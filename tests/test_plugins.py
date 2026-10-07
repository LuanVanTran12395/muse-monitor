"""Extension system: discovery/loading, error isolation, enable/disable, scaffold, and the sample extensions in extensions/."""
import textwrap
from pathlib import Path

import pytest
from PySide6 import QtCore, QtWidgets

import synthetic as S
from musemonitor.plugins import loader
from musemonitor.plugins.scaffold import create_extension, slugify
from musemonitor.ui import main_window as mw

T0 = 1.79e9
REPO_EXT = Path(__file__).resolve().parents[1] / "extensions"


def write(d, name, body):
    p = Path(d) / name
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


GOOD = """
    from musemonitor.plugins.api import Extension
    class Good(Extension):
        name = "Good"
        def activate(self, app):
            self.seen = []
            app.add_action("Good: ping", lambda: self.seen.append("ping"))
        def on_eeg(self, x, ts): self.seen.append(("eeg", x.shape, ts))
        def on_event(self, t, label): self.seen.append(("event", label))
    EXTENSION = Good
"""
CRASHY = """
    from musemonitor.plugins.api import Extension
    class Crashy(Extension):
        def on_eeg(self, x, ts): raise RuntimeError("boom")
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
    for w in made: w.close()


def feed(w, spec, sec=10):
    fs, ofs, ifs = spec.eeg.fs, spec.optics.fs, spec.imu.fs
    e, o, m = S.eeg(fs, sec), S.optics(ofs, sec), S.imu(ifs, sec)
    for k in range(sec):
        w.on_data(e[:, k * fs:(k + 1) * fs], T0 + k + 1)
        w.on_optics(o[:, k * ofs:(k + 1) * ofs], T0 + k + 1)
        w.on_imu(m[:, k * ifs:(k + 1) * ifs], T0 + k + 1)


# ---- loader -------------------------------------------------------------------
def test_discover_file_package_and_errors(tmp_path):
    write(tmp_path, "good.py", GOOD)
    pkg = tmp_path / "pkg_ext"; pkg.mkdir()
    write(pkg, "helpers.py", "VALUE = 42\n")
    write(pkg, "__init__.py", """
        from musemonitor.plugins.api import Extension
        from .helpers import VALUE          # relative imports inside a package must work
        class Pkg(Extension):
            id = "custom_id"
            description = f"value={VALUE}"
    """)
    write(tmp_path, "broken.py", "raise ImportError('missing dependency')\n")
    write(tmp_path, "_ignored.py", "raise SystemExit\n")          # starts with _ → skipped
    found = {d.id: d for d in loader.discover([tmp_path], use_entry_points=False)}
    assert set(found) == {"good", "custom_id", "broken"}
    assert found["custom_id"].cls.description == "value=42"
    assert "missing dependency" in found["broken"].error and found["broken"].cls is None


# ---- manager qua MainWindow ---------------------------------------------------------
def test_hooks_actions_and_events(make_window, spec, tmp_path):
    write(tmp_path, "good.py", GOOD)
    w = make_window([tmp_path])
    rec = w.extensions.records[0]
    assert rec.status == "active"
    feed(w, spec, sec=2)
    ext = rec.instance
    assert ext.seen[0] == ("eeg", (spec.eeg.n, spec.eeg.fs), T0 + 1)
    w.add_event("stimulus")
    assert ("event", "stimulus") in ext.seen and len(w.markers) == 1
    act = next(a for a in w.ext_menu.actions() if a.text() == "Good: ping")
    act.trigger()
    assert ext.seen[-1] == "ping"


def test_crashing_extension_is_isolated(make_window, spec, tmp_path):
    write(tmp_path, "good.py", GOOD); write(tmp_path, "crashy.py", CRASHY)
    w = make_window([tmp_path])
    feed(w, spec, sec=3)                                     # must not raise
    recs = {r.id: r for r in w.extensions.records}
    assert recs["crashy"].status == "error" and "boom" in recs["crashy"].error
    assert recs["good"].status == "active"
    assert sum(1 for s in recs["good"].instance.seen if s[0] == "eeg") == 3     # still receives all data
    assert w.ctx.store.eeg.n == 3 * spec.eeg.fs


def test_crashing_tab_is_disabled(make_window, spec, tmp_path):
    write(tmp_path, "badtab.py", """
        from musemonitor.plugins.api import BaseTab, Extension
        class Bad(BaseTab):
            title = "Bad"
            def on_analysis(self): raise ValueError("tab bug")
        class BadTab(Extension):
            def activate(self, app): app.add_tab(Bad)
    """)
    w = make_window([tmp_path])
    rp = w.rec_page
    w.stack.setCurrentIndex(mw.PAGE_RECORDING)
    rp.tabs.setCurrentIndex(rp.tabs.count() - 1); w.update_analysis()
    assert not rp.tabs.isTabEnabled(rp.tabs.count() - 1)
    assert w.extensions.records[0].status == "error" and "tab bug" in w.extensions.records[0].error
    w.update_analysis()                                      # the broken tab is not called again


def test_disable_and_api_version(make_window, settings, tmp_path):
    write(tmp_path, "good.py", GOOD)
    write(tmp_path, "future.py", """
        from musemonitor.plugins.api import Extension
        class Future(Extension):
            requires_api = 999
    """)
    settings.setValue("extensions/disabled", ["good"])
    w = make_window([tmp_path])
    recs = {r.id: r for r in w.extensions.records}
    assert recs["good"].status == "disabled" and recs["good"].instance is None
    assert recs["future"].status == "incompatible"
    w.extensions.set_enabled("good", True)
    assert "good" not in w.extensions.disabled_ids()


# ---- scaffold + sample extensions --------------------------------------------------------
def test_scaffold_creates_loadable_extension(make_window, spec, tmp_path):
    assert slugify("My Cool Ext!") == "my_cool_ext"
    folder = create_extension("My Cool Ext", tmp_path)
    with pytest.raises(FileExistsError): create_extension("My Cool Ext", tmp_path)
    w = make_window([tmp_path])
    rec = w.extensions.records[0]
    assert rec.id == "my_cool_ext" and rec.status == "active", rec.error
    feed(w, spec, sec=3)
    rp = w.rec_page; w.stack.setCurrentIndex(mw.PAGE_RECORDING)
    rp.tabs.setCurrentIndex(rp.tabs.count() - 1); w.update_analysis()
    assert rp.tabs.tabText(rp.tabs.count() - 1) == "My Cool Ext"
    assert rp.tabs.isTabEnabled(rp.tabs.count() - 1)
    assert folder.name == "my_cool_ext"


def test_bundled_examples(make_window, spec, tmp_path):
    w = make_window([REPO_EXT])
    recs = {r.id: r for r in w.extensions.records}
    assert recs["band_power"].status == "active", recs["band_power"].error
    assert recs["hello_world"].status == "active", recs["hello_world"].error
    bp = recs["band_power"].instance
    path = tmp_path / "rec.csv"
    bp.on_recording_started(str(path))
    feed(w, spec, sec=6)
    bp.on_recording_stopped()
    assert len(bp.history) >= 3
    alpha = [h[1][2] for h in bp.history]                   # synthetic signal = 10 Hz alpha
    assert min(alpha) > 80
    lines = (tmp_path / "rec_bandpower.csv").read_text().splitlines()
    assert lines[0].startswith("timestamp,delta_pct") and len(lines) >= 4
    for theme in ("Light", "Dark"): w.apply_theme(theme)
    rp = w.rec_page; w.stack.setCurrentIndex(mw.PAGE_RECORDING)
    bp_tab = next(t for t in rp.tab_list if t.owner == "band_power")   # no assumption about tab order
    rp.tabs.setCurrentWidget(bp_tab); w.update_analysis()
    assert "alpha" in bp_tab.info.text()


# ---- Update: load new extensions while the app is running -----------------------------------
COUNTING = """
    from pathlib import Path
    from musemonitor.plugins.api import BaseTab, Extension
    _log = Path(__file__).with_name("imports.log")
    _log.write_text(_log.read_text() + "x" if _log.exists() else "x")   # counts how many times the module is imported
    class LateTab(BaseTab):
        title = "Late"
    class Late(Extension):
        def activate(self, app):
            self.calls = []
            app.add_tab(LateTab)
        def on_theme_changed(self, th): self.calls.append("theme")
        def on_connected(self, name): self.calls.append(("connected", name))
        def on_recording_started(self, path): self.calls.append(("recording", path))
    EXTENSION = Late
