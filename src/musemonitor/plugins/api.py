"""Public API for extensions — extensions should ONLY import from this module.

Minimal example (save as ``extensions/hello.py``)::

    from musemonitor.plugins.api import Extension

    class Hello(Extension):
        name = "Hello"
        def activate(self, app):
            app.add_action("Say hello", lambda: app.show_status("Hello!"))
        def on_event(self, t, label):
            print("event", t, label)

    EXTENSION = Hello

Every hook runs on the GUI thread: keep it fast (on_eeg is called ~50 times/s). Do heavy work
in a tab's ``on_analysis``, a dedicated QTimer, or a separate thread.

API 2 adds review windows (File ▸ Open session). An extension runs there only if it sets
``supports_review = True``; the recording is then replayed through the data hooks in 0.1 s chunks,
``app.is_review`` is True and ``on_view_changed(t_end)`` follows the scrollbar. Extensions written
for API 1 keep working unchanged in the live window.

API 3 adds per-sample timestamps for live data: ``on_eeg_samples(x, ts_raw)``,
``on_optics_samples`` and ``on_imu_samples`` receive the same timestamp vector the CSV gets.
They are live-only (never called in review windows) and sit next to the API 1 hooks, which are
unchanged.
See docs/EXTENSIONS.md for details.
"""
from pathlib import Path

from PySide6 import QtGui, QtWidgets

from ..ui.tabs.base import BaseTab

API_VERSION = 3

__all__ = ["API_VERSION", "CATEGORIES", "Extension", "ExtensionContext", "BaseTab"]

# Where an extension's panels (tabs) appear in the menu bar: category → menu. Panels start hidden and are
# shown by ticking them in that menu. An unknown category is treated as "Other".
CATEGORIES = {
    "EEG": "Analysis",
    "Heart & optics": "Analysis",
    "Data quality": "Analysis",
    "Other": "Analysis",
    "Eyes": "HCI/BCI",
    "Motion": "HCI/BCI",
}
MENUS = ("Analysis", "HCI/BCI")


def category_of(value):
    return value if value in CATEGORIES else "Other"


def menu_location(category):
    """'Analysis ▸ EEG', 'HCI/BCI ▸ Eyes'… for a category (unknown → Other)."""
    c = category_of(category)
    return f"{CATEGORIES[c]} ▸ {c}"


class Extension:
    """Base class. Override the hooks you need; hooks that are not overridden are never called."""
    id = None               # default = file/folder name of the extension
    name = None             # display name (default = id)
    version = "0.1.0"
    description = ""
    author = ""
    requires_api = 1        # minimum API_VERSION the extension needs
    supports_review = False # API 2: also run in review windows (recorded sessions); see on_view_changed
    category = "Other"      # API 2: menu placement of its panels — a key of CATEGORIES (EEG, Eyes, Motion…)

    @classmethod
    def supports(cls, spec):
        """Whether the extension works with the connected device (spec: DeviceSpec — channel names,
        rates, whether there is an IMU). Return False → shown as "not applicable" instead of running and failing.
        Default True (compatible with older extensions)."""
        return True

    app = None              # ExtensionContext, assigned before activate()

    # ---- lifecycle -------------------------------------------------------------
    def activate(self, app):
        """Called once at app start-up: add tabs and actions, initialise state."""

    def deactivate(self):
        """Called when the app closes or the extension is disabled after an error: close files, stop threads."""

    # ---- realtime data (newest chunk; history is in app.store) ---------
    def on_eeg(self, x, ts):
        """x: (n EEG channels, k samples) unfiltered µV; ts: unix timestamp of the last sample."""

    def on_optics(self, x, ts):
        """x: (16, k) raw optical intensity."""

    def on_imu(self, x, ts):
        """x: (6, k) = acc_x,y,z (g) + gyro_x,y,z (°/s)."""

    # ---- realtime data with per-sample timestamps (API 3, live window only) -------
    def on_eeg_samples(self, x, ts_raw):
        """Same chunk as on_eeg, called right after it. ts_raw: float64 (k,), the unix timestamp of every
        sample exactly as written to the CSV (for Athena: BrainFlow's host-receive time — samples of one
        BLE packet can share a value, and IMU values can step back). Not called in review windows."""

    def on_optics_samples(self, x, ts_raw):
        """Same as on_eeg_samples for the optics chunk."""

    def on_imu_samples(self, x, ts_raw):
        """Same as on_eeg_samples for the IMU chunk."""

    # ---- app events --------------------------------------------------------
    def on_event(self, t, label):
        """A new event (Space key or app.mark_event)."""

    def on_recording_started(self, path):
        """Recording started; path = EEG .csv file. Use companion_path(path, "xxx") for companion files."""

    def on_recording_stopped(self):
        pass

    def on_connected(self, device_name):
        """The stream is delivering data."""

    def on_disconnected(self):
        pass

    def on_theme_changed(self, theme):
        """theme: colour dict (see ui/theme.py) — for custom-drawn widgets."""

    # ---- review windows (API 2, only with supports_review = True) -------------------
    def on_view_changed(self, t_end):
        """Review window: the view now ends at unix time ``t_end`` (scrollbar, event jump, Time range).
        Called after the whole recording has been replayed through on_eeg/on_optics/on_imu/on_event."""


