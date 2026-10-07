"""Golden test on RAW Athena data (fixture from tools/capture_athena.py).

Replays the recorded BrainFlow chunks in their original order, then locks:
- CSV: SHA-256 of the ORIGINAL COLUMNS (timestamp + channels) of each file — new columns (package_num…) are dropped
  before hashing, so adding metadata does not break the golden file but changing existing data does.
- Analysis results: channel quality, PSD levels, HRV metrics, ΔHbO, EEG trace totals.

Create the expected file from a code version KNOWN TO BE CORRECT (e.g. a baseline commit), not from the code being changed:

    git worktree add /tmp/mm-base <commit>
    PYTHONPATH=/tmp/mm-base/src python tests/golden.py bless tests/fixtures/athena_raw_X.npz

The harness only uses APIs that exist at baseline commit 7e7720a (it detects new/old function signatures).
"""
import csv
import hashlib
import inspect
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

STREAMS = (("eeg", "eeg"), ("optics", "optics"), ("imu", "imu"))   # (fixture key, Recorder key)
WINDOW_SEC = 20


def load_fixture(path):
    z = np.load(path, allow_pickle=False)
    fx = {"meta": json.loads(str(z["meta"]))}
    for key, _ in STREAMS:
        if f"{key}_data" in z:
            fx[key] = (z[f"{key}_data"], z[f"{key}_chunk_lens"], z[f"{key}_poll_wall"])
    return fx


def chunks_in_order(fx):
    """[(poll_wall, key, array with all rows)] in read order — as the worker received them."""
    out = []
    for key, _ in STREAMS:
        if key not in fx: continue
        data, lens, wall = fx[key]
        for w, a, b in zip(wall, np.cumsum(lens) - lens, np.cumsum(lens)):
            out.append((float(w), key, data[:, a:b]))
    out.sort(key=lambda c: c[0])
    return out


def extract(spec, key, d):
    s = getattr(spec, key)
    seq_row = getattr(s, "seq_row", None)
    return d[s.rows], d[s.ts_row], (d[seq_row] if seq_row is not None else None)


def _accepts(fn, n):
    return len(inspect.signature(fn).parameters) >= n


def csv_digests(fx, spec):
    from musemonitor.storage.recording import Recorder, companion_path
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rec.csv"
        rec = Recorder(path, spec)
        new_api = _accepts(rec.write, 4)
        for _, key, d in chunks_in_order(fx):
            x, ts, seq = extract(spec, key, d)
            rec.write(key, ts, x, seq) if new_api else rec.write(key, ts, x)
        rec.close()
        out = {}
        for key, _ in STREAMS:
            p = path if key == "eeg" else companion_path(path, key)
            with open(p, newline="") as f:
                rows = list(csv.reader(f))
            n_legacy = 1 + len(getattr(spec, key).names)            # timestamp + channels
            text = "\n".join(",".join(r[:n_legacy]) for r in rows)
            out[key] = {"rows": len(rows) - 1, "sha256": hashlib.sha256(text.encode()).hexdigest()}
        return out


def analysis(fx, spec):
    from PySide6 import QtCore, QtWidgets
    from musemonitor.ui import main_window as mw
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        st = QtCore.QSettings(str(Path(tmp) / "s.ini"), QtCore.QSettings.IniFormat)
        mw.MainWindow.start_scan = lambda self: None
        w = mw.MainWindow(spec, settings=st, extension_dirs=[]); w.resize(1300, 900); w.show()
        w.connected = True
        handlers = {"eeg": w.on_data, "optics": w.on_optics, "imu": w.on_imu}
        new_api = _accepts(w.on_data, 3)
        for _, key, d in chunks_in_order(fx):
            x, ts, seq = extract(spec, key, d)
            handlers[key](x, ts, seq) if new_api else handlers[key](x, float(ts[-1]))
        w.stack.setCurrentIndex(2); w.rec_page.range_spin.setValue(WINDOW_SEC)
        rp = w.rec_page; psd, ppg = rp.tab_list[1], rp.tab_list[2]
        out = {}
        w.update_quality(); out["quality"] = [[q, round(float(b), 3), round(float(l), 3)] for q, b, l in w.last_qs]
        rp.tabs.setCurrentIndex(1); w.update_analysis()
        out["psd_levels"] = [round(float(v), 4) for v in psd.levels]
        rp.tabs.setCurrentIndex(2); ppg.tiles_t = 0; w.update_analysis()
        out["tiles"] = {k: v.text() for k, v in ppg.tiles.items()}
        out["hbo_sum"] = round(float(np.sum(ppg.hbo_curve.yData)), 4)
        rp.tabs.setCurrentIndex(0); w.redraw()
        out["eeg_curve0_sum"] = round(float(np.sum(rp.signals_tab.curves[0].yData)), 4)
        w.connected = False; w.close()
        app.processEvents()
    return out


def compute(path):
    from musemonitor.device.spec import athena_spec
    spec = athena_spec()
    fx = load_fixture(path)
    return {"csv": csv_digests(fx, spec), "analysis": analysis(fx, spec)}


def expected_path(fixture):
    return Path(fixture).with_suffix(".expected.json")


if __name__ == "__main__":
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import musemonitor  # noqa: F401 — loads numpy/scipy/brainflow before PySide6
    if len(sys.argv) != 3 or sys.argv[1] != "bless":
        sys.exit("usage: python tests/golden.py bless <fixture.npz>")
    res = compute(sys.argv[2])
    res["blessed_with"] = musemonitor.__file__
    expected_path(sys.argv[2]).write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print(json.dumps(res, indent=2, ensure_ascii=False))