"""


def test_refresh_loads_new_extension_without_reimporting_old(make_window, tmp_path):
    write(tmp_path, "good.py", GOOD)
    w = make_window([tmp_path])
    n_tabs = w.rec_page.tabs.count()
    assert w.extensions.refresh() == []                       # nothing new yet
    write(tmp_path, "late.py", COUNTING)
    w.streaming, w.device_name = True, "MuseS-TEST"           # app is streaming + recording
    w.recording, w.rec_path = True, str(tmp_path / "rec.csv")
    changed = w.check_new_extensions()
    assert [r.id for r in changed] == ["late"] and changed[0].status == "active"
    assert changed[0].instance.calls == ["theme", ("connected", "MuseS-TEST"), ("recording", str(tmp_path / "rec.csv"))]
    assert w.rec_page.tabs.count() == n_tabs + 1 and w.rec_page.tabs.tabText(n_tabs) == "Late"
    assert w.extensions.refresh() == []                       # next time: no reload/re-import
    assert (tmp_path / "imports.log").read_text() == "x"
    assert "1 new extension" in w.statusBar().currentMessage()
    w.recording = w.streaming = False


def test_refresh_retries_extension_that_failed_to_import(make_window, tmp_path):
    write(tmp_path, "fixme.py", "raise ImportError('typo')\n")
    w = make_window([tmp_path])
    assert w.extensions.records[0].status == "error"
    write(tmp_path, "fixme.py", GOOD)                        # the user fixes the file
    changed = w.extensions.refresh()
    assert len(w.extensions.records) == 1 and changed[0].status == "active"


def test_update_button_in_manage_dialog(make_window, tmp_path):
    from musemonitor.ui.widgets.extensions_dialog import ExtensionsDialog
    w = make_window([tmp_path])
    dlg = ExtensionsDialog(w.extensions, w)
    write(tmp_path, "good.py", GOOD)
    btn = next(b for b in dlg.findChildren(QtWidgets.QPushButton) if "Update" in b.text())
    btn.click()
    assert dlg.table.rowCount() == 1 and "loaded: Good" in dlg.result.text()
    dlg.close()


# ---- Unload / Load mid-session ------------------------------------------------
TABBED = """
    import pyqtgraph as pg
    from PySide6 import QtWidgets
    from musemonitor.plugins.api import BaseTab, Extension
    class T(BaseTab):
        title = "Tabbed"
        def __init__(self, ctx):
            super().__init__(ctx)
            pw = ctx.plots.widget(pg.PlotWidget()); ctx.plots.plot(pw.getPlotItem(), marker="eeg", marker_label=True)
            QtWidgets.QVBoxLayout(self).addWidget(pw)
    class Tabbed(Extension):
        def activate(self, app):
            self.seen = 0; self.closed = False
            app.add_tab(T); app.add_action("Tabbed: ping", lambda: None)
        def on_eeg(self, x, ts): self.seen += 1
        def deactivate(self): self.closed = True
    EXTENSION = Tabbed
