"""Extension panels in the menu bar (debate/claude-extension-placement-proposal.md, option A with an HCI/BCI menu):
panels hidden until ticked, grouped by category, remembered per window kind; actions in per-extension submenus;
the scaffold suggests a category."""
import pytest

from musemonitor.device.profiles import athena_profile
from musemonitor.plugins.__main__ import main as plugins_cli
from musemonitor.plugins.api import CATEGORIES, menu_location
from musemonitor.plugins.loader import PROJECT_DIR
from musemonitor.plugins.scaffold import create_extension, suggest_category
from musemonitor.ui import main_window as mw
from musemonitor.ui.review_window import ReviewWindow
from musemonitor.ui.widgets.extensions_dialog import ExtensionsDialog
from test_review import write_session


@pytest.fixture
def make(qapp, spec, settings, monkeypatch):
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    made = []

    def build(dirs=(PROJECT_DIR,)):
        w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(d) for d in dirs]); w.show()
        made.append(w); return w
    yield build
    for w in made: w.close()


def menu(w, title):
    return next(a.menu() for a in w.menuBar().actions() if a.text() == title)


def tree(m):
    """{submenu: [item texts]} of a menu (top-level plain items under '')."""
    out = {}
    for a in m.actions():
        if a.menu() is not None: out[a.text()] = [x.text() for x in a.menu().actions()]
        elif a.text(): out.setdefault("", []).append(a.text())
    return out


def tab_visible(w, title):
    rp = w.rec_page
    i = next(i for i in range(rp.tabs.count()) if rp.tabs.tabText(i) == title)
    return rp.tabs.isTabVisible(i)


def test_menu_bar_and_groups(make):
    w = make()
    assert [a.text() for a in w.menuBar().actions()] == ["File", "Analysis", "HCI/BCI", "Extensions"]
    an, hci = tree(menu(w, "Analysis")), tree(menu(w, "HCI/BCI"))
    assert an["EEG"] == ["Band power"] and an["Data quality"] == ["Artifacts"]
    assert an[""] == ["Show all panels", "Hide all panels"]
    assert hci["Eyes"] == ["Eyes · EEG/alpha"] and hci["Motion"] == ["3D head", "3D head +"]
    assert "Heart & optics" not in an                                 # empty groups are not shown
    ext = tree(menu(w, "Extensions"))
    assert ext["Band Power"] == ["Clear history"] and ext["Artifact Log"] == ["Clear list"]
    assert ext["Hello World"] == ["Say hi"]
    assert ext[""] == ["Check for new extensions", "Manage extensions…"]


def test_panels_start_hidden_and_follow_the_menu(make, settings):
    w = make()
    rp = w.rec_page
    assert [tab_visible(w, t) for t in ("Signals", "EEG PSD", "PPG · HRV · fNIRS")] == [True] * 3
    for t in ("Band power", "Artifacts", "Eyes · EEG/alpha", "3D head", "3D head +"):
        assert not tab_visible(w, t)
    p = w.panels.find("Artifacts")
    p.action.trigger()                                                # tick
    assert tab_visible(w, "Artifacts") and rp.tabs.currentWidget() is p.tab
    p.action.trigger()                                                # untick the selected panel
    assert not tab_visible(w, "Artifacts") and rp.tabs.currentIndex() == 0
    w.panels.find("3D head").action.trigger()
    w.close()
    w2 = make()                                                       # remembered
    assert tab_visible(w2, "3D head") and not tab_visible(w2, "Artifacts")
    assert w2.panels.find("3D head").action.isChecked()


def test_show_all_and_hide_all_per_menu(make):
    w = make()
    hci = menu(w, "HCI/BCI")
    next(a for a in hci.actions() if a.text() == "Show all panels").trigger()
    assert all(tab_visible(w, t) for t in ("Eyes · EEG/alpha", "3D head", "3D head +"))
    assert not tab_visible(w, "Band power")                           # other menu untouched
    next(a for a in hci.actions() if a.text() == "Hide all panels").trigger()
    assert not any(tab_visible(w, t) for t in ("Eyes · EEG/alpha", "3D head", "3D head +"))


def test_new_panels_announced_once(make):
    w = make()
    assert w.panels.new_panels == []                                  # announced and cleared
    w.close()
    w2 = make()
    assert w2.panels.announce() == ""


