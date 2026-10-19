"""B1 reload of file extensions, B3 keys claimed by extension tabs, B5 extension status messages
(debate/claude-ux-bottlenecks-proposal.md)."""
import os
import textwrap
from pathlib import Path

import pytest
from PySide6 import QtCore, QtTest, QtWidgets

from musemonitor.plugins import loader
from musemonitor.ui import main_window as mw
from musemonitor.ui.widgets.ext_status import ExtensionStatus


def write(d, name, body):
    p = Path(d) / name
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def versioned(tag, marker=None):
    """An extension with one tab ("Panel") and one action; ``tag`` identifies the code version."""
    return f"""
        from musemonitor.plugins.api import Extension, BaseTab
        class Panel(BaseTab):
            title = "Panel"
        class Versioned(Extension):
            id = "versioned"
            TAG = "{tag}"
            def activate(self, app):
                self.connected = None
                self.tab = app.add_tab(Panel)
                app.add_action("Ping", lambda: None)
                app.show_status("hello from {tag}", 0)
            def on_connected(self, name): self.connected = name
            def deactivate(self):
                if {marker!r}: open({marker!r}, "a").write("{tag} closed\\n")
        EXTENSION = Versioned
    """


@pytest.fixture
def make_window(qapp, spec, settings, monkeypatch):
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    made = []

    def make(dirs):
        w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(d) for d in dirs])
        w.resize(1200, 800); w.show(); made.append(w)
        return w
    yield make
    for w in made: w.connected = False; w.close()


def rec_of(w, ext_id="versioned"):
    return next(r for r in w.extensions.records if r.id == ext_id)


def ext_actions(w):
    return [a.text() for a in w.ext_menu.actions() if a.menu()]


# ---- B1: reload --------------------------------------------------------------------------------------
def test_reload_runs_new_code_even_within_the_same_second(make_window, tmp_path):
    d = tmp_path / "ext"; d.mkdir(); marker = tmp_path / "closed.txt"
    f = write(d, "versioned.py", versioned("AAA1", str(marker)))
    w = make_window([d])
    old = rec_of(w).instance
    assert old.TAG == "AAA1"
    st = f.stat()
    write(d, "versioned.py", versioned("AAA2", str(marker)))              # same size …
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))                         # … and same mtime: a stale .pyc would win
    new, msg = w.extensions.reload("versioned")
    assert new.instance.TAG == "AAA2" and new.status == "active" and "reloaded" in msg
    assert marker.read_text() == "AAA1 closed\n"                            # the old instance was deactivated
    assert ext_actions(w) == ["versioned"]                                  # its submenu is not duplicated
    titles = [w.rec_page.tabs.tabText(i) for i in range(w.rec_page.tabs.count())]
    assert titles.count("Panel") == 1 and old.tab not in w.rec_page.tab_list


def test_reload_keeps_panel_tick_and_catches_up_with_connection(make_window, tmp_path):
    d = tmp_path / "ext"; d.mkdir()
    write(d, "versioned.py", versioned("A"))
    w = make_window([d])
    panel = w.panels.find("Panel"); w.panels.set_shown(panel, True)
    w.streaming, w.device_name = True, "MuseS-TEST"
    write(d, "versioned.py", versioned("B"))
    new, _ = w.extensions.reload("versioned")
    p2 = w.panels.find("Panel")
    assert p2 is not panel and p2.shown and w.rec_page.tabs.isTabVisible(w.rec_page.tabs.indexOf(p2.tab))
    assert new.instance.connected == "MuseS-TEST"                          # on_connected replayed
    assert w.extensions.records.index(new) == 0                             # same row in Manage
    w.streaming = False


def test_reload_changed_only_touches_edited_files(make_window, tmp_path):
    d = tmp_path / "ext"; d.mkdir()
    write(d, "versioned.py", versioned("A"))
    write(d, "other.py", """
        from musemonitor.plugins.api import Extension
        class Other(Extension): pass
    """)
    w = make_window([d])
    other = rec_of(w, "other").instance
    done, msg = w.reload_changed_extensions(), w.statusBar().currentMessage()
    assert done == [] and "No extension changed" in msg
    f = write(d, "versioned.py", versioned("B"))
    st = f.stat(); os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    done = w.reload_changed_extensions()
    assert [r.id for r in done] == ["versioned"] and done[0].instance.TAG == "B"
    assert rec_of(w, "other").instance is other                            # untouched
    assert w.extensions.changed() == []


