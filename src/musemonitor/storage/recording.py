import csv
import time
from pathlib import Path

import numpy as np


def companion_path(path, suffix):
    """muse_eeg_X.csv → muse_eeg_X_<suffix>.csv"""
    p = Path(path)
    return p.with_name(f"{p.stem}_{suffix}.csv")


class Recorder:
    """Writes CSV in the worker thread (does not block the GUI), in blocks.

    Main file = EEG; plus ``_optics.csv`` and ``_imu.csv`` in the same folder.
    Columns: timestamp (raw from the device/BrainFlow, unmodified), the channels, then ``package_num``
    (if the stream has one) LAST, so code reading by column name or old column position is unaffected."""
    def __init__(self, path, spec):
        streams = {"eeg": spec.eeg, "optics": spec.optics, "imu": spec.imu}
        self.has_seq = {k: s.seq_row is not None for k, s in streams.items()}
        heads = {k: list(s.names) + (["package_num"] if self.has_seq[k] else []) for k, s in streams.items()}
        paths = {"eeg": Path(path), "optics": companion_path(path, "optics"), "imu": companion_path(path, "imu")}
        self.files, self.writers = {}, {}
        try:
            for k in ("eeg", "optics", "imu"):
                if k != "eeg" and not streams[k].n: continue           # the device has no such stream
                self.files[k] = open(paths[k], "w", newline="")
                self.writers[k] = csv.writer(self.files[k])
                self.writers[k].writerow(["timestamp"] + list(heads[k]))
        except OSError:
            self.close(); raise
        self.last_flush = time.monotonic()

    def write(self, stream, ts, data, seq=None):
        if stream not in self.writers: return
        cols = [ts, data.T]
        if self.has_seq[stream]:
            cols.append(np.full(len(ts), np.nan) if seq is None else seq)
        self.writers[stream].writerows(np.column_stack(cols).tolist())
        if time.monotonic() - self.last_flush > 1.0:      # flush once per second instead of every packet
            for f in self.files.values(): f.flush()
            self.last_flush = time.monotonic()

    def close(self):
        for f in self.files.values(): f.close()
        self.files = {}
