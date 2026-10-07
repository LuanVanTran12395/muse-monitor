"""Recording session: every Start recording creates its own folder in data/.

    data/muse_20261007_101500/
        muse_eeg_20261007_101500.csv            (+ _optics, _imu, _events, extension files…)
        report.html                             whole-session PSD, band power, events
        psd_eeg.csv  psd_optics.csv  psd_imu.csv

CSV names and columns are unchanged (Recorder is untouched); only the location differs.
The PSD is accumulated while recording (core.spectral.PsdAccumulator), so the CSV is never re-read.
"""
import os
import time
from pathlib import Path

from .. import config as C
from ..core.spectral import PsdAccumulator

PROJECT_DATA = Path(__file__).resolve().parents[3] / "data"     # <repo>/data when running from src/


def data_root():
    """Data folder: $MUSEMONITOR_DATA_DIR → <repo>/data → ~/MuseMonitor/data."""
    env = os.environ.get(C.DATA_DIR_ENV)
    if env: return Path(env).expanduser()
    if PROJECT_DATA.parent.joinpath("src", "musemonitor").is_dir(): return PROJECT_DATA
    return Path.home() / "MuseMonitor" / "data"


class RecordingSession:
    STREAMS = {"eeg": "eeg", "opt": "optics", "imu": "imu"}       # store key → spec key

    def __init__(self, spec, root=None, device="", stamp=None, folder=None):
        """folder: use an EXISTING folder (report for an old recording) instead of creating one."""
        stamp = stamp or time.strftime("%Y%m%d_%H%M%S")
        if folder is None:
            root = Path(root) if root else data_root()
            folder = root / f"muse_{stamp}"
            k = 2
            while folder.exists():                                 # two sessions within the same second
                folder = root / f"muse_{stamp}_{k}"; k += 1
            folder.mkdir(parents=True)
        folder = Path(folder)
        self.folder, self.stamp, self.device = folder, stamp, device
        self.eeg_path = folder / f"muse_eeg_{stamp}.csv"
        self.spec = spec
        self.started = time.time(); self.ended = None
        self.events = []
        self.acc = {}
        for key, attr in self.STREAMS.items():
            s = getattr(spec, attr)
            if s.n: self.acc[key] = PsdAccumulator(s.fs, s.n, C.REPORT_PSD_SEG_SEC[key])

    def add(self, stream, x):
        if stream in self.acc: self.acc[stream].add(x)

    def add_event(self, t, label):
        self.events.append((t, label))

    def finish(self, health=None, ended=None):
        """Close the session: write report.html + psd_*.csv. Returns the report path."""
        from .report import write_report
        self.ended = time.time() if ended is None else ended
        return write_report(self, health or {})
