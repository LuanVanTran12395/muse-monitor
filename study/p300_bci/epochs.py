"""Epochs around STIMULUS ONSET, ERP, grouped averages — pure numpy / scipy (no Qt, no clock).

Order (stated, adjustable): pick channels by name → combine (mean or keep) → band-pass on the CONTINUOUS signal,
separately per block (never across a train/test or block boundary) → cut epochs at the onset → baseline →
amplitude rejection → (later) grouped averages within cell + trial.

Onsets are software estimates (Qt paint time); EEG times are host-receive estimates (see timing.py).
"""
from dataclasses import asdict, dataclass, field

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi, sosfiltfilt


@dataclass
class Preset:
    name: str
    channels: tuple                  # by name; missing channels are an error, never silently replaced
    combine: str = "mean"            # "mean" (one signal) | "keep" (each channel)
    band_hz: tuple = (0.5, 35.0)
    order: int = 4
    tmin_s: float = -0.2
    tmax_s: float = 0.8
    baseline_s: tuple = (-0.2, 0.0)  # None = no baseline
    reject_uv: float = 80.0          # |amplitude| after filtering and baseline, µV; None = off
    note: str = ""

    def to_dict(self):
        return asdict(self)


PRESETS = {
    "li2020": Preset(
        "li2020", ("TP9", "TP10"), "mean", (0.5, 35.0), 4, 0.0, 1.0, None, 80.0,
        note="As in Li, Liu, Cao (2020): TP9/TP10 averaged, 0.5–35 Hz, 1 s epoch, reject > 80 (unit not stated in the "
             "paper; µV assumed). Differences: we filter the continuous signal per block BEFORE cutting epochs (the "
             "paper filtered after concatenating epochs) and cut at stimulus onset (the paper cut at key presses)."),
    "default": Preset(
        "default", ("TP9", "TP10"), "mean", (0.5, 35.0), 4, -0.2, 0.8, (-0.2, 0.0), 80.0,
        note="Same channels and band as li2020, with a 200 ms pre-stimulus baseline."),
}

REASONS = ("missed", "no_paint", "out_of_range", "uncertain", "segment_boundary", "gap", "amplitude")


def select(data, names, preset):
    """(n_sig, n) signals for the preset; ValueError when a channel is missing."""
    missing = [c for c in preset.channels if c not in names]
    if missing:
        raise ValueError(f"preset {preset.name!r} needs channel(s) {', '.join(missing)}; this device has "
                         f"{', '.join(names)} — choose channels for this device instead")
    x = np.asarray(data, dtype=float)[[names.index(c) for c in preset.channels]]
    return x.mean(axis=0, keepdims=True) if preset.combine == "mean" else x


def filter_blocks(x, fs, preset, blocks, causal=False, warmup_s=2.0):
    """Band-pass each block [i0, i1) separately. Zero-phase (sosfiltfilt) for ERP viewing; causal=True is the online
    pipeline (state reset at each block start, first ``warmup_s`` set to NaN)."""
    sos = butter(preset.order, preset.band_hz, btype="bandpass", fs=fs, output="sos")
    y = np.full_like(x, np.nan, dtype=float)
    for i0, i1 in blocks:
        seg = x[:, i0:i1]
        if seg.shape[1] < 3 * (2 * preset.order + 1) * 2: continue          # too short to filter: left as NaN
        if causal:
            zi = sosfilt_zi(sos)[:, None, :] * seg[None, :, :1]
            out, _ = sosfilt(sos, seg, axis=1, zi=zi)
            out[:, :int(warmup_s * fs)] = np.nan
        else:
            out = sosfiltfilt(sos, seg, axis=1)
        y[:, i0:i1] = out
    return y


def sample_at(onset, t):
    """Fractional sample index where the (monotonic) time ``onset`` falls on the EEG timeline ``t`` (NaN outside)."""
    t = np.asarray(t, dtype=float)
    ok = np.isfinite(t)
    if ok.sum() < 2 or not t[ok][0] <= onset <= t[ok][-1]: return np.nan
    return float(np.interp(onset, t[ok], np.flatnonzero(ok)))


def extract(y, t, fs, onsets, preset, segment=None, uncertain=None, missed=None):
    """Epochs (n_ep, n_sig, n_t) and one reason per onset (None = kept). Rejected epochs are NaN-filled."""
    n_sig, n = y.shape
    i_min, i_max = int(round(preset.tmin_s * fs)), int(round(preset.tmax_s * fs))
    times = np.arange(i_min, i_max) / fs
    ep = np.full((len(onsets), n_sig, len(times)), np.nan)
    reasons = []
    seg = np.zeros(n) if segment is None else np.asarray(segment)
    unc = np.zeros(n, bool) if uncertain is None else np.asarray(uncertain, bool)
    tt = np.asarray(t, dtype=float)
    for k, onset in enumerate(onsets):
        if missed is not None and missed[k]: reasons.append("missed"); continue
        if onset is None or not np.isfinite(onset): reasons.append("no_paint"); continue
        c = sample_at(onset, tt)
        if not np.isfinite(c): reasons.append("out_of_range"); continue
        i0 = int(round(c)) + i_min; i1 = int(round(c)) + i_max
        if i0 < 0 or i1 > n: reasons.append("out_of_range"); continue
        if unc[i0:i1].any(): reasons.append("uncertain"); continue
        if np.unique(seg[i0:i1]).size > 1: reasons.append("segment_boundary"); continue
        dt = np.diff(tt[i0:i1])
        if not np.all(np.isfinite(dt)) or np.any(dt > 3.0 / fs) or np.any(dt <= 0): reasons.append("gap"); continue
        e = y[:, i0:i1].copy()
        if not np.all(np.isfinite(e)): reasons.append("gap"); continue
        if preset.baseline_s is not None:
            b = (times >= preset.baseline_s[0]) & (times < preset.baseline_s[1])
            if b.any(): e -= e[:, b].mean(axis=1, keepdims=True)
        if preset.reject_uv is not None and np.max(np.abs(e)) > preset.reject_uv:
            reasons.append("amplitude"); continue
        ep[k] = e; reasons.append(None)
    return ep, times, reasons