"""


def test_unload_and_reload_extension_during_session(make_window, spec, tmp_path):
    write(tmp_path, "tabbed.py", TABBED)
    w = make_window([tmp_path])
    rp, reg = w.rec_page, w.ctx.plots
    n_tabs, n_plots, n_targets = rp.tabs.count(), len(reg.plots), len(reg.marker_targets)
    w.add_event("before unload")
    inst = w.extensions.records[0].instance
    assert w.extensions.unload("tabbed") is True
    rec = w.extensions.records[0]
    assert rec.status == "unloaded" and inst.closed                       # deactivate() was called
    assert rp.tabs.count() == n_tabs - 1 and all(t.owner != "tabbed" for t in rp.tab_list)
    assert not any(a.text() == "Tabbed: ping" for a in w.ext_menu.actions())
    assert len(reg.plots) == n_plots - 1 and len(reg.marker_targets) == n_targets - 1
    feed(w, spec, sec=2)                                                  # hooks are no longer called
    assert inst.seen == 0
    for theme in ("Light", "Dark"): w.apply_theme(theme)                  # does not touch deleted widgets
    w.stack.setCurrentIndex(mw.PAGE_RECORDING); w.redraw(); w.add_event("after unload")
    assert w.extensions.load("tabbed") == "active"                        # reloaded mid-session
    assert rp.tabs.count() == n_tabs and w.extensions.records[0].instance is not inst
    feed(w, spec, sec=1)
    assert w.extensions.records[0].instance.seen == 1


def test_manage_dialog_unload_button(make_window, tmp_path):
    from musemonitor.ui.widgets.extensions_dialog import ExtensionsDialog
    write(tmp_path, "tabbed.py", TABBED)
    w = make_window([tmp_path])
    dlg = ExtensionsDialog(w.extensions, w)
    dlg.table.selectRow(0)
    assert dlg.toggle_btn.text() == "Unload" and dlg.toggle_btn.isEnabled()
    dlg.toggle_btn.click()
    assert w.extensions.records[0].status == "unloaded" and dlg.toggle_btn.text() == "Load"
    dlg.toggle_btn.click()
    assert w.extensions.records[0].status == "active"
    dlg.close()
