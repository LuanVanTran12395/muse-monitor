"""Light/dark themes: every text/line colour comes from here so it stands out on the matching background."""
import pyqtgraph as pg
from PySide6 import QtGui, QtWidgets

THEMES = {
    "Dark": dict(
        window="#161b22", base="#0d1117", button="#21262d", fg="#e6edf3", muted="#8b949e",
        disabled="#6e7681", highlight="#1f6feb", link="#58a6ff", bg="#0d1117", border="#30363d",
        eeg=["#58a6ff", "#3fb950", "#f0883e", "#d2a8ff"], xyz=["#ff7b72", "#3fb950", "#58a6ff"],
        ppg="#f0883e", beat="#ffd33d", hr="#ff7b72", hbo="#ff7b72", hbr="#58a6ff", event="#e3b341", event_img="#39d0d8",
        opt_value=255, cmap="inferno",
        q={"Good": "#3fb950", "Fair": "#d29922", "Bad": "#f85149", "No signal": "#8b949e", "—": "#8b949e"}),
    "Light": dict(
        window="#f6f8fa", base="#ffffff", button="#ffffff", fg="#1f2328", muted="#59636e",
        disabled="#8c959f", highlight="#0969da", link="#0969da", bg="#ffffff", border="#d1d9e0",
        eeg=["#0550ae", "#1a7f37", "#bc4c00", "#8250df"], xyz=["#cf222e", "#1a7f37", "#0969da"],
        ppg="#bc4c00", beat="#8250df", hr="#cf222e", hbo="#cf222e", hbr="#0969da", event="#9a6700", event_img="#ff4d4f",
        opt_value=170, cmap="viridis",
        q={"Good": "#1a7f37", "Fair": "#9a6700", "Bad": "#cf222e", "No signal": "#6e7781", "—": "#6e7781"}),
}
DEFAULT_THEME = "Dark"


def qt_palette(th):
    p = QtGui.QPalette()
    C = QtGui.QColor
    for role, c in ((QtGui.QPalette.Window, th["window"]), (QtGui.QPalette.WindowText, th["fg"]),
                    (QtGui.QPalette.Base, th["base"]), (QtGui.QPalette.AlternateBase, th["window"]),
                    (QtGui.QPalette.Text, th["fg"]), (QtGui.QPalette.Button, th["button"]),
                    (QtGui.QPalette.ButtonText, th["fg"]), (QtGui.QPalette.ToolTipBase, th["window"]),
                    (QtGui.QPalette.ToolTipText, th["fg"]), (QtGui.QPalette.Highlight, th["highlight"]),
                    (QtGui.QPalette.HighlightedText, "#ffffff"), (QtGui.QPalette.Link, th["link"]),
                    (QtGui.QPalette.PlaceholderText, th["muted"]), (QtGui.QPalette.BrightText, "#ff7b72")):
        p.setColor(role, C(c))
    for role in (QtGui.QPalette.WindowText, QtGui.QPalette.Text, QtGui.QPalette.ButtonText):
        p.setColor(QtGui.QPalette.Disabled, role, C(th["disabled"]))
    return p


def apply_app_theme(th):
    """App-wide Qt palette + default colours for pyqtgraph plots created afterwards."""
    QtWidgets.QApplication.instance().setPalette(qt_palette(th))
    pg.setConfigOptions(background=th["bg"], foreground=th["fg"])
