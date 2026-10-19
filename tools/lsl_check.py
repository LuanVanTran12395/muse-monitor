"""Check the lsl_outlet streams with a real LSL inlet (needs pylsl; no LabRecorder required).

Start Muse Monitor, connect the headset, Extensions ▸ LSL Outlet ▸ Start LSL streams, then:

    ~/.venvs/musemonitor/bin/python tools/lsl_check.py --seconds 60

Reports, per stream: samples received, rate, whether timestamps strictly increase, the largest gap,
metadata; the Markers received; the Quality events. Timestamps are read as sent (no inlet
post-processing). Optional ``--csv <recording>.csv`` compares the EEG sample count with the app's CSV
over the time both covered (approximate at the edges: the clock offset is measured by this tool).
"""
import argparse
import csv
import json
import sys
import time

import numpy as np

PREFIX = "MuseMonitor-Athena"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--timeout", type=float, default=10.0, help="how long to look for the streams")
    ap.add_argument("--csv", help="the app's EEG CSV of the same session, to compare sample counts")
    a = ap.parse_args()
    import pylsl

    found = {}
    t_end = time.time() + a.timeout
    while time.time() < t_end and len(found) < 3:
        for info in pylsl.resolve_streams(wait_time=1.0):
            if info.name().startswith(PREFIX): found[info.name()] = info
    if f"{PREFIX}-EEG" not in found:
        sys.exit(f"no {PREFIX}-EEG stream found (is 'Start LSL streams' on?); found: {sorted(found)}")
    inlets = {}
    for name, info in found.items():
        inl = pylsl.StreamInlet(info, max_buflen=int(a.seconds) + 30)
        inl.open_stream(timeout=5)
        inlets[name] = inl
    offset = pylsl.local_clock() - time.time()
    data = {n: ([], []) for n in inlets}
    print(f"recording {a.seconds:g} s from {sorted(inlets)}…")
    t_stop = time.time() + a.seconds
    while time.time() < t_stop:
        for n, inl in inlets.items():
            x, t = inl.pull_chunk(timeout=0.0)
            if t: data[n][0].extend(x); data[n][1].extend(t)
        time.sleep(0.02)

    ok = True
    for n, inl in sorted(inlets.items()):
        info = inl.info(timeout=5)
        x, t = data[n]
        t = np.array(t)
        print(f"\n== {n}  type={info.type()}  channels={info.channel_count()}  "
              f"nominal={info.nominal_srate():g} Hz  source_id={info.source_id()}")
        if n.endswith("-EEG"):
            d = np.diff(t)
            inc = bool(np.all(d > 0))
            ok &= inc
            print(f"samples {t.size}, rate {(t.size - 1) / (t[-1] - t[0]):.3f} Hz" if t.size > 1 else f"samples {t.size}")
            if d.size:
                print(f"strictly increasing: {inc} (backsteps/zero steps: {int((d <= 0).sum())}); "
                      f"spacing ms p50 {np.median(d) * 1e3:.3f}, min {d.min() * 1e3:.3f}, max {d.max() * 1e3:.3f}")
            desc = info.desc()
            ch = desc.child("channels").child("channel")
            labels = []
            while not ch.empty():
                labels.append(ch.child_value("label")); ch = ch.next_sibling()
            print(f"labels {labels}; timing note: {desc.child('timing').child_value('note')!r}")
            if a.csv and t.size:
                ts = []
                with open(a.csv) as f:
                    r = csv.reader(f); next(r)
                    ts = np.array([float(row[0]) for row in r])
                lo, hi = t[0] - offset, t[-1] - offset
                n_csv = int(((ts >= lo) & (ts <= hi)).sum())
                print(f"CSV samples in the same span: {n_csv} vs LSL {t.size} (difference {t.size - n_csv}; "
                      f"edges are approximate)")
        elif n.endswith("-Markers"):
            print(f"markers {len(x)}: " + ", ".join(f"{v[0]!r}@{tt:.3f}" for v, tt in zip(x, t)))
        elif n.endswith("-Quality"):
            ev = [json.loads(v[0]) for v in x]
            for e in ev: print("  ", json.dumps(e)[:200])
            print(f"Quality timestamps never decrease: {bool(np.all(np.diff(t) >= 0))}")
    print("\nRESULT:", "OK" if ok else "EEG timestamps did NOT strictly increase")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
