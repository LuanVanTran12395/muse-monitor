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
See docs/EXTENSIONS.md for details.
"""
from pathlib import Path

from PySide6 import QtGui

from ..ui.tabs.base import BaseTab

API_VERSION = 1

__all__ = ["API_VERSION", "Extension", "ExtensionContext", "BaseTab"]


class Extension:
    """Base class. Override the hooks you need; hooks that are not overridden are never called."""
    id = None               # default = file/folder name of the extension
    name = None             # display name (default = id)
    version = "0.1.0"
    description = ""
    author = ""
    requires_api = 1        # minimum API_VERSION the extension needs

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


class ExtensionContext:
    """The bridge between an extension and the app (passed to ``activate``)."""

    def __init__(self, ext_id, host, manager):
        self.id = ext_id
        self._host = host          # MainWindow — private, may change between versions
        self._manager = manager
        self._actions = []         # removed when the extension is unloaded

    # ---- reading state ---------------------------------------------------------
    @property
    def spec(self):
        """DeviceSpec: .eeg/.optics/.imu with fs, n, names."""
        return self._host.spec

    @property
    def store(self):
        """SignalStore: Ring buffers .eeg/.eeg_f/.opt/.imu (use .get(n)), .last_ts, .eeg_display(n)."""
        return self._host.ctx.store

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
    def add_tab(self, tab, title=None):
        """Add a tab to the Recording screen. ``tab`` is a BaseTab subclass (the app instantiates it) or an instance."""
        if isinstance(tab, type): tab = tab(self._host.ctx)
        if title: tab.title = title
        self._host.rec_page.add_tab(tab, owner=self.id)
        return tab

    def add_action(self, text, callback, shortcut=None):
        """Add an item to the Extensions menu; an error in the callback only disables this extension."""
        act = QtGui.QAction(text, self._host)
        if shortcut: act.setShortcut(QtGui.QKeySequence(shortcut))
        act.triggered.connect(lambda *_: self._manager.guard(self.id, "action", callback))
        self._host.ext_menu.insertAction(self._host.ext_menu_sep, act)
        self._actions.append(act)
        return act

    def _dispose(self):
        """Remove everything the extension added to the UI (called by the app on unload)."""
        for act in self._actions:
            self._host.ext_menu.removeAction(act); act.deleteLater()
        self._actions = []
        self._host.remove_extension_tabs(self.id)

    # ---- actions ------------------------------------------------------------
    def mark_event(self, label, t=None):
        """Create an event as if Space were pressed (draws a marker, writes _events.csv while recording)."""
        self._host.add_event(label, t)

    def show_status(self, message, ms=5000):
        self._host.statusBar().showMessage(f"[{self.id}] {message}", ms)

    # ---- private storage ----------------------------------------------------------
    def setting(self, key, default=None, type=None):
        """Read an extension-specific setting (persisted via QSettings)."""
        k = f"extensions/{self.id}/{key}"
        st = self._host.ctx.settings
        return st.value(k, default, type=type) if type else st.value(k, default)

    def set_setting(self, key, value):
        self._host.ctx.settings.setValue(f"extensions/{self.id}/{key}", value)

    @property
    def data_dir(self):
        """Private folder for the extension's files (created on demand): ~/.musemonitor/data/<id>."""
        d = Path.home() / ".musemonitor" / "data" / self.id
        d.mkdir(parents=True, exist_ok=True)
        return d
