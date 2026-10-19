"""Timing report — pure numpy (no Qt, no clock). Three groups, never added together
(debate/claude-p300-extension-round-2.md §1):

    measured       what the software observed: timer lateness, paint after fire, missed schedule slots
    estimated      what the EEG timestamps suggest: duplicates, gaps, steps back, timeline flags,
                   online timeline vs whole-session fit
    not_measured   display latency (compositor, refresh, pixel response) and the fixed BLE delay

EEG times are host-RECEIVE estimates, not the time a sample was taken on the scalp.
"""
import numpy as np

NOT_MEASURED = "not measured"


def dist(values_s):
    """min / median / p95 / max in milliseconds of the finite values (None when there are none)."""
    v = np.asarray([x for x in values_s if x is not None], dtype=float)
    v = v[np.isfinite(v)] * 1000.0
    if not v.size: return None
    return dict(n=int(v.size), min=round(float(v.min()), 3), median=round(float(np.median(v)), 3),
                p95=round(float(np.percentile(v, 95)), 3), max=round(float(v.max()), 3))


def fit_timeline(index, r, segment):
    """Whole-session estimate: per segment, least-squares line of the observed receive times ``r`` (already in the
    monotonic clock) against the sample index. Returns (t_fit, per-segment [(segment, period_s, intercept, n)])."""
    index = np.asarray(index, dtype=float); r = np.asarray(r, dtype=float); segment = np.asarray(segment)
    t_fit = np.full(r.shape, np.nan)
    params = []
    for seg in np.unique(segment):
        m = (segment == seg) & np.isfinite(r)
        if m.sum() < 2: continue
        slope, intercept = np.polyfit(index[m], r[m], 1)
        t_fit[segment == seg] = slope * index[segment == seg] + intercept
        params.append((int(seg), float(slope), float(intercept), int(m.sum())))
    return t_fit, params


PAUSE_S = 0.1          # a receive interval longer than this is reported as a pause


def eeg_timestamp_stats(ts_raw, fs, pause_s=PAUSE_S):
    """From the RAW receive timestamps: duplicates (Δ = 0: samples of one Bluetooth packet sharing a time), steps
    back (Δ < 0), bursty intervals (Δ > 3 sample periods — packets arriving in bursts, NOT data loss) and receive
    pauses (Δ > ``pause_s``). Receive times cannot show lost packets. Compare the sample count with the session
    length instead (the measured rate) — the app's package_num step count is not a lost-packet count on Athena."""
    d = np.diff(np.asarray(ts_raw, dtype=float))
    d = d[np.isfinite(d)]
    return dict(samples=int(len(ts_raw)), duplicate_timestamps=int((d == 0).sum()),
                steps_back=int((d < 0).sum()), bursty_intervals=int((d > 3.0 / fs).sum()),
                receive_pauses=int((d > pause_s).sum()), pause_threshold_ms=round(pause_s * 1000, 1),
                longest_receive_interval_ms=round(float(d.max() * 1000), 3) if d.size else None)


def summarize(stims, eeg, fs, clock_steps=0, timeline=None, writer=None, hook_s=(), display_latency_s=None,
              seq_anomalies=None, seq_deltas=None):
    """stims: dicts with planned/fired/painted/missed; eeg: dict of arrays index, ts_raw, r, t_online, segment,
    uncertain (bool); timeline: dict(rebases=…, forward_jumps=…, counters=…) from OnlineTimeline."""
    planned = [s.get("planned_mono") for s in stims]
    fired = [s.get("fired_mono") for s in stims]
    painted = [s.get("painted_mono") for s in stims]
    pairs = lambda a, b: [(y - x) if x is not None and y is not None else None for x, y in zip(a, b)]
    missed = sum(1 for s in stims if s.get("missed"))
    no_paint = sum(1 for p in painted if p is None)
    measured = dict(
        flashes=len(stims), missed=missed, missed_fraction=round(missed / len(stims), 4) if stims else None,
        no_paint=no_paint,
        timer_late_ms=dist(pairs(planned, fired)), paint_after_fire_ms=dist(pairs(fired, painted)),
        paint_after_plan_ms=dist(pairs(planned, painted)), eeg_hook_ms=dist(hook_s))
    estimated = {}
    if eeg is not None and len(eeg.get("index", [])):
        estimated.update(eeg_timestamp_stats(eeg["ts_raw"], fs))
        t_fit, params = fit_timeline(eeg["index"], eeg["r"], eeg["segment"])
        online = np.asarray(eeg["t_online"], dtype=float)
        r = np.asarray(eeg["r"], dtype=float)
        estimated.update(
            uncertain_samples=int(np.asarray(eeg["uncertain"], dtype=bool).sum()),
            segments=int(len(np.unique(eeg["segment"]))),
            online_minus_fit_ms=dist(online - t_fit),
            receive_scatter_online_mad_ms=_mad_ms(r - online), receive_scatter_fit_mad_ms=_mad_ms(r - t_fit),
            fit_per_segment=[dict(segment=s, period_s=p, rate_hz=round(1 / p, 4) if p > 0 else None, samples=n)
                             for s, p, _, n in params])
    if timeline:
        estimated.update(rebases=len(timeline.get("rebases", [])), forward_jumps=len(timeline.get("forward_jumps", [])),
                         timeline_counters=timeline.get("counters", {}))
    estimated["clock_steps_during_session"] = int(clock_steps)
    if seq_anomalies is not None:                       # package_num steps other than 0/1 counted by the app
        estimated["package_num_steps_not_0_or_1_during_session"] = seq_anomalies
        estimated["package_num_note"] = ("NOT a lost-packet count: Athena's package_num rule is unverified (see "
                                         "musemonitor/core/timing.py). Judge data loss from the sample count vs the "
                                         "session length (fit_per_segment rate).")
        if seq_deltas: estimated["package_num_step_histogram_since_connect"] = seq_deltas
    return dict(
        note="Onsets are software estimates (Qt paint). EEG times are host-receive estimates. The three groups are "
             "reported separately and are not added into one uncertainty.",
        onset_source="painted_mono (Qt paintEvent)",
        measured=measured, estimated=estimated,
        not_measured=dict(display_latency=NOT_MEASURED if display_latency_s is None else None,
                          ble_fixed_delay=NOT_MEASURED),
        display_latency_s=display_latency_s,
        writer=writer or {})


def _mad_ms(v):
    v = np.asarray(v, dtype=float); v = v[np.isfinite(v)]
    if not v.size: return None
    return round(float(np.median(np.abs(v - np.median(v))) * 1000), 3)
