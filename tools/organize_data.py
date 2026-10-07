"""Move OLD recordings (flat files in data/) into session folders + create a whole-session PSD report.

    data/muse_eeg_20261006_221502.csv, …_optics.csv, …_imu.csv, …_events.csv, …_bandpower.csv
        → data/muse_20261006_221502/ (file names kept) + report.html + psd_*.csv

By default only PRINTS the plan (changes nothing). Add --apply to move files and create reports.
Never deletes a file; empty files (0 bytes, e.g. not yet downloaded from iCloud) are reported and skipped for the report.

    PYTHONPATH=src ~/.venvs/musemonitor/bin/python tools/organize_data.py            # preview
    PYTHONPATH=src ~/.venvs/musemonitor/bin/python tools/organize_data.py --apply    # apply
"""
import argparse
import csv
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from musemonitor.core.timing import StreamClock  # noqa: E402
from musemonitor.device.spec import athena_spec  # noqa: E402
from musemonitor.storage.session import RecordingSession, data_root  # noqa: E402

PATTERN = re.compile(r"^muse_eeg_(\d{8}_\d{6})(?:_(.+))?\.csv$")
STREAM_FILES = {"eeg": None, "opt": "optics", "imu": "imu"}       # session key → file suffix


def find_sessions(root):
    groups = {}
    for p in sorted(root.glob("muse_eeg_*.csv")):
        m = PATTERN.match(p.name)
        if m: groups.setdefault(m.group(1), []).append(p)
    return groups


def _load_csv(path):
    with open(path, newline="") as f:
        head = next(csv.reader(f))
    data = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    return head, data


def build_report(stamp, folder, spec):
    """Create report.html in ``folder`` from existing CSVs (same code as a live recording session)."""
    sess = RecordingSession(spec, stamp=stamp, folder=folder)     # build a session from existing files
    health, t_first, t_last = {}, None, None
    for key, suffix in STREAM_FILES.items():
        p = folder / (f"muse_eeg_{stamp}.csv" if suffix is None else f"muse_eeg_{stamp}_{suffix}.csv")
        if not p.exists() or p.stat().st_size == 0: continue
        head, d = _load_csv(p)
        if not len(d): continue
        n_ch = getattr(spec, "eeg" if key == "eeg" else ("optics" if key == "opt" else "imu")).n
        sess.add(key, d[:, 1:1 + n_ch].T)
        clk = StreamClock(sess.acc[key].fs, len(d), 30)
        seq = d[:, head.index("package_num")] if "package_num" in head else None
        clk.add(d[:, 0], seq)
        health[key] = clk.health()
        t_first = d[0, 0] if t_first is None else min(t_first, d[0, 0])
        t_last = d[-1, 0] if t_last is None else max(t_last, d[-1, 0])
    ev = folder / f"muse_eeg_{stamp}_events.csv"
    if ev.exists() and ev.stat().st_size:
        with open(ev, newline="") as f:
            for row in list(csv.reader(f))[1:]:
                if len(row) >= 2: sess.add_event(float(row[0]), row[1])
    if t_first is None: return None
    sess.started = t_first                                      # session time from the data timestamps
    return sess.finish(health, ended=t_last)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None, help=f"data folder (default {data_root()})")
    ap.add_argument("--apply", action="store_true", help="apply (default: preview only)")
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else data_root()
    spec = athena_spec()
    groups = find_sessions(root)
    if not groups:
        print(f"No flat recordings in {root}"); return 0
    for stamp, files in groups.items():
        folder = root / f"muse_{stamp}"
        empty = [p.name for p in files if p.stat().st_size == 0]
        print(f"{'MOVE' if a.apply else 'would move'} {len(files)} file → {folder.name}/"
              + (f"   (empty files: {', '.join(empty)})" if empty else ""))
        for p in files: print(f"    {p.name}")
        if not a.apply: continue
        if folder.exists() and any(folder.iterdir()):
            print(f"    skipped: {folder.name}/ already exists and is not empty"); continue
        folder.mkdir(exist_ok=True)
        for p in files: p.rename(folder / p.name)
        try:
            rep = build_report(stamp, folder, spec)
            print(f"    report: {rep.name if rep else 'not enough data'}")
        except Exception as e:
            print(f"    report failed ({type(e).__name__}: {e}) — files were moved, no data lost")
    if not a.apply: print("\nNothing changed. Run again with --apply to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
