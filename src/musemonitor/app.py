import sys
from pathlib import Path

import pyqtgraph as pg
from brainflow.board_shim import BoardShim
from PySide6 import QtCore, QtGui, QtWidgets

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
    """Start the app. Options (for checking an installation, e.g. a packaged build):
        --self-check [--report FILE]   exercise every feature without a headset, print OK / FAIL / SKIP (and write them
                            to FILE), exit 0 if all passed
        --quit-after SEC    open the app normally, then quit after SEC seconds (a smoke test of a real start)"""
    argv = list(sys.argv if argv is None else argv)
    if "--self-check" in argv:                     # --report FILE: also write the lines to FILE (a windowed app
        from .selfcheck import run                  # on Windows has no console to print to)
        report = argv[argv.index("--report") + 1] if "--report" in argv else None
        lines = []
        def out(line):
            lines.append(line)
            if sys.stdout is not None: print(line, flush=True)
        code = run(out=out)
        if report: Path(report).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return code
    quit_after = None
    if "--quit-after" in argv:
        i = argv.index("--quit-after")
        quit_after = float(argv[i + 1]); del argv[i:i + 2]
    BoardShim.enable_dev_board_logger()
    app = QtWidgets.QApplication(argv)
    apply_app_style(app)                   # Fusion (honours the light/dark palette) + checkbox fix
    icon = Path(__file__).resolve().parent / "ui" / "app_icon.png"      # packaging/icon/icon.svg → make_icons.py
    if icon.exists(): app.setWindowIcon(QtGui.QIcon(str(icon)))
    pg.setConfigOptions(antialias=False)
    manager = WindowManager(discover_profiles())
    manager.open()
    if quit_after is not None: QtCore.QTimer.singleShot(int(quit_after * 1000), app.quit)
    return app.exec()
