"""Simulated Athena host-receive timestamps for OnlineTimeline tests and tools/timeline_report.py.

Only AGGREGATE parameters measured on Athena recordings are encoded here (run-length shares of samples
sharing one timestamp, per stream) — no personal data. Every number this produces describes the MODEL,
not the accuracy of a real headset.

Model ("athena_empirical"): samples are grouped into runs whose lengths follow the measured shares; a run
is delivered at (true time of its last sample + latency + jitter), with a slowly varying bounded jitter;
deliveries are kept in order. The app polls every ``poll`` s: a chunk = everything delivered since the
previous poll, ``arrival`` = the poll time. Time is "mono" seconds; the unix clock = mono + offset(t).
"""
from dataclasses import dataclass, field

import numpy as np

RUN_SHARES = {                       # measured on 5 Athena recordings (debate/claude-lsl-athena-stage2-round-2.md)
    "eeg": {1: 0.73, 2: 0.095, 3: 0.025, 4: 0.135, 5: 0.015},
    "opt": {1: 0.835, 2: 0.165},
    "imu": {1: 1.0},
}
FS_TRUE = {"eeg": 256.88, "opt": 64.03, "imu": 52.06}
UNIX0 = 1.79e9


@dataclass
class Event:
    kind: str                        # "pause" | "clock_step" | "rate"
    t: float
    d: float = 0.0                   # pause duration / clock step size
    mode: str = "lost"               # pause: "lost" (never delivered) | "late" (held, then delivered)
    drain: float = None              # late pause: backlog delivered at drain × fs (None = all at once)
    fs: float = None                 # rate: new true rate


@dataclass
class Sim:
    true_t: np.ndarray               # true sampling time of each DELIVERED sample (mono s)
    deliver: np.ndarray              # host delivery time (mono s)
    ts_unix: np.ndarray              # what BrainFlow would stamp (unix clock at delivery)
    chunks: list                     # [(i0, i1, arrival_mono)]
    events: list = field(default_factory=list)

    def unix_at(self, t):
        return t + UNIX0 + sum(e.d for e in self.events if e.kind == "clock_step" and t >= e.t)


def _run_lengths(rng, n, model, stream):
    if model == "athena_empirical":
        shares = RUN_SHARES[stream]
        L, p = np.array(list(shares)), np.array(list(shares.values()), dtype=float)
        draws = rng.choice(L, size=n, p=p / p.sum())
    elif model == "distinct":
        draws = np.ones(n, dtype=int)
    elif model == "fixed_12":
        draws = np.full(n, 12)
    elif model == "bursty":
        draws = rng.integers(1, 21, size=n)
    else:
        raise ValueError(model)
    return draws


def simulate(seed, dur=120.0, stream="eeg", model="athena_empirical", latency=0.015, jitter=0.020,
             poll=0.020, events=(), fs_true=None):
    rng = np.random.default_rng(seed)
    events = sorted(events, key=lambda e: e.t)
    fs = fs_true or FS_TRUE[stream]
    # true sampling times (piecewise rate)
    t, out = 0.0, []
    rates = [e for e in events if e.kind == "rate"]
    while t < dur:
        out.append(t)
        cur = fs
        for e in rates:
            if t >= e.t: cur = e.fs
        t += 1.0 / cur
    true_all = np.array(out)
    # runs and base delivery times (bounded slowly varying jitter, in order)
    runs = _run_lengths(rng, true_all.size, model, stream)
    ends = np.minimum(np.cumsum(runs), true_all.size)
    ends = ends[np.r_[True, np.diff(ends) > 0]]
    starts = np.r_[0, ends[:-1]]
    j, prev = jitter / 2, -np.inf
    run_deliver = np.empty(ends.size)
    for i, e in enumerate(ends):
        j = float(np.clip(j + rng.normal(0, jitter / 20), 0, jitter))
        d = true_all[e - 1] + latency + j
        d = max(d, prev + 1e-6)
        run_deliver[i] = prev = d
    keep = np.ones(ends.size, dtype=bool)
    # pauses
    for ev in (e for e in events if e.kind == "pause"):
        a, b = ev.t, ev.t + ev.d
        inside = (run_deliver >= a) & (run_deliver < b)
        if ev.mode == "lost":
            keep &= ~inside
        else:                                     # late: one in-order queue drained at drain × fs from b
            cursor = None
            for i in range(ends.size):
                if not keep[i] or run_deliver[i] < a: continue
                d0, n_i = run_deliver[i], ends[i] - starts[i]
                if inside[i]:
                    d = b if cursor is None else (cursor + (1e-6 if ev.drain is None else n_i / (ev.drain * fs)))
                    d = max(d, b)
                elif cursor is not None:
                    step = 1e-6 if ev.drain is None else n_i / (ev.drain * fs)
                    d = max(d0, cursor + step)
                    if d == d0: cursor = None                         # queue drained: back to normal
                else:
                    break
                run_deliver[i] = d
                if cursor is not None or inside[i]: cursor = d
    idx = np.concatenate([np.arange(s, e) for s, e, k in zip(starts, ends, keep) if k]) if keep.any() else np.empty(0, int)
    deliver = np.concatenate([np.full(e - s, d) for s, e, d, k in zip(starts, ends, run_deliver, keep) if k])
    true_t = true_all[idx]
    sim = Sim(true_t=true_t, deliver=deliver, ts_unix=np.empty(0), chunks=[], events=list(events))
    sim.ts_unix = np.array([sim.unix_at(d) for d in deliver]) if any(e.kind == "clock_step" for e in events) \
        else deliver + UNIX0
    # polling
    polls = np.arange(poll, deliver.max() + 2 * poll, poll) if deliver.size else np.empty(0)
    cut = np.searchsorted(deliver, polls, side="right")
    i0 = 0
    for p_t, c in zip(polls, cut):
        if c > i0: sim.chunks.append((i0, int(c), float(p_t))); i0 = int(c)
    return sim


class FakeClocks:
    """unix/mono clocks driven by the replay loop (``now`` = mono seconds)."""
    def __init__(self, sim):
        self.sim, self.now = sim, 0.0

    def mono(self):
        return self.now

    def unix(self):
        return self.sim.unix_at(self.now)


def replay(sim, timeline, bridge=None, chunk_filter=None):
    """Feed a Sim through (ClockBridge →) OnlineTimeline. Returns per-sample arrays and the results."""
    from musemonitor.core.online_timeline import ClockBridge
    clocks = FakeClocks(sim)
    bridge = bridge or ClockBridge(clocks.unix, clocks.mono)
    t_out, seg, unc, arrival, results = [], [], [], [], []
    for i0, i1, arr in sim.chunks:
        clocks.now = arr
        offset, mono, stepped = bridge.measure()
        r = bridge.to_mono(sim.ts_unix[i0:i1], offset)
        res = timeline.push(r, mono, uncertain="clock_step" if stepped else None)
        results.append(res)
        t_out.append(res.t_out); seg.append(np.full(i1 - i0, res.segment))
        unc.append(np.full(i1 - i0, res.uncertain)); arrival.append(np.full(i1 - i0, mono))
    cat = lambda xs, dt=float: np.concatenate(xs) if xs else np.empty(0, dt)
    return dict(t_out=cat(t_out), segment=cat(seg, int), uncertain=cat(unc, bool), arrival=cat(arrival),
                results=results, bridge=bridge)
