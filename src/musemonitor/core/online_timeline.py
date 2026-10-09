"""OnlineTimeline: a strictly increasing, nearly regular timeline for samples whose timestamps are
host-receive times (Muse S Athena through BrainFlow). Prototype for LSL output (stage 2 of
debate/lsl-athena-proposal.md; design in debate/claude-lsl-athena-stage2-round-2.md).

What the output is — and is not: an ESTIMATE of the host-receive time, smoothed. It is not the sampling
time on the device, which these timestamps cannot reveal. Pure numpy: no Qt, no LSL, no clock calls
inside ``OnlineTimeline``; clocks are passed in (``ClockBridge``), so the same input always gives the same
output.

Per chunk ``push(r, arrival)``:
  r        observed time of every sample, already in a monotonic clock (``ClockBridge.to_mono``)
  arrival  monotonic time the chunk reached the app (the hook call)

Rules (all parameters in TimelineConfig are trial values, not calibrated):
- normal: phase error e = median(r − predicted). |e| < G → bounded phase correction (spacing changes
  by at most ``slew``); the sample period follows a regression of r on sample index over ``fit_window_s``.
  Until then the phase may be corrected faster (``acquire_slew``). The FIRST valid estimate (after
  ``min_fit_s`` = 20 s; after 10 s it was off by up to 0.3–0.4 Hz) is taken as is — "acquisition": the real rate of an
  Athena differs from nominal by ~0.3 %, far beyond a 200 ppm step — later ones move the period by at
  most ``period_step_ppm`` per update, once per ``period_update_s`` of arrival time.
- e > G (observations far later than predicted: data stopped arriving, or arrives late): pause_pending.
  Keep emitting at the period; decide after ``confirm_s`` seconds of ARRIVAL time: caught up (e < G/2)
  → back to normal, no jump; still catching up (e fell by ≥ ``catchup_min_rate`` s per s since the last
  check) → wait another ``confirm_s``, up to ``max_wait_s`` — a backlog that drains slowly is not mistaken
  for lost data; otherwise one FORWARD jump ("not caught up within the wait" — not a claim that samples
  were lost).
- e < −G in a single chunk (e.g. a clock step inside the chunk): emitted at the period, marked
  uncertain (outlier). Persisting for ``rebase_chunks`` chunks and ``rebase_min_s`` seconds, or any
  emitted timestamp ahead of ``arrival + G`` ("in the future") → REBASE: a new segment re-anchored to
  the observations. Timestamps strictly increase within a segment; between segments they may go back,
  and the caller must handle it (new outlet / segment, or drop) — see TimelineResult.rebase.

Flags: ``TimelineResult.uncertain`` is True for chunks the algorithm flagged — transient reasons (pause
pending, outlier, clock step) and the PERSISTENT state ``timing_uncertain`` that starts at an unrecovered
forward jump or a rebase. After those, an unknown delay may remain (a backlog drained at exactly the
sampling rate looks like fresh data), so the state is not cleared by the arrival rate: only ``reset()``
(stream stopped/restarted) or ``mark_flushed()`` (the caller has evidence the backlog is gone) clear it.
Unflagged ("trusted") means only "not flagged by the algorithm" — never a validated physiological time.

Each chunk gets ONE ``reason`` (TimelineResult.reason, None when unflagged), chosen by REASON_PRIORITY.
``report()["uncertain_intervals"]`` is the run-length encoding of exactly those per-chunk reasons, in
arrival order: disjoint, ascending, never revised afterwards — it can be turned into quality events as
is. Where a forward jump's wait started is in ``forward_jumps`` instead (no retroactive interval).
Residual histograms count only FINITE r − t_out; invalid input timestamps are counted separately.
The sample-rate regression keeps using chunks in that state, so drift and further rebases are still seen.
"""
from collections import deque
from dataclasses import dataclass, field

import numpy as np

# when a chunk has several reasons, the one reported (most severe first)
REASON_PRIORITY = ("rebase", "pause_unrecovered_after_wait", "clock_step", "invalid_timestamp", "outlier",
                   "pause_pending")