def erp(epochs, is_target, reasons):
    """Mean and standard error per class over the KEPT epochs: {"target": (mean, sem, n), "nontarget": …}."""
    keep = np.array([r is None for r in reasons])
    tgt = np.asarray(is_target, bool)
    out = {}
    for name, m in (("target", keep & tgt), ("nontarget", keep & ~tgt)):
        e = epochs[m]
        if len(e) == 0: out[name] = (None, None, 0); continue
        mean = e.mean(axis=0)
        sem = e.std(axis=0, ddof=1) / np.sqrt(len(e)) if len(e) > 1 else np.zeros_like(mean)
        out[name] = (mean, sem, int(len(e)))
    return out


def reason_counts(reasons):
    return {r: sum(1 for x in reasons if x == r) for r in REASONS} | {"kept": sum(1 for x in reasons if x is None)}


def group_average(epochs, meta, k):
    """Averages of k epochs within the same cell and trial, in repetition order (reps 1..k, k+1..2k, …).
    meta: list of dicts with trial, cell, rep, is_target and 'reason' (None = kept).
    Rules (round 2 §3): requires R ≥ k; the remainder R mod k is dropped and counted; a group with a rejected
    member is NOT formed (no smaller groups). Returns (averages, group_meta, counts)."""
    if k < 1: raise ValueError("k must be ≥ 1")
    reps = {}
    for i, m in enumerate(meta):
        reps.setdefault((m["trial"], m["cell"]), []).append((m["rep"], i))
    R = max((len(v) for v in reps.values()), default=0)
    if R < k: raise ValueError(f"cannot average groups of {k}: only {R} repetitions per cell")
    out, gmeta = [], []
    counts = dict(groups=0, remainder_dropped=0, incomplete_groups=0)
    for (trial, cell), items in sorted(reps.items()):
        items.sort()
        full = len(items) - len(items) % k
        counts["remainder_dropped"] += len(items) - full
        for g in range(0, full, k):
            idx = [i for _, i in items[g:g + k]]
            if any(meta[i]["reason"] is not None for i in idx):
                counts["incomplete_groups"] += 1; continue
            out.append(epochs[idx].mean(axis=0))
            gmeta.append(dict(trial=trial, cell=cell, group=g // k, is_target=meta[idx[0]]["is_target"]))
            counts["groups"] += 1
    return (np.stack(out) if out else np.empty((0,) + epochs.shape[1:])), gmeta, counts


# ---- whole session -----------------------------------------------------------------------------------------
def block_ranges(trials, t, n):
    """Sample ranges [i0, i1) of each block, from the trials' start / end times on the EEG timeline ``t``."""
    by_block = {}
    for tr in trials:
        by_block.setdefault(tr["block"], []).append(tr)
    ranges = []
    for b, trs in sorted(by_block.items()):
        start = min(x["cue_on_mono"] for x in trs if x.get("cue_on_mono") is not None) - 2.0   # 2 s warm-up margin
        end = max((x["end_mono"] for x in trs if x.get("end_mono") is not None), default=None)
        if end is None: end = np.nanmax(t)
        i0 = int(np.searchsorted(t, start)); i1 = int(np.searchsorted(t, end + 1.0))
        ranges.append((max(0, i0), min(n, i1)))
    return ranges or [(0, n)]


def analyse_session(session, preset, fit_timeline, timeline="fit", causal=False):
    """ERP of a loaded session (session.load). timeline: "fit" (whole-session regression, default offline) or
    "online" (the OnlineTimeline estimate recorded live). ``fit_timeline`` is timing.fit_timeline (passed in so this
    module has no sibling imports and runs both inside the app and from offline.py)."""
    cfg = session["config"]; eeg = session["eeg"]
    fs = float(cfg["fs"]); names = list(cfg["channels"])
    x = select(eeg["data"], names, preset)
    if timeline == "fit":
        t, _ = fit_timeline(eeg["index"], eeg["r"], eeg["segment"])
    else:
        t = np.asarray(eeg["t_online"], dtype=float)
    uncertain = np.array([bool(f) for f in eeg["flag"]])
    blocks = block_ranges(session["trials"], t, x.shape[1])
    y = filter_blocks(x, fs, preset, blocks, causal=causal)
    st = session["stimuli"]
    onsets = [s.get("painted_mono") for s in st]
    missed = [bool(s.get("missed")) for s in st]
    ep, times, reasons = extract(y, t, fs, onsets, preset, eeg["segment"], uncertain, missed)
    targets = [bool(s.get("is_target")) for s in st]
    return dict(epochs=ep, times=times, reasons=reasons, is_target=targets, erp=erp(ep, targets, reasons),
                trial=[s.get("trial") for s in st], block=[s.get("block") for s in st],
                counts=reason_counts(reasons), preset=preset.to_dict(), timeline=timeline,
                incomplete=not cfg.get("completed"), mode=cfg.get("mode"))
