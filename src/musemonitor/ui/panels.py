"""Extension panels in the menu bar: **Analysis** and **HCI/BCI**.

Every tab an extension adds is a *panel*. The three built-in tabs always show; a panel shows only while
it is ticked in its menu. Which menu and group is decided by the extension's ``category``
(plugins.api.CATEGORIES); unknown categories go to Analysis ▸ Other. Ticks are remembered per window
kind ("live" / "review") and panel in QSettings; a panel never seen before starts hidden, and the live
window announces it once in the status bar.

See debate/claude-extension-placement-proposal.md.
"""
from PySide6 import QtCore

from ..plugins.api import CATEGORIES, MENUS, category_of

SHOWN_KEY = "panels/{kind}/{owner}/{title}"
SEEN_KEY = "panels/seen/{owner}/{title}"


class Panel:
    def __init__(self, owner, ext_name, tab, category):
        self.owner, self.ext_name, self.tab, self.category = owner, ext_name, tab, category
        self.title = tab.title
        self.shown = False
        self.action = None

    @property
    def location(self):
        return f"{CATEGORIES[self.category]} ▸ {self.category} ▸ {self.title}"


class PanelMenus:
    def __init__(self, window, page, settings, kind="live"):
        """window: QMainWindow whose menu bar gets the menus; page: RecordingPage holding the tabs."""
        self.window, self.page, self.settings, self.kind = window, page, settings, kind
        self.menus = {m: window.menuBar().addMenu(m) for m in MENUS}
        self.panels = []
        self.new_panels = []                    # first seen in this window (announced once, live only)
        self.rebuild()

    # ---- panels -----------------------------------------------------------------------------------
    def _key(self, p):
        return SHOWN_KEY.format(kind=self.kind, owner=p.owner, title=p.title)

    def add(self, owner, ext_name, tab, category, shown=None):
        """Register an extension tab (already added to the page) and hide or show it."""
        p = Panel(owner, ext_name, tab, category_of(category))
        key = self._key(p)
        if self.settings.contains(key):
            on = str(self.settings.value(key)).lower() in ("true", "1")
        else:
            on = bool(shown)
        seen = SEEN_KEY.format(owner=owner, title=p.title)
        if self.kind == "live" and not self.settings.contains(seen):
            self.settings.setValue(seen, True); self.new_panels.append(p)
        self.panels.append(p)
        self.set_shown(p, on, save=False)
        self.rebuild()
        return p

    def remove_owner(self, owner):
        self.panels = [p for p in self.panels if p.owner != owner]
        self.new_panels = [p for p in self.new_panels if p.owner != owner]
        self.rebuild()

    def find(self, title):
        return next((p for p in self.panels if p.title == title), None)

    def of_owner(self, owner):
        return [p for p in self.panels if p.owner == owner]

    def set_shown(self, p, on, save=True, select=False):
        p.shown = bool(on)
        self.page.set_tab_shown(p.tab, p.shown)
        if p.shown and select: self.page.tabs.setCurrentWidget(p.tab)
        if save: self.settings.setValue(self._key(p), p.shown)
        if p.action is not None and p.action.isChecked() != p.shown:
            p.action.blockSignals(True); p.action.setChecked(p.shown); p.action.blockSignals(False)

    def set_all(self, menu, on):
        for p in self.panels:
            if CATEGORIES[p.category] == menu: self.set_shown(p, on)

    # ---- menus ------------------------------------------------------------------------------------
    def rebuild(self):
        for p in self.panels: p.action = None
        for menu_name, menu in self.menus.items():
            menu.clear()
            groups = [g for g, m in CATEGORIES.items() if m == menu_name]
            any_panel = False
            for g in groups:
                items = [p for p in self.panels if p.category == g]
                if not items: continue
                any_panel = True
                sub = menu.addMenu(g)
                for p in items:
                    act = sub.addAction(p.title)
                    act.setCheckable(True); act.setChecked(p.shown)
                    act.setToolTip(f"Show the {p.title} panel (extension {p.ext_name})")
                    act.toggled.connect(lambda on, p=p: self.set_shown(p, on, select=on))
                    p.action = act
            if any_panel:
                menu.addSeparator()
                menu.addAction("Show all panels", lambda m=menu_name: self.set_all(m, True))
                menu.addAction("Hide all panels", lambda m=menu_name: self.set_all(m, False))
            else:
                menu.addAction("No extension panels").setEnabled(False)

    def announce(self):
        """Status-bar note for panels this user has never seen (they start hidden)."""
        if not self.new_panels: return ""
        if len(self.new_panels) == 1:
            msg = f"New panel '{self.new_panels[0].title}' — {self.new_panels[0].location.rsplit(' ▸ ', 1)[0]}"
        else:
            where = sorted({CATEGORIES[p.category] for p in self.new_panels})
            msg = (f"{len(self.new_panels)} new extension panels — tick them in the {' and '.join(where)} "
                   f"menu{'s' if len(where) > 1 else ''}")
        self.new_panels = []
        QtCore.QTimer.singleShot(0, lambda: self.window.statusBar().showMessage(msg, 12000))
        return msg