HIST_RANGE_S = 2.0
HIST_BIN_S = 1e-4


@dataclass(frozen=True)
class TimelineConfig:
    fs_nominal: float
    fit_window_s: float = 30.0
    min_fit_s: float = 20.0
    period_update_s: float = 1.0
    gain: float = 0.1
    slew: float = 1e-3
    acquire_slew: float = 1e-2      # slew allowed until the period has been acquired (start-up only)
    period_step_ppm: float = 200.0
    period_tolerance: float = 0.02
    gap_s: float = 0.25
    gap_periods: int = 10
    confirm_s: float = 2.0
    catchup_min_rate: float = 0.02
    max_wait_s: float = 30.0
    rebase_chunks: int = 3
    rebase_min_s: float = 0.1

    def __post_init__(self):
        checks = {
            "fs_nominal > 0": self.fs_nominal > 0, "fit_window_s > 0": self.fit_window_s > 0,
            "0 < min_fit_s <= fit_window_s": 0 < self.min_fit_s <= self.fit_window_s,
            "period_update_s >= 0": self.period_update_s >= 0, "0 < gain <= 1": 0 < self.gain <= 1,
            "0 < slew < 1": 0 < self.slew < 1, "slew <= acquire_slew < 1": self.slew <= self.acquire_slew < 1, "period_step_ppm > 0": self.period_step_ppm > 0,
            "0 < period_tolerance < 1": 0 < self.period_tolerance < 1, "gap_s > 0": self.gap_s > 0,
            "gap_periods >= 1": self.gap_periods >= 1, "confirm_s > 0": self.confirm_s > 0,
            "catchup_min_rate > 0": self.catchup_min_rate > 0, "max_wait_s >= confirm_s": self.max_wait_s >= self.confirm_s,
            "rebase_chunks >= 1": self.rebase_chunks >= 1, "rebase_min_s >= 0": self.rebase_min_s >= 0,
        }
        bad = [k for k, ok in checks.items() if not ok]
        if bad: raise ValueError("invalid TimelineConfig: " + ", ".join(bad))


@dataclass(frozen=True)
class Rebase:
    index: int              # global index of the first sample of the new segment
    shift_s: float          # new first timestamp − what the old segment would have given it
    reason: str             # "behind_observations" | "future"


@dataclass
class TimelineResult:
    t_out: np.ndarray       # a NEW array, one timestamp per sample
    segment: int
    rebase: Rebase = None   # set when this chunk starts a new segment
    uncertain: bool = False
    reason: str = None      # why flagged: a REASON_PRIORITY entry, or "timing_uncertain:<cause>"; None = unflagged


class _Hist:
    """Residual histogram (0.1 ms bins over ±2 s) with exact min/max and under/overflow counts."""
    def __init__(self):
        self.n_bins = int(round(2 * HIST_RANGE_S / HIST_BIN_S))
        self.counts = np.zeros(self.n_bins, dtype=np.int64)
        self.under = self.over = self.n = 0
        self.min, self.max = np.inf, -np.inf

    def add(self, v):
        v = np.asarray(v, dtype=float)
        v = v[np.isfinite(v)]
        if not v.size: return
        self.n += v.size; self.min = min(self.min, v.min()); self.max = max(self.max, v.max())
        idx = np.floor((v + HIST_RANGE_S) / HIST_BIN_S).astype(np.int64)
        self.under += int((idx < 0).sum()); self.over += int((idx >= self.n_bins).sum())
        ok = (idx >= 0) & (idx < self.n_bins)
        np.add.at(self.counts, idx[ok], 1)

    def quantile(self, q):
        """q-quantile (bin centre); under/overflow count as the range ends."""
        if self.n == 0: return None
        target = q * self.n
        if target <= self.under: return -HIST_RANGE_S
        c = np.cumsum(self.counts) + self.under
        i = int(np.searchsorted(c, target))
        if i >= self.n_bins: return HIST_RANGE_S
        return -HIST_RANGE_S + (i + 0.5) * HIST_BIN_S

    def summary(self):
        if self.n == 0: return dict(n=0)
        return dict(n=self.n, min=float(self.min), max=float(self.max), underflow=self.under, overflow=self.over,
                    p01=self.quantile(0.01), p50=self.quantile(0.5), p95=self.quantile(0.95), p99=self.quantile(0.99))


