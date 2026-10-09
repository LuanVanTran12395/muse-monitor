"""Measurement report for core.online_timeline (LSL stage 2). A TOOL, not a test: prints markdown tables.

    PYTHONPATH=src:tests ~/.venvs/musemonitor/bin/python tools/timeline_report.py            # model + data/
    PYTHONPATH=src:tests ~/.venvs/musemonitor/bin/python tools/timeline_report.py --seeds 5  # quicker

Sections:
1. MODEL scenarios (tests/timeline_sim.py, "athena_empirical" batching measured on Athena recordings):
   counters, jumps/rebases, and |t_out − (true sampling time + median latency)| after the first 30 s.
   These numbers describe the model, not a real headset.
2. Other batching models (robustness).
3. A small parameter sweep (gain × slew) on the clean model.
4. REAL host timestamps in data/: capture_athena .npz files (exact chunks and read times) and app
   recordings (chunks rebuilt from 20 ms polls — approximate). Only r − t_out can be measured there
   (the true sampling time is unknown); offset unix→mono is a constant 0 (no clock bridge needed offline).
"""
import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

import timeline_sim as TS  # noqa: E402
from musemonitor.core.online_timeline import OnlineTimeline, TimelineConfig  # noqa: E402

NOMINAL = {"eeg": 256.0, "opt": 64.0, "imu": 52.0}
SCENARIOS = {
    "clean": [],
    "rate 256.88→256.70 at 30 s": [TS.Event("rate", 30.0, fs=256.70)],
    "2 s lost": [TS.Event("pause", 30.0, 2.0, "lost")],
    "0.5 s stall + burst": [TS.Event("pause", 30.0, 0.5, "late")],
    "2 s backlog drained 1.2×": [TS.Event("pause", 30.0, 2.0, "late", drain=1.2)],
    "2 s backlog drained 1.01×": [TS.Event("pause", 30.0, 2.0, "late", drain=1.01)],
}


def ms(x):
    return "—" if x is None else f"{1000 * x:.2f}"


def model_run(seed, events, model="athena_empirical", dur=120.0, flagged=False, **cfg):
    sim = TS.simulate(seed, dur, "eeg", model, events=events)
    tl = OnlineTimeline(TimelineConfig(NOMINAL["eeg"], **cfg))
    out = TS.replay(sim, tl)
    lat = np.median(sim.deliver - sim.true_t)
    seg, t = out["segment"], out["t_out"]
    mono = bool(np.all(np.diff(t)[seg[1:] == seg[:-1]] > 0))
    ok = (sim.true_t > 30) & ~out["uncertain"]                         # unflagged only
    err = np.abs(t - (sim.true_t + lat))[ok]
    if flagged: return tl.report(), mono, err, float(np.mean(out["uncertain"][sim.true_t > 30]))
    return tl.report(), mono, err


def pct(a):
    return (np.percentile(a, 50), np.percentile(a, 95), np.percentile(a, 99), a.max()) if a.size else (None,) * 4