def test_unload_and_load_update_menus(make):
    w = make()
    w.panels.find("Band power").action.trigger()
    assert w.extensions.unload("band_power")
    assert "EEG" not in tree(menu(w, "Analysis")) and "Band Power" not in tree(menu(w, "Extensions"))
    assert w.extensions.load("band_power") == "active"
    assert tree(menu(w, "Analysis"))["EEG"] == ["Band power"] and "Band Power" in tree(menu(w, "Extensions"))
    assert tab_visible(w, "Band power")                               # choice kept


CUSTOM = '''
from musemonitor.plugins.api import BaseTab, Extension

class T(BaseTab):
    title = "{title}"

class E(Extension):
    {category}
    def activate(self, app): app.add_tab(T{shown})

EXTENSION = E
'''


def test_category_defaults_and_initial_shown(make, tmp_path):
    (tmp_path / "plain.py").write_text(CUSTOM.format(title="Plain", category="", shown=""))
    (tmp_path / "odd.py").write_text(CUSTOM.format(title="Odd", category='category = "Telepathy"', shown=""))
    (tmp_path / "eager.py").write_text(CUSTOM.format(title="Eager", category='category = "Eyes"', shown=", shown=True"))
    w = make([tmp_path])
    an, hci = tree(menu(w, "Analysis")), tree(menu(w, "HCI/BCI"))
    assert set(an["Other"]) == {"Plain", "Odd"} and hci["Eyes"] == ["Eager"]
    assert tab_visible(w, "Eager") and not tab_visible(w, "Plain")
    assert menu_location("Telepathy") == "Analysis ▸ Other" and CATEGORIES["Motion"] == "HCI/BCI"


def test_no_panels_menu_placeholder(make, tmp_path):
    w = make([])
    assert [a.text() for a in menu(w, "Analysis").actions()] == ["No extension panels"]
    assert not menu(w, "HCI/BCI").actions()[0].isEnabled()


def test_review_window_has_its_own_choices(make, qapp, settings, spec, tmp_path):
    from musemonitor.storage.reader import inspect, load, locate
    w = make()
    w.panels.find("Band power").action.trigger()
    folder, _ = write_session(spec, tmp_path / "s", sec=20, events=())
    rw = ReviewWindow(load(inspect(locate(folder), [athena_profile()])), settings, profile=athena_profile(),
                      extension_dirs=[str(PROJECT_DIR)], replay=False)
    assert [a.text() for a in rw.menuBar().actions()] == ["File", "Analysis", "HCI/BCI", "Extensions"]
    assert tree(menu(rw, "HCI/BCI"))[""] == ["No extension panels"]          # Eyes / Motion are live-only
    assert not rw.panels.find("Band power").shown                                # live choice not copied
    rw.panels.find("Artifacts").action.trigger()
    assert rw.panels.find("Artifacts").shown and not w.panels.find("Artifacts").shown
    rw.close()


def test_manage_dialog_shows_menu_location(make):
    w = make()
    d = ExtensionsDialog(w.extensions, w)
    rows = {d.table.item(i, 1).text().split("  (")[0]: d.table.item(i, 4).text() for i in range(d.table.rowCount())}
    assert rows["Band Power"] == "Analysis ▸ EEG" and rows["Eye Interaction"] == "HCI/BCI ▸ Eyes"
    assert rows["Hello World"] == "Extensions ▸ Hello World (actions only)"
    d.close()


# ---- scaffold ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("name, cat", [("Alpha Peak", "EEG"), ("Wink Mouse", "Eyes"), ("Head Nod Control", "Motion"),
                                       ("Resonance Breathing HRV", "Heart & optics"), ("Noise Meter", "Data quality"),
                                       ("Stopwatch", "Other")])
def test_suggest_category(name, cat):
    assert suggest_category(name) == cat


def test_scaffold_category_and_cli(tmp_path, capsys):
    folder = create_extension("Gaze Typing", tmp_path)
    src = (folder / "__init__.py").read_text()
    assert 'category = "Eyes"' in src and "HCI/BCI ▸ Eyes" in src
    with pytest.raises(ValueError, match="unknown category"):
        create_extension("X", tmp_path, category="Telepathy")
    assert plugins_cli(["new", "Calm Score", "--category", "Data quality", "--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Analysis ▸ Data quality ▸ Calm Score" in out and "Suggested" not in out
    plugins_cli(["new", "Alpha Peak", "--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert "Suggested category from the name: EEG" in out and "Analysis ▸ EEG ▸ Alpha Peak" in out