class ExtensionContext:
    """The bridge between an extension and the app (passed to ``activate``)."""

    def __init__(self, ext_id, host, manager, name=None, category="Other"):
        self.id = ext_id
        self.name = name or ext_id
        self.category = category_of(category)
        self._host = host          # MainWindow — private, may change between versions
        self._manager = manager
        self._actions = []         # removed when the extension is unloaded
        self._menu = None          # Extensions ▸ <name> submenu holding this extension's actions
        self._overlay = {} if self.is_review else None   # review: settings changes stay in memory

    # ---- reading state ---------------------------------------------------------
    @property
    def spec(self):
        """DeviceSpec: .eeg/.optics/.imu with fs, n, names."""
        return self._host.spec

    @property
    def store(self):
        """SignalStore: Ring buffers .eeg/.eeg_f/.opt/.imu (use .get(n)), .last_ts, .eeg_display(n).
        In a review window: the recorded session, read the same way; during the replay its newest
        sample is the one just delivered to the data hooks."""
        return getattr(self._host, "extension_store", None) or self._host.ctx.store

    @property
    def is_review(self):
        """True in a review window (a recorded session opened with File ▸ Open session)."""
        return bool(getattr(self._host, "is_review", False))

    @property
    def view_end(self):
        """Review window: unix time of the right edge of the view; None in the live window."""
        return self._host.view_end_unix() if self.is_review else None

    @property
    def view(self):
        """ViewContext for building a BaseTab by hand (usually not needed — use add_tab)."""
        return self._host.ctx

    @property
    def theme(self):
        return self._host.ctx.th

    @property
    def window_sec(self):
        return self._host.ctx.window_sec

    @property
    def is_streaming(self):
        return self._host.streaming

    @property
    def is_recording(self):
        return self._host.recording

    @property
    def recording_path(self):
        """Path of the EEG file being recorded, or None."""
        return self._host.rec_path if self._host.recording else None

    @property
    def main_window(self):
        """Last resort: direct access to MainWindow (NOT stable across versions)."""
        return self._host

    # ---- adding to the UI ---------------------------------------------------
    def add_tab(self, tab, title=None, shown=None):
        """Add a panel (tab) to the Recording screen. ``tab`` is a BaseTab subclass (the app instantiates it)
        or an instance. It is listed under ``category`` in the Analysis or HCI/BCI menu and shows only while
        ticked there; the user's choice is remembered. ``shown``: initial state the first time only
        (default hidden)."""
        if isinstance(tab, type): tab = tab(self._host.ctx)
        if title: tab.title = title
        self._host.rec_page.add_tab(tab, owner=self.id)
        panels = getattr(self._host, "panels", None)
        if panels is not None: panels.add(self.id, self.name, tab, self.category, shown)
        return tab

    def add_action(self, text, callback, shortcut=None):
        """Add an item to Extensions ▸ <extension name>; an error in the callback only disables this extension."""
        act = QtGui.QAction(text, self._host)
        if shortcut: act.setShortcut(QtGui.QKeySequence(shortcut))
        act.triggered.connect(lambda *_: self._manager.guard(self.id, "action", callback))
        if self._menu is None:
            self._menu = QtWidgets.QMenu(self.name, self._host)
            self._host.ext_menu.insertMenu(self._host.ext_menu_sep, self._menu)
        self._menu.addAction(act)
        self._actions.append(act)
        return act

    def _dispose(self):
        """Remove everything the extension added to the UI (called by the app on unload)."""
        for act in self._actions: act.deleteLater()
        self._actions = []
        if self._menu is not None:
            self._host.ext_menu.removeAction(self._menu.menuAction()); self._menu.deleteLater(); self._menu = None
        self._host.remove_extension_tabs(self.id)

    # ---- actions ------------------------------------------------------------
    def mark_event(self, label, t=None):
        """Create an event as if Space were pressed (draws a marker, writes _events.csv while recording).
        Review window: a temporary marker only — nothing is written."""
        self._host.add_event(label, t)

    def show_status(self, message, ms=5000):
        self._host.statusBar().showMessage(f"[{self.id}] {message}", ms)

    # ---- private storage ----------------------------------------------------------
    def setting(self, key, default=None, type=None):
        """Read an extension-specific setting (persisted via QSettings)."""
        k = f"extensions/{self.id}/{key}"
        if self._overlay is not None and k in self._overlay: return self._overlay[k]
        st = self._host.ctx.settings
        return st.value(k, default, type=type) if type else st.value(k, default)

    def set_setting(self, key, value):
        """Persist a setting. Review window: kept in memory for that window only (QSettings untouched)."""
        k = f"extensions/{self.id}/{key}"
        if self._overlay is not None: self._overlay[k] = value
        else: self._host.ctx.settings.setValue(k, value)

    @property
    def data_dir(self):
        """Private folder for the extension's files (created on demand): ~/.musemonitor/data/<id>."""
        d = Path.home() / ".musemonitor" / "data" / self.id
        d.mkdir(parents=True, exist_ok=True)
        return d
