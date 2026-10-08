"""Recording session: every Start recording creates its own folder in data/.

    data/muse_20261007_101500/
        muse_eeg_20261007_101500.csv            (+ _optics, _imu, _events, extension files…)
        session.json                            device profile, sampling rates, channels, units (schema 1)
        report.html                             whole-session PSD, band power, events
        psd_eeg.csv  psd_optics.csv  psd_imu.csv

CSV names and columns are unchanged (Recorder is untouched); only the location differs.
``session.json`` is an extra file so a recording can be opened again without guessing the device
(see storage/reader.py); it is written when recording starts and updated when it stops.
The PSD is accumulated while recording (core.spectral.PsdAccumulator), so the CSV is never re-read.
"""
import json
import os
import time
from pathlib import Path

from .. import config as C
from ..core.spectral import PsdAccumulator

PROJECT_DATA = Path(__file__).resolve().parents[3] / "data"     # <repo>/data when running from src/
META_FILE = "session.json"
META_SCHEMA = 1
UNITS = {"eeg": "uV", "optics": "raw"}                          # imu: per channel, see _units()


def _units(key, names):
    if key == "imu": return ["g" if n.startswith("acc") else "deg/s" if n.startswith("gyro") else "" for n in names]
    return [UNITS.get(key, "")] * len(names)


def data_root():
    """Data folder: $MUSEMONITOR_DATA_DIR → <repo>/data → ~/MuseMonitor/data."""
    env = os.environ.get(C.DATA_DIR_ENV)
    if env: return Path(env).expanduser()
    if PROJECT_DATA.parent.joinpath("src", "musemonitor").is_dir(): return PROJECT_DATA
    return Path.home() / "MuseMonitor" / "data"


class RecordingSession:
    STREAMS = {"eeg": "eeg", "opt": "optics", "imu": "imu"}       # store key → spec key

    def __init__(self, spec, root=None, device="", stamp=None, folder=None, profile_id=None):
        """folder: use an EXISTING folder (report for an old recording) instead of creating one;
        session.json is only written for new folders. profile_id: device profile (None = Muse S Athena)."""
        stamp = stamp or time.strftime("%Y%m%d_%H%M%S")
        new_folder = folder is None
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
        self.profile_id = profile_id or "muse_athena"
        self.started = time.time(); self.ended = None
        self.events = []
        self.acc = {}
        for key, attr in self.STREAMS.items():
            s = getattr(spec, attr)
            if s.n: self.acc[key] = PsdAccumulator(s.fs, s.n, C.REPORT_PSD_SEG_SEC[key])
        if new_folder: self.write_meta()

    def meta(self):
        from .. import __version__
        from .recording import companion_path
        streams = {}
        for key in ("eeg", "optics", "imu"):
            s = getattr(self.spec, key)
            if not s.n: continue
            f = self.eeg_path if key == "eeg" else companion_path(self.eeg_path, key)
            streams[key] = dict(file=f.name, fs=s.fs, channels=list(s.names), units=_units(key, s.names))
        return dict(schema=META_SCHEMA, app_version=__version__, profile_id=self.profile_id, device_name=self.device,
                    started_unix=self.started, stopped_unix=self.ended, streams=streams)

    def write_meta(self):
        """session.json next to the CSVs (an extra file; the CSVs themselves are unchanged)."""
        tmp = self.folder / (META_FILE + ".tmp")
        tmp.write_text(json.dumps(self.meta(), indent=2)); tmp.replace(self.folder / META_FILE)

    def add(self, stream, x):
        if stream in self.acc: self.acc[stream].add(x)

    def add_event(self, t, label):
        self.events.append((t, label))

    def finish(self, health=None, ended=None):
        """Close the session: write report.html + psd_*.csv. Returns the report path."""
        from .report import write_report
        self.ended = time.time() if ended is None else ended
        if (self.folder / META_FILE).exists():
            try: self.write_meta()
            except OSError: pass                             # the report matters more than the stop time
        return write_report(self, health or {})