def section_model(seeds):
    print("## 1. Model scenarios (EEG, athena_empirical, 120 s each)\n")
    print(f"{len(seeds)} seeds per scenario. |err| = |t_out − (true time + median latency)|, UNFLAGGED samples after 30 s, pooled;\n"
          "'flagged %' = share of samples after 30 s the algorithm flagged.\n")
    print("| Scenario | strictly ↑ | pauses | caught up | extensions | jumps | rebases | outliers | flagged % | |err| p50 | p95 | p99 | max (ms) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name, ev in SCENARIOS.items():
        runs = [model_run(s, ev, flagged=True) for s in seeds]
        reps, monos, errs, flag = zip(*runs)
        c = lambda k: sum(r["counters"][k] for r in reps)
        p50, p95, p99, mx = pct(np.concatenate(errs))
        print(f"| {name} | {sum(monos)}/{len(seeds)} | {c('arrival_pauses')} | {c('pauses_caught_up')} | {c('pause_extensions')} | "
              f"{sum(len(r['forward_jumps']) for r in reps)} | {sum(len(r['rebases']) for r in reps)} | {c('outlier_chunks')} | "
              f"{100 * np.mean(flag):.1f} | {ms(p50)} | {ms(p95)} | {ms(p99)} | {ms(mx)} |")
    print()


def section_models(seeds):
    print("## 2. Other batching models (clean, robustness)\n")
    print("| Model | Δts = 0 share | strictly ↑ | rebases | |err| p50 | p95 | p99 (ms) |")
    print("|---|---|---|---|---|---|---|")
    for model in ("athena_empirical", "distinct", "fixed_12", "bursty"):
        share = np.mean(np.diff(TS.simulate(0, 60, "eeg", model).ts_unix) == 0)
        reps, monos, errs = zip(*(model_run(s, [], model) for s in seeds))
        p50, p95, p99, _ = pct(np.concatenate(errs))
        print(f"| {model} | {100 * share:.1f} % | {sum(monos)}/{len(seeds)} | {sum(len(r['rebases']) for r in reps)} | "
              f"{ms(p50)} | {ms(p95)} | {ms(p99)} |")
    print()


def section_sweep(seeds):
    print("## 3. Parameter sweep (clean, athena_empirical)\n")
    print("| gain | slew | |err| p50 | p95 | p99 (ms) | slew-limited chunks |")
    print("|---|---|---|---|---|---|")
    for g in (0.05, 0.1, 0.2):
        for s in (5e-4, 1e-3, 2e-3):
            reps, _, errs = zip(*(model_run(sd, [], gain=g, slew=s) for sd in seeds))
            p50, p95, p99, _ = pct(np.concatenate(errs))
            lim = np.mean([r["counters"]["slew_limited_chunks"] / max(1, r["counters"]["chunks"]) for r in reps])
            print(f"| {g} | {s:g} | {ms(p50)} | {ms(p95)} | {ms(p99)} | {100 * lim:.0f} % |")
    print()


def feed_real(ts, chunks, fs_nom):
    """chunks: [(i0, i1, arrival)] in the same (unix) clock as ts."""
    tl = OnlineTimeline(TimelineConfig(fs_nom))
    seg_prev, t_prev, mono = None, None, True
    for i0, i1, arr in chunks:
        res = tl.push(ts[i0:i1], arr)
        if seg_prev == res.segment and t_prev is not None and res.t_out.size and res.t_out[0] <= t_prev: mono = False
        if res.t_out.size: mono &= bool(np.all(np.diff(res.t_out) > 0))
        seg_prev, t_prev = res.segment, (res.t_out[-1] if res.t_out.size else t_prev)
    return tl.report(), mono


def poll_chunks(ts, poll=0.02):
    """APPROXIMATE chunks of an app recording: samples whose timestamp falls in each 20 ms poll window.
    IMU timestamps can step back, so the windows are cut on the running maximum (sorted by construction)."""
    env = np.maximum.accumulate(ts)
    polls = np.arange(env[0] + poll, env[-1] + 2 * poll, poll)
    cut = np.searchsorted(env, polls, side="right")
    out, i0 = [], 0
    for p, c in zip(polls, cut):
        if c > i0: out.append((i0, int(c), float(p))); i0 = int(c)
    return out


def real_sources(data_dir):
    for f in sorted(glob.glob(str(data_dir / "*.npz"))):
        z = np.load(f, allow_pickle=False)
        meta = json.loads(str(z["meta"]))
        for key, stream in (("eeg", "eeg"), ("optics", "opt"), ("imu", "imu")):
            if f"{key}_data" not in z: continue
            row = meta["board_descr"][key]["timestamp_channel"]
            ts = z[f"{key}_data"][row]
            lens, wall = z[f"{key}_chunk_lens"], z[f"{key}_poll_wall"]
            ends = np.cumsum(lens); starts = ends - lens
            yield Path(f).name + " (exact chunks)", stream, ts, list(zip(starts, ends, wall))
    from musemonitor.device.profiles import discover_profiles
    from musemonitor.storage.reader import ReaderError, inspect, load, locate
    for d in sorted(p for p in data_dir.glob("muse_*") if p.is_dir()):
        try:
            s = load(inspect(locate(d), discover_profiles()))
        except ReaderError:
            continue
        for stream in ("eeg", "opt", "imu"):
            if stream in s.streams:
                ts = s.streams[stream][0]
                yield d.name + " (≈ 20 ms polls)", stream, ts, poll_chunks(ts)


def section_real(data_dir):
    print("## 4. Real host timestamps (data/)\n")
    rows = list(real_sources(data_dir))
    if not rows:
        print("No recordings found in data/ — this section is empty.\n"); return
    print("Only r − t_out is measurable (the true sampling time is unknown); r and t_out both come from host\n"
          "timestamps, so this is an internal consistency check, not EEG–marker accuracy. Unflagged samples.\n")
    print("| Recording | Stream | s | strictly ↑ | fs est. | pauses | jumps | rebases | r−t_out p01 | p50 | p99 | min | max (ms) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name, stream, ts, chunks in rows:
        rep, mono = feed_real(ts, chunks, NOMINAL[stream])
        r = rep["residual_s"]["unflagged"]
        print(f"| {name} | {stream} | {ts[-1] - ts[0]:.0f} | {mono} | {rep['fs_estimate']:.3f} | {rep['counters']['arrival_pauses']} | "
              f"{len(rep['forward_jumps'])} | {len(rep['rebases'])} | {ms(r.get('p01'))} | {ms(r.get('p50'))} | {ms(r.get('p99'))} | "
              f"{ms(r.get('min'))} | {ms(r.get('max'))} |")
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    a = ap.parse_args()
    seeds = list(range(a.seeds))
    print("# OnlineTimeline measurement report\n")
    print(f"Defaults: {TimelineConfig(256)}\n")
    section_model(seeds)
    section_models(seeds[:5])
    section_sweep(seeds[:5])
    section_real(a.data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