class OnlineTimeline:
    def __init__(self, config):
        self.cfg = config
        self.reset()

    def reset(self):
        cfg = self.cfg
        self.p = 1.0 / cfg.fs_nominal
        self.t_last = None
        self.n = 0
        self.segment = 0
        self.state = "normal"
        self._pending = None
        self._neg = None                       # (chunks, arrival of the first) while e < −G
        self._obs = deque()                    # (index mid, median r, arrival)
        self._last_period_update = None
        self.period_log = []                   # (sample index, period) after each update
        self.uncertain = []                    # [(first index, end index, reason)]
        self.timing_uncertain = None           # persistent reason after an unrecovered jump / rebase, else None
        self.timing_uncertain_since = None
        self.rebases = []
        self.forward_jumps = []
        self.counters = dict(chunks=0, arrival_pauses=0, pauses_caught_up=0, pauses_unrecovered_after_wait=0,
                             pause_extensions=0, outlier_chunks=0, timing_uncertain_episodes=0, period_acquired=0, period_updates=0, period_rejected=0, invalid_samples=0,
                             slew_limited_chunks=0, uncertain_samples=0)
        self._hist = {"unflagged": _Hist(), "flagged": _Hist()}

    @property
    def period(self):
        return self.p

    # ---- main entry ---------------------------------------------------------------------------------
    def push(self, r, arrival, uncertain=None):
        cfg = self.cfg
        r = np.array(r, dtype=float)
        k = r.size
        if k == 0: return TimelineResult(np.empty(0), self.segment)
        self.counters["chunks"] += 1
        steps = np.arange(1, k + 1, dtype=float)
        finite = np.isfinite(r)
        self.counters["invalid_samples"] += int(k - finite.sum())
        rebase, reasons = None, []
        if uncertain: reasons.append(uncertain)
        if not finite.all(): reasons.append("invalid_timestamp")

        if self.t_last is None:                                       # first chunk: anchor on observations
            self.t_last = float(np.median(r[finite] - self.p * steps[finite])) if finite.any() else float(arrival) - k * self.p
            e = 0.0
        else:
            e = float(np.median(r[finite] - (self.t_last + self.p * steps[finite]))) if finite.any() else 0.0
        G = max(cfg.gap_s, cfg.gap_periods * self.p)
        pc = self.p

        if uncertain or not finite.any():
            pass                                                       # caller says unreliable (clock step), or nothing usable:
                                                                       # emit at the period, no correction, no state change
        elif self.state == "pause_pending":
            if e < G / 2:
                self.state = "normal"; self.counters["pauses_caught_up"] += 1; self._pending = None
            elif (arrival >= self._pending["deadline"]
                  and (self._pending["e"] - e) / max(arrival - self._pending["checked"], 1e-9) >= cfg.catchup_min_rate
                  and arrival - self._pending["arrival"] + cfg.confirm_s <= cfg.max_wait_s):
                self._pending.update(deadline=arrival + cfg.confirm_s, checked=arrival, e=e)   # still catching up
                self.counters["pause_extensions"] += 1; reasons.append("pause_pending")
            elif arrival >= self._pending["deadline"]:
                self.t_last += e                                       # forward only (e ≥ G/2 > 0)
                self.forward_jumps.append((self.n, e, self._pending["index"]))   # (jump index, size, wait start)
                self.counters["pauses_unrecovered_after_wait"] += 1
                reasons.append("pause_unrecovered_after_wait")          # the jump chunk itself is flagged too
                self._enter_timing_uncertain("pause_unrecovered_after_wait")
                self.state = "normal"; self._pending = None; e = 0.0
            else:
                reasons.append("pause_pending")

        if not uncertain and finite.any() and self.state == "normal" and "pause_pending" not in reasons:
            if e > G:
                self.state = "pause_pending"
                self._pending = dict(index=self.n, arrival=arrival, deadline=arrival + cfg.confirm_s, checked=arrival, e=e)
                self.counters["arrival_pauses"] += 1; self._obs.clear(); self._neg = None
                reasons.append("pause_pending")
            elif e < -G:
                if self._neg is None: self._neg = (0, arrival)
                self._neg = (self._neg[0] + 1, self._neg[1])
                if self._neg[0] >= cfg.rebase_chunks and arrival - self._neg[1] >= cfg.rebase_min_s:
                    rebase = "behind_observations"
                else:
                    self.counters["outlier_chunks"] += 1; reasons.append("outlier")
            else:
                self._neg = None
                slew = cfg.slew if self.counters["period_acquired"] else cfg.acquire_slew
                lim = slew * k * self.p
                delta = cfg.gain * e
                if abs(delta) > lim: self.counters["slew_limited_chunks"] += 1
                pc = self.p + float(np.clip(delta, -lim, lim)) / k

        t_out = self.t_last + pc * steps
        if rebase is None and t_out[-1] > arrival + G: rebase = "future"
        if rebase is not None:
            anchor = float(np.median(r[finite] - self.p * steps[finite])) if finite.any() else float(arrival) - k * self.p
            new = anchor + self.p * steps
            info = Rebase(index=self.n, shift_s=float(new[0] - t_out[0]), reason=rebase)
            self.rebases.append(info); self.segment += 1
            t_out = new; self.state = "normal"; self._pending = None; self._neg = None; self._obs.clear()
            reasons.append("rebase")
            self._enter_timing_uncertain("rebase")
        reason = next((r for r in REASON_PRIORITY if r in reasons), reasons[0] if reasons else None)
        if reason is None and self.timing_uncertain: reason = "timing_uncertain:" + self.timing_uncertain
        if reason: self._mark(self.n, self.n + k, reason)

        flagged = reason is not None
        if not reasons and self.state == "normal" and finite.any():    # rate tracking ignores the persistent flag
            self._obs.append((self.n + (k - 1) / 2.0, float(np.median(r[finite])), arrival))
            self._update_period(arrival)
        resid = r - t_out
        self._hist["flagged" if flagged else "unflagged"].add(resid)
        if flagged: self.counters["uncertain_samples"] += k
        self.t_last = float(t_out[-1]); self.n += k
        return TimelineResult(t_out, self.segment, None if rebase is None else self.rebases[-1], flagged, reason)

    def mark_flushed(self):
        """The caller has EVIDENCE that any backlog is gone (e.g. it flushed the device buffer): clear the
        persistent ``timing_uncertain`` state. Not to be called because the arrival rate looks normal."""
        self.timing_uncertain = self.timing_uncertain_since = None

    def _enter_timing_uncertain(self, reason):
        if self.timing_uncertain is None:
            self.counters["timing_uncertain_episodes"] += 1
            self.timing_uncertain_since = self.n
        self.timing_uncertain = reason

    # ---- helpers -------------------------------------------------------------------------------------
    def _mark(self, a, b, reason):
        """Append [a, b) — always the chunk just emitted, so intervals stay disjoint and ascending."""
        if self.uncertain and self.uncertain[-1][2] == reason and self.uncertain[-1][1] == a:
            self.uncertain[-1] = (self.uncertain[-1][0], b, reason)
        else:
            self.uncertain.append((a, b, reason))

    def _update_period(self, arrival):
        cfg = self.cfg
        while self._obs and self._obs[-1][1] - self._obs[0][1] > cfg.fit_window_s: self._obs.popleft()
        if len(self._obs) < 3 or self._obs[-1][1] - self._obs[0][1] < cfg.min_fit_s: return
        if self._last_period_update is not None and arrival - self._last_period_update < cfg.period_update_s: return
        self._last_period_update = arrival
        x = np.array([o[0] for o in self._obs]); y = np.array([o[1] for o in self._obs])
        x = x - x.mean()
        p_hat = float((x * (y - y.mean())).sum() / (x * x).sum())
        nominal = 1.0 / cfg.fs_nominal
        if not np.isfinite(p_hat) or abs(p_hat - nominal) > cfg.period_tolerance * nominal:
            self.counters["period_rejected"] += 1; return
        if not self.counters["period_acquired"]:
            self.p = p_hat; self.counters["period_acquired"] = 1        # acquisition: first estimate as is
        else:
            step = cfg.period_step_ppm * 1e-6 * self.p
            self.p = float(np.clip(p_hat, self.p - step, self.p + step))
        self.counters["period_updates"] += 1
        self.period_log.append((self.n, self.p))

    def report(self):
        trusted, unc = self._hist["unflagged"], self._hist["flagged"]
        both = _Hist()
        both.counts = trusted.counts + unc.counts; both.under = trusted.under + unc.under
        both.over = trusted.over + unc.over; both.n = trusted.n + unc.n
        both.min, both.max = min(trusted.min, unc.min), max(trusted.max, unc.max)
        return dict(period=self.p, fs_estimate=1.0 / self.p, segment=self.segment, state=self.state,
                    timing_uncertain=self.timing_uncertain, timing_uncertain_since=self.timing_uncertain_since,
                    samples=self.n, counters=dict(self.counters),
                    forward_jumps=[(i, float(e), w) for i, e, w in self.forward_jumps],
                    rebases=[(b.index, b.shift_s, b.reason) for b in self.rebases],
                    uncertain_intervals=list(self.uncertain),
                    # finite residuals only: unflagged.n + flagged.n + counters["invalid_samples"] == samples
                    residual_s=dict(unflagged=trusted.summary(), flagged=unc.summary(), all=both.summary()))