def test_reload_refused_while_recording_in_review_and_for_packages(make_window, tmp_path):
    d = tmp_path / "ext"; d.mkdir()
    write(d, "versioned.py", versioned("A"))
    w = make_window([d])
    inst = rec_of(w).instance
    w.recording = True
    new, msg = w.extensions.reload("versioned")
    assert new is None and "stop recording" in msg and rec_of(w).instance is inst
    f = d / "versioned.py"; st = f.stat(); os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    done, msg = w.extensions.reload_changed()
    assert done == [] and "stop recording" in msg
    w.recording = False
    rec_of(w).source = "package: some_pkg:Ext"
    assert "installed as a package" in w.extensions.reload_refusal(rec_of(w))
    rec_of(w).source = str(f)
    w.is_review = True
    assert "live window" in w.extensions.reload_refusal(rec_of(w))
    del w.is_review


def test_reload_with_import_error_then_fixed(make_window, tmp_path):
    d = tmp_path / "ext"; d.mkdir()
    f = write(d, "versioned.py", versioned("A"))
    w = make_window([d])
    f.write_text("this is not python (\n")
    new, msg = w.extensions.reload("versioned")
    assert new.status == "error" and "SyntaxError" in new.error and "failed to reload" in msg
    assert ext_actions(w) == [] and w.panels.find("Panel") is None          # old UI removed, app still running
    assert w.ext_msg.text() == ""                                           # and its status message
    f.write_text(textwrap.dedent(versioned("C")))
    st = f.stat(); os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    done = w.reload_changed_extensions()                                    # error records are reloaded too
    assert done and done[0].status == "active" and done[0].instance.TAG == "C"


def test_reload_crashed_extension_removes_its_old_tab(make_window, tmp_path):
    d = tmp_path / "ext"; d.mkdir()
    write(d, "versioned.py", versioned("A"))
    w = make_window([d])
    old_tab = rec_of(w).instance.tab
    w.extensions.fail("versioned", RuntimeError("boom"), where="test")
    assert rec_of(w).status == "error" and old_tab in w.rec_page.tab_list   # crash leaves the tab behind
    new, _ = w.extensions.reload("versioned")
    assert new.status == "active" and old_tab not in w.rec_page.tab_list
    assert [t.title for t in w.rec_page.tab_list].count("Panel") == 1


def test_package_extension_with_submodule_is_reimported(make_window, tmp_path):
    d = tmp_path / "ext"; pkg = d / "pkgext"; pkg.mkdir(parents=True)
    write(pkg, "helper.py", "VALUE = 'one'\n")
    write(pkg, "__init__.py", """
        from musemonitor.plugins.api import Extension
        from .helper import VALUE
        class PkgExt(Extension):
            id = "pkgext"
            def activate(self, app): self.value = VALUE
    """)
    w = make_window([d])
    assert rec_of(w, "pkgext").instance.value == "one"
    write(pkg, "helper.py", "VALUE = 'two'\n")
    new, _ = w.extensions.reload("pkgext")
    assert new.instance.value == "two"                                      # sub-module came from disk again
    assert loader.module_name(pkg) + ".helper" in __import__("sys").modules


def test_manage_dialog_reload_button(make_window, tmp_path):
    from musemonitor.ui.widgets.extensions_dialog import ExtensionsDialog
    d = tmp_path / "ext"; d.mkdir()
    write(d, "versioned.py", versioned("A"))
    w = make_window([d])
    dlg = ExtensionsDialog(w.extensions, w)
    dlg.table.selectRow(0)
    assert dlg.reload_btn.isEnabled()
    write(d, "versioned.py", versioned("B"))
    dlg.reload_btn.click()
    assert rec_of(w).instance.TAG == "B" and "reloaded" in dlg.result.text()
    w.recording = True; dlg._show_details()
    assert not dlg.reload_btn.isEnabled() and "stop recording" in dlg.reload_btn.toolTip()
    w.recording = False; dlg.close()


def test_reload_shortcut(make_window, tmp_path):
    w = make_window([])
    assert w.reload_action.shortcut() == mw.RELOAD_KEY


