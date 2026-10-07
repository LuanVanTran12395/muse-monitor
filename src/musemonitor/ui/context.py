from dataclasses import dataclass

from .plotkit import PlotRegistry
from .theme import THEMES, DEFAULT_THEME


@dataclass
class ViewContext:
    """What every page/tab shares — passed in instead of letting them reference MainWindow."""
    spec: object              # device.spec.DeviceSpec
    store: object             # core.store.SignalStore
    settings: object          # QtCore.QSettings
    plots: PlotRegistry
    th: dict = None           # current theme
    profile: object = None    # device.profiles.DeviceProfile (None = default Muse S Athena)

    def __post_init__(self):
        if self.th is None: self.th = THEMES[DEFAULT_THEME]

    @property
    def window_sec(self):
        return self.plots.window_sec
