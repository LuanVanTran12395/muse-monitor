import sys

import pyqtgraph as pg
from brainflow.board_shim import BoardShim
from PySide6 import QtCore, QtWidgets

from . import config as C
from .device.profiles import discover_profiles
from .ui.main_window import MainWindow
from .ui.style import apply_app_style


class WindowManager(QtCore.QObject):
    """Opens the main window for a device profile. Choosing a device of another kind
    opens a fresh window built for that profile — the old one closes after the new one is shown —
    and connects to the chosen device. The last used profile is reopened on the next start."""

    def __init__(self, profiles, settings=None, window_kwargs=None):
        super().__init__()
        self.profiles = {p.id: p for p in profiles}
        self.order = list(profiles)
        self.settings = settings or QtCore.QSettings(C.ORG_NAME, "MuseMonitor")
        self.kwargs = dict(window_kwargs or {})
        self.window = None

    def open(self, profile_id=None, connect_to=None):
        if profile_id is None: profile_id = self.settings.value("device_profile", self.order[0].id)
        prof = self.profiles.get(profile_id, self.order[0])           # library removed → Athena
        old = self.window
        if old is not None and old.connected: return old               # never drop a live stream
        w = MainWindow(prof.make_spec(), settings=self.settings, profile=prof, profiles=self.order, **self.kwargs)
        w.switch_requested.connect(lambda pid, dev: self.open(pid, dev))
        if old is not None: w.setGeometry(old.geometry())
        self.window = w
        w.show()                                   # show the new window BEFORE closing the old one,
        if old is not None:                        # otherwise Qt quits on "last window closed"
            old.close(); old.deleteLater()
        if connect_to: QtCore.QTimer.singleShot(0, lambda: w.connect_to(connect_to))
        return w


def main(argv=None):
    BoardShim.enable_dev_board_logger()
    app = QtWidgets.QApplication(sys.argv if argv is None else argv)
    apply_app_style(app)                   # Fusion (honours the light/dark palette) + checkbox fix
    pg.setConfigOptions(antialias=False)
    manager = WindowManager(discover_profiles())
    manager.open()
    return app.exec()