# ---- B3: keys claimed by extension tabs --------------------------------------------------------------
KEYTAB = """
    from PySide6 import QtCore
    from musemonitor.plugins.api import Extension, BaseTab
    class Keys(BaseTab):
        title = "Keys"
        wants_keys = {QtCore.Qt.Key_1}
        def __init__(self, ctx):
            super().__init__(ctx); self.got = []; self.setFocusPolicy(QtCore.Qt.StrongFocus)
        def keyPressEvent(self, ev): self.got.append(ev.key())
    class KeyExt(Extension):
        id = "keyext"
        def activate(self, app): self.tab = app.add_tab(Keys, shown=True)
"""


def test_tab_that_claims_keys_gets_them_others_still_mark(make_window, tmp_path, monkeypatch):
    d = tmp_path / "ext"; d.mkdir()
    write(d, "keyext.py", KEYTAB)
    w = make_window([d])
    monkeypatch.setattr(mw.MainWindow, "isActiveWindow", lambda self: True)
    monkeypatch.setattr(mw, "ask_event_label", lambda *a, **k: "spaced")
    w.stack.setCurrentIndex(mw.PAGE_RECORDING)
    tab = rec_of(w, "keyext").instance.tab
    w.rec_page.tabs.setCurrentWidget(tab); tab.setFocus()
    QtTest.QTest.keyClick(tab, QtCore.Qt.Key_1)
    assert tab.got == [QtCore.Qt.Key_1] and len(w.markers) == 0           # claimed: the tab gets it, no event
    QtTest.QTest.keyClick(tab, QtCore.Qt.Key_2)
    QtTest.QTest.keyClick(tab, QtCore.Qt.Key_Space)
    assert [e[1] for e in w.markers.events] == ["2", "spaced"]             # not claimed: app shortcuts still work
    type(tab).wants_all_keys = True
    QtTest.QTest.keyClick(tab, QtCore.Qt.Key_Space)
    assert tab.got[-1] == QtCore.Qt.Key_Space and len(w.markers) == 2
    type(tab).wants_all_keys = False
    w.rec_page.tabs.setCurrentIndex(0); w.rec_page.signals_tab.setFocus()
    QtTest.QTest.keyClick(w.rec_page.signals_tab, QtCore.Qt.Key_1)
    assert w.markers.events[-1][1] == "1"                                  # outside the tab: quick event as before


# ---- B5: extension status messages -------------------------------------------------------------------
@pytest.mark.parametrize("ms, expected", [(5000, 5000), (0, 15000), (-1, 15000), (60000, 15000), (2.5, 2),
                                          (None, 5000), ("soon", 5000), (float("nan"), 5000), ("800", 800)])
def test_status_duration_edge_cases(ms, expected):
    assert ExtensionStatus.duration(ms) == expected


def test_status_text_edge_cases(qapp):
    s = ExtensionStatus()
    s.show_message("a", "line one\n\n  line two  \n")
    assert s.text() == "🧩 a: line one · line two" and s.owner == "a"
    s.show_message("a", "<b>bold</b>")
    assert s.text() == "🧩 a: <b>bold</b>" and s.textFormat() == QtCore.Qt.PlainText
    s.show_message("a", 42)
    assert s.text() == "🧩 a: 42"
    s.show_message("b", "")                                                # b clears only its own message
    assert s.owner == "a" and s.text()
    s.show_message("a", None)
    assert s.text() == "" and s.owner is None and not s._timer.isActive()
    s.show_message("a", "x"); s.show_message("b", "y")
    s.clear_owner("a")
    assert s.text() == "🧩 b: y"                                           # a newer message from b stays


def test_status_cleared_when_extension_unloaded_or_fails(make_window, tmp_path):
    d = tmp_path / "ext"; d.mkdir()
    write(d, "versioned.py", versioned("A"))
    w = make_window([d])
    assert w.ext_msg.text() == "🧩 versioned: hello from A"
    w.extensions.unload("versioned")
    assert w.ext_msg.text() == ""
    w.extensions.load("versioned")
    assert w.ext_msg.owner == "versioned"
    w.extensions.fail("versioned", RuntimeError("boom"), where="test")
    assert w.ext_msg.text() == ""