@dataclass
class _Measure:
    order: int
    unix: float
    offset: float
    step: bool


class ClockBridge:
    """Maps unix timestamps to a monotonic clock (LSL's local_clock in stage 3). Clocks are passed in."""
    def __init__(self, unix_clock, mono_clock, tries=3, step_s=0.05, history_s=60.0):
        self.unix, self.mono = unix_clock, mono_clock
        self.tries, self.step_s, self.history_s = tries, step_s, history_s
        self.offset = None
        self.steps = 0
        self._order = 0
        self.history = deque()

    def measure(self):
        """(offset = mono − unix, mono now, stepped). Bracketed read: the pair with the shortest mono window."""
        best = None
        for _ in range(max(1, self.tries)):
            m1 = self.mono(); u = self.unix(); m2 = self.mono()
            if best is None or m2 - m1 < best[0]: best = (m2 - m1, (m1 + m2) / 2.0, u)
        _, m, u = best
        offset = m - u
        stepped = self.offset is not None and abs(offset - self.offset) > self.step_s
        if stepped: self.steps += 1
        self.offset = offset
        self._order += 1
        self.history.append(_Measure(self._order, u, offset, stepped))
        while self.history and m - (self.history[0].unix + self.history[0].offset) > self.history_s:
            self.history.popleft()
        return offset, m, stepped

    @staticmethod
    def to_mono(ts_unix, offset):
        return np.asarray(ts_unix, dtype=float) + offset

    def marker_offset(self, t_unix):
        """(offset, uncertain) for an event stamped t_unix: the latest measurement (in measuring order) with
        unix ≤ t_unix. After a backward step unix values repeat, so the right epoch cannot be known from
        t_unix alone: any clock step in the history window makes the result uncertain (conservative).
        Also uncertain when the event is older than the history."""
        items = list(self.history)
        if not items: return (self.offset if self.offset is not None else 0.0), True
        stepped = any(m.step for m in items)
        for i in range(len(items) - 1, -1, -1):
            if items[i].unix <= t_unix:
                return items[i].offset, stepped
        return items[0].offset, True
