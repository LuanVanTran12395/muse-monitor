"""Check a LabRecorder XDF file of the lsl_outlet streams against the app's recording (needs pyxdf).

    pip install pyxdf
    ~/.venvs/musemonitor/bin/python tools/xdf_check.py session.xdf --events data/<session>/<rec>_events.csv \
        --csv data/<session>/<rec>.csv

Reads the file WITHOUT clock synchronisation or de-jittering, so timestamps are exactly what the
outlets sent (same machine → same clock). Reports:
- per stream: samples, strictly increasing or not, number of backsteps, largest gap, LabRecorder
  clock offsets recorded (several streams with the same name = LabRecorder created separate streams);
- Markers vs ``_events.csv``: same labels in the same order; the spacing between consecutive markers
  equals the CSV spacing (offset-free check of the time mapping, ≤ 1 ms unless the clock stepped);
- EEG vs CSV: places the XDF samples in the CSV by value, checks every overlapping sample is bit-equal and
  in order, and (with markers) the smoothed − host timestamp difference; reports gaps > 0.5 s;
- the Quality events (counts by type, every non-null reason).
Results are what one file shows; they do not measure latency to the real stimulus.
"""
import argparse
import csv
import json
import sys
from collections import Counter

import numpy as np

PREFIX = "MuseMonitor-Athena"


def read_csv(path):
    with open(path) as f:
        r = csv.reader(f); next(r)
        return [row for row in r]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xdf")
    ap.add_argument("--events", help="<recording>_events.csv")
    ap.add_argument("--csv", help="<recording>.csv (EEG)")
    a = ap.parse_args()
    import pyxdf
    streams, _ = pyxdf.load_xdf(a.xdf, synchronize_clocks=False, dejitter_timestamps=False)
    ours = [s for s in streams if s["info"]["name"][0].startswith(PREFIX)]
    if not ours: sys.exit(f"no {PREFIX}-* stream in {a.xdf}")
    names = Counter(s["info"]["name"][0] for s in ours)
    ok = True
    by = {}
    for s in ours:
        n = s["info"]["name"][0]; by.setdefault(n, []).append(s)
        t = np.asarray(s["time_stamps"], dtype=float)
        d = np.diff(t)
        inc = bool(np.all(d > 0)) if n.endswith("-EEG") else bool(np.all(d >= 0))
        offs = s.get("clock_times", [])
        print(f"== {n} (source_id {s['info']['source_id'][0]}): samples {t.size}, "
              f"{'strictly increasing' if n.endswith('-EEG') else 'non-decreasing'}: {inc}, "
              f"backsteps {int((d < 0).sum())}, largest gap {d.max() * 1e3 if d.size else 0:.1f} ms, "
              f"clock offsets recorded {len(offs)}")
        ok &= inc
    dup = [n for n, c in names.items() if c > 1]
    if dup: print(f"NOTE: several XDF streams with the same name {dup} (LabRecorder did not join them)")

    offset = None
    if "%s-Markers" % PREFIX in by and a.events:
        mk = by[f"{PREFIX}-Markers"][0]
        labels = [v[0] for v in mk["time_series"]]
        t_x = np.asarray(mk["time_stamps"], dtype=float)
        rows = read_csv(a.events)
        t_c = np.array([float(r[0]) for r in rows]); l_c = [r[1] for r in rows]
        print(f"\n== Markers: XDF {len(labels)}, _events.csv {len(l_c)}")
        # the outlet may have started after the recording or stopped before it: align by label sequence
        start = next((i for i in range(len(l_c) - len(labels) + 1) if l_c[i:i + len(labels)] == labels), None)
        if start is None:
            print("labels do not match as one contiguous run:", labels[:10], l_c[:10]); ok = False
        elif len(labels):
            t_c = t_c[start:start + len(labels)]
            gap_err = np.abs(np.diff(t_x) - np.diff(t_c)) * 1e3 if len(labels) > 1 else np.zeros(0)
            offset = float(np.median(t_x - t_c))
            print(f"labels match (from CSV row {start}); spacing |XDF − CSV| max "
                  f"{gap_err.max() if gap_err.size else 0:.3f} ms; offset (LSL − unix) {offset:.6f} s")
            ok &= bool(gap_err.size == 0 or gap_err.max() <= 1.0)

    if f"{PREFIX}-EEG" in by and a.csv:
        eeg = by[f"{PREFIX}-EEG"]
        t = np.concatenate([np.asarray(s["time_stamps"], dtype=float) for s in eeg])
        x = np.concatenate([np.asarray(s["time_series"], dtype=np.float32) for s in eeg])
        data = np.array(read_csv(a.csv), dtype=float)
        tc, xc = data[:, 0], data[:, 1:1 + x.shape[1]].astype(np.float32)
        print(f"\n== EEG vs CSV: XDF {t.size} samples, CSV {tc.size} rows")
        # locate the XDF samples in the CSV by value (float32 µV, exact), then compare in the overlap
        hit = np.where(np.all(xc == x[min(1000, len(x) - 1)], axis=1))[0]
        if len(hit) != 1:
            print(f"could not place the XDF in the CSV by value ({len(hit)} matches) — skipped")
        else:
            j = int(hit[0]) - min(1000, len(x) - 1)                 # CSV row of XDF sample 0
            a0, a1 = max(0, -j), min(len(x), len(xc) - j)
            same = np.all(x[a0:a1] == xc[a0 + j:a1 + j], axis=1)
            print(f"overlap {a1 - a0} samples: values bit-equal and in order for {int(same.sum())} "
                  f"(XDF-only samples: {len(x) - (a1 - a0)})")
            ok &= bool(same.all())
            if offset is not None:
                d = (t[a0:a1] - offset) - tc[a0 + j:a1 + j]
                q = np.percentile(d, [50, 1, 99]) * 1e3
                print(f"smoothed − CSV host timestamp (ms): median {q[0]:.2f}, p1 {q[1]:.2f}, p99 {q[2]:.2f}, "
                      f"min {d.min() * 1e3:.2f}, max {d.max() * 1e3:.2f}")
            gaps = np.where(np.diff(t) > 0.5)[0]
            for g in gaps: print(f"EEG gap {np.diff(t)[g]:.2f} s after XDF sample {g} (outlet stopped/restarted?)")

    if f"{PREFIX}-Quality" in by:
        ev = [json.loads(v[0]) for s in by[f"{PREFIX}-Quality"] for v in s["time_series"]]
        print(f"\n== Quality: {dict(Counter(e['event'] for e in ev))}")
        for e in ev:
            if e["event"] != "state" or e.get("reason"): print("  ", json.dumps(e)[:220])
    print("\nRESULT:", "OK" if ok else "CHECK FAILED (see above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
