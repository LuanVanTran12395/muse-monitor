"""P300 session report: self-contained HTML (hand-drawn SVG, no plotting library), written into the session folder.

Sections: summary · electrodes (at start + during the session) · good epochs · ERP / P300 per signal · timing
deviations · limits and method. Statistics are EXPLORATORY. The unit of the test is the TRIAL, not the epoch
(epochs of one trial overlap and share the trial's state): per trial, target − non-target mean amplitude in the window,
then a sign-flip test across trials. No correction for testing several signals / sessions. Stage A: no classifier.
"""
import csv
import html
import math
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    import epochs, session, timing                      # noqa: E401  (run from offline.py as a script)
else:
    from . import epochs, session, timing

WINDOW_S = (0.25, 0.50)          # P300 window used for the statistics (stated in the report)
N_PERM = 2000
MIN_KEEP = 0.5                   # a trial is valid when it keeps ≥ this share of its target AND non-target epochs
# measurement-quality thresholds, fixed before C1 (debate/claude-p300-stage-a-round-4.md §2) — operational, not
# physiological: the report always shows the continuous values next to them
QUALITY = dict(attention=0.8, contact_good=0.7, kept_class=0.8, kept_gap=0.10, valid_trials=0.8)
LEVEL_COLORS = {"Good": "#1a7f37", "Fair": "#9a6700", "Bad": "#cf222e", "No signal": "#6e7781", "—": "#d0d7de"}
TARGET, NONTARGET, DIFF = "#cf222e", "#0550ae", "#57606a"

T = {
    "en": dict(
        title="P300 session report", summary="Summary", electrodes="Electrodes", epochs="Good epochs", erp="ERP and P300",
        timing="Timing deviations", limits="Limits and method", files="Files",
        completed="completed", incomplete="INCOMPLETE", mode="mode", duration="duration", trials="trials", flashes="flashes",
        good_epochs="good epochs", window="P300 window", diff="target − non-target (mean over trials)", p_perm="p (sign-flip over trials, exploratory)",
        quality="Measurement quality", attention="Attention (count question)", q_item="check", q_value="value",
        q_threshold="threshold (fixed before)", q_ok="result", ok_yes="pass", ok_no="FAIL", ok_na="not assessed",
        q_contact="contact", q_names=dict(attention="counts right (±1)", **{"epochs kept": "epochs kept", "valid trials": "valid trials"}),
        q_overall_ok="Measurement quality: pass.", q_overall_na="Measurement quality: not fully assessed ({items}).",
        verdict_fail="Measurement quality FAILED ({items}) — no conclusion about a P300 from this session; the "
                     "measure is shown for completeness.",
        att_asked="asked", att_answered="answered", att_exact="exact", att_within1="within ±1", att_trial="trial",
        att_reps="flashes", att_answer="answer",
        pooled="pooled epochs (descriptive)", diff_curve="target − non-target (pooled epochs)", by_block="mean per block", valid_trials="valid trials",
        trial_range="per trial min / median / max",
        at_start="at start", during="during the session (share of time)", sig="signal RMS (median)",
        mains="50 Hz noise (median)", not_recorded="Contact was not recorded during this session (older session).",
        channel="channel", total="total", kept="kept", target="target", nontarget="non-target", reason="reason",
        peak="target peak in window", mean_amp="mean amplitude in window", signal="signal", n="n",
        measured="Measured (software)", estimated="Estimated (EEG receive times)", not_measured="Not measured",
        verdict_none="No reliable target / non-target difference in the P300 window (exploratory test).",
        verdict_few="Too few trials ({n}) for the trial-level test: p cannot go below {pmin:.3f}. Look at the ERP, record more trials.",
        verdict_some="A positive target / non-target difference in the P300 window on the primary signal {chs} (exploratory).",
        contact_warn="Contact on the preset channels was not Good for {pct:.0f} % of the time.",
        eeg_gap_warn="EEG covers only {got:.0f} of the {need:.0f} s of stimulation (no EEG for the last {late:.0f} s) — the "
                     "headset stopped sending; flashes without EEG are rejected as outside the EEG.",
        time_s="time from onset (s)", session_time="session time (min)", paint_plan="planned → painted (ms)",
        flashes_n="flashes", subject="Subject ID",
        pkg_note="an undecoded diagnostic, not a count of lost packets or samples (Athena's package_num rule is "
                 "unverified). The sample count matching the session length is no proof of no loss either: it can hide "
                 "short losses — read it as 'no evidence of loss from the current checks'."),
    "vi": dict(
        title="Báo cáo phiên P300", summary="Tóm tắt", electrodes="Tình trạng điện cực", epochs="Epoch đạt", erp="ERP và P300",
        timing="Độ lệch thời gian", limits="Giới hạn và phương pháp", files="Tệp",
        completed="hoàn chỉnh", incomplete="CHƯA HOÀN CHỈNH", mode="chế độ", duration="thời lượng", trials="lượt",
        flashes="lần sáng", good_epochs="epoch đạt", window="cửa sổ P300", diff="target − non-target (TB theo trial)",
        p_perm="p (đảo dấu theo trial, thăm dò)",
        quality="Chất lượng phép đo", attention="Chú ý (câu hỏi đếm)", q_item="chỉ số", q_value="giá trị",
        q_threshold="ngưỡng (chốt trước)", q_ok="kết quả", ok_yes="đạt", ok_no="KHÔNG ĐẠT", ok_na="chưa đánh giá",
        q_contact="tiếp xúc", q_names=dict(attention="đếm đúng (±1)", **{"epochs kept": "epoch giữ", "valid trials": "trial hợp lệ"}),
        q_overall_ok="Chất lượng phép đo: đạt.", q_overall_na="Chất lượng phép đo: chưa đánh giá đủ ({items}).",
        verdict_fail="Phép đo KHÔNG ĐẠT chất lượng ({items}) — không kết luận về P300 từ phiên này; thước đo vẫn "
                     "được hiển thị cho đầy đủ.",
        att_asked="đã hỏi", att_answered="đã trả lời", att_exact="đúng", att_within1="lệch ≤ 1", att_trial="lượt",
        att_reps="số lần sáng", att_answer="trả lời",
        pooled="gộp epoch (mô tả)", diff_curve="target − non-target (gộp epoch)", by_block="TB theo block",
        valid_trials="trial hợp lệ", trial_range="từng trial nhỏ nhất / trung vị / lớn nhất", at_start="lúc bắt đầu", during="trong phiên (tỉ lệ thời gian)",
        sig="biên độ tín hiệu (trung vị)", mains="nhiễu 50 Hz (trung vị)",
        not_recorded="Phiên này không ghi chất lượng tiếp xúc trong lúc đo (phiên cũ).",
        channel="kênh", total="tổng", kept="giữ", target="target", nontarget="non-target", reason="lý do",
        peak="đỉnh target trong cửa sổ", mean_amp="biên độ trung bình trong cửa sổ", signal="tín hiệu", n="n",
        measured="Đo được (phần mềm)", estimated="Ước lượng được (thời điểm nhận EEG)", not_measured="Chưa đo được",
        verdict_none="Chưa thấy khác biệt target / non-target đáng tin trong cửa sổ P300 (kiểm định thăm dò).",
        verdict_few="Quá ít trial ({n}) cho phép thử theo trial: p không thể nhỏ hơn {pmin:.3f}. Xem ERP, cần ghi thêm trial.",
        verdict_some="Thấy hiệu target − non-target dương trong cửa sổ P300 ở tín hiệu chính {chs} (thăm dò).",
        contact_warn="Tiếp xúc ở các kênh của preset không đạt Good trong {pct:.0f} % thời gian.",
        eeg_gap_warn="EEG chỉ phủ {got:.0f} trên {need:.0f} s kích thích (không có EEG trong {late:.0f} s cuối) — tai nghe đã "
                     "ngừng gửi dữ liệu; các lần sáng không có EEG bị loại là ngoài dữ liệu EEG.",
        time_s="thời gian từ onset (s)", session_time="thời gian phiên (phút)", paint_plan="lên lịch → vẽ (ms)",
        flashes_n="lần sáng", subject="Mã người tham gia",
        pkg_note="chỉ số chẩn đoán chưa giải mã, không phải số gói hay số mẫu bị mất (quy tắc package_num của Athena chưa "
                 "được xác minh). Số mẫu khớp thời lượng phiên cũng không chứng minh không mất: nó có thể che các đoạn mất "
                 "ngắn — chỉ nên đọc là 'chưa thấy bằng chứng mất dữ liệu từ các phép kiểm tra hiện có'."),
}
REASON_TEXT = {
    "en": dict(missed="timer late", no_paint="not painted", out_of_range="outside the EEG", uncertain="timing flagged",
               segment_boundary="timeline rebase", gap="gap", amplitude="amplitude"),
    "vi": dict(missed="timer trễ", no_paint="không được vẽ", out_of_range="ngoài dữ liệu EEG", uncertain="timing bị đánh dấu",
               segment_boundary="timeline tái neo", gap="đứt quãng", amplitude="biên độ lớn"),
}


# ---- statistics -------------------------------------------------------------------------------------------
def window_stats(res, window=WINDOW_S, n_perm=N_PERM, seed=0, min_keep=MIN_KEEP):
    """Target / non-target mean amplitude in the window, their difference, an exploratory p, and the target peak
    (latency, amplitude) in the window — for the first signal of an analyse_session result.

    Primary effect ``diff``: the mean of the per-trial differences (each valid trial — one keeping ≥ ``min_keep`` of
    its target epochs and of its non-target epochs, at least one of each: mean target − mean non-target of its kept
    epochs) — the SAME vector the p uses, so effect and p share one unit. ``diff_pooled`` (all kept target
    epochs − all kept non-target epochs) is descriptive only; the two differ when trials keep different numbers of
    epochs. Also: per-trial differences, their mean per block.

    p: sign-flip test across TRIALS, exact when there are at most 2^12 sign patterns, otherwise ``n_perm`` random
    flips. Trials are separated by the cue and the inter-trial interval, so they are closer to independent than
    epochs 400 ms apart — not fully (contact drift, attention): exploratory."""
    keep = np.array([r is None for r in res["reasons"]]); tg = np.array(res["is_target"], bool)
    t = res["times"]; m = (t >= window[0]) & (t < window[1])
    amp = np.full(len(keep), np.nan)
    amp[keep] = res["epochs"][keep][:, 0, m].mean(axis=1)          # rejected epochs are NaN-filled: skip them
    a_t, a_n = amp[keep & tg], amp[keep & ~tg]
    out = dict(n_target=int(a_t.size), n_nontarget=int(a_n.size), mean_target=None, mean_nontarget=None,
               diff=None, diff_pooled=None, p=None, n_trials=0, trial_diffs=[], block_diffs={},
               peak_latency=None, peak_amplitude=None)
    if a_t.size < 2 or a_n.size < 2: return out
    n = len(keep)
    trial = np.array([-1 if x is None else x for x in res.get("trial") or [None] * n])
    block = np.array([-1 if x is None else x for x in res.get("block") or [None] * n])
    d, d_block = [], []
    for k in np.unique(trial[keep]):
        it, inn = keep & tg & (trial == k), keep & ~tg & (trial == k)
        if k < 0 or not it.any() or not inn.any(): continue          # a trial without both classes is not valid
        if it.sum() < min_keep * (tg & (trial == k)).sum() or inn.sum() < min_keep * (~tg & (trial == k)).sum():
            continue                                                 # mostly rejected: one epoch would dominate
        d.append(amp[it].mean() - amp[inn].mean()); d_block.append(int(block[it][0]))
    d = np.array(d)
    blocks = {b: round(float(d[np.array(d_block) == b].mean()), 4) for b in sorted(set(d_block))}
    mean_t = res["erp"]["target"][0][0]
    i = int(np.argmax(mean_t[m])); tm = t[m]
    out.update(mean_target=float(a_t.mean()), mean_nontarget=float(a_n.mean()),
               diff=float(d.mean()) if d.size else None, diff_pooled=float(a_t.mean() - a_n.mean()),
               n_trials=int(d.size), trial_diffs=[round(float(x), 4) for x in d], block_diffs=blocks,
               p=sign_flip_p(d, n_perm, seed), peak_latency=float(tm[i]), peak_amplitude=float(mean_t[m][i]))
    return out


def sign_flip_p(d, n_perm=N_PERM, seed=0):
    """Two-sided p of mean(d) ≠ 0 under random sign flips of the per-unit differences ``d`` (None if < 2 units)."""
    d = np.asarray(d, dtype=float)
    if d.size < 2: return None
    obs = abs(d.mean())
    if d.size <= 12:                                                  # exact: every sign pattern
        signs = 1 - 2 * ((np.arange(2 ** d.size)[:, None] >> np.arange(d.size)) & 1)
        return float(np.mean(np.abs((signs * d).mean(axis=1)) >= obs - 1e-12))
    rng = np.random.default_rng(seed)
    flips = np.abs((rng.choice((-1.0, 1.0), size=(n_perm, d.size)) * d).mean(axis=1))
    return float((np.sum(flips >= obs - 1e-12) + 1) / (n_perm + 1))


def contact_summary(contact, channels):
    """Per channel: share of time per level, median signal and mains RMS (None when not recorded)."""
    if not contact: return None
    out = {}
    for c in channels:
        rows = [r["channels"][c] for r in contact if c in r["channels"]]
        if not rows: continue
        levels = [r[0] for r in rows]
        out[c] = dict(share={lv: levels.count(lv) / len(levels) for lv in LEVEL_COLORS if levels.count(lv)},
                      signal=float(np.median([r[1] for r in rows])), mains=float(np.median([r[2] for r in rows])))
    return out


def attention(trials):
    """Count question summary (None when no trial was asked): asked, answered, exact, within ±1, per-trial rows."""
    asked = [t for t in trials if t.get("ask_on_mono") is not None]
    if not asked: return None
    rows = [(t["trial"], t.get("repetitions"), t.get("count_answer")) for t in asked]
    ans = [(r, a) for _, r, a in rows if a is not None and r is not None]
    return dict(asked=len(asked), answered=len(ans), exact=sum(a == r for r, a in ans),
                within1=sum(abs(a - r) <= 1 for r, a in ans), rows=rows)


def quality(s, main, channels, att):
    """Measurement quality against QUALITY → list of (key, value text, threshold text, ok True/False/None).
    None = could not be assessed (e.g. no count question, no contact.csv)."""
    out, trials = [], [t for t in s["trials"] if not t.get("aborted")]
    n_tr = len(trials) or 1
    if att is None: out.append(("attention", "—", f"≥ {QUALITY['attention']:.0%}", None))
    else:
        v = att["within1"] / n_tr
        out.append(("attention", f"{att['within1']}/{len(trials)} ({v:.0%})", f"≥ {QUALITY['attention']:.0%}",
                    bool(v >= QUALITY["attention"])))
    st = s["stimuli"]
    t0 = min((x["planned_mono"] for x in st), default=None); t1 = max((x["planned_mono"] for x in st), default=None)
    rows = [r for r in s["contact"] if t0 is not None and t0 <= r["mono"] <= t1 + 1.0]
    for c in channels:
        lv = [r["channels"][c][0] for r in rows if c in r["channels"]]
        if not lv: out.append((f"contact {c}", "—", f"Good ≥ {QUALITY['contact_good']:.0%}", None)); continue
        v = lv.count("Good") / len(lv)
        out.append((f"contact {c}", f"Good {v:.0%} ({len(lv)})", f"Good ≥ {QUALITY['contact_good']:.0%}",
                    bool(v >= QUALITY["contact_good"])))
    if main is not None:
        res, w = main[2], main[3]
        keep = np.array([r is None for r in res["reasons"]]); tg = np.array(res["is_target"], bool)
        kt = keep[tg].mean() if tg.any() else 0.0; kn = keep[~tg].mean() if (~tg).any() else 0.0
        ok = bool(kt >= QUALITY["kept_class"] and kn >= QUALITY["kept_class"] and abs(kt - kn) <= QUALITY["kept_gap"])
        out.append(("epochs kept", f"target {kt:.0%} · non-target {kn:.0%}",
                    f"≥ {QUALITY['kept_class']:.0%}, gap ≤ {QUALITY['kept_gap'] * 100:.0f} pts", ok))
        v = w["n_trials"] / n_tr
        out.append(("valid trials", f"{w['n_trials']}/{len(trials)} ({v:.0%})", f"≥ {QUALITY['valid_trials']:.0%}",
                    bool(v >= QUALITY["valid_trials"])))
    return out


# ---- SVG ------------------------------------------------------------------------------------------------------
def _esc(s):
    return html.escape(str(s))


def _nice(span, target=6):
    raw = span / target; mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


def svg_erp(times, curves, window=WINDOW_S, xlabel="", width=820, height=260):
    """curves: [(label, mean, sem or None, color, dashed)] in µV."""
    ml, mr, mt, mb = 52, 12, 14, 38
    W, H = width - ml - mr, height - mt - mb
    vals = [np.abs(m) + (s if s is not None else 0) for _, m, s, _, _ in curves if m is not None]
    ymax = max(3.0, float(np.nanmax(np.concatenate(vals))) * 1.1) if vals else 3.0
    t0, t1 = float(times[0]), float(times[-1])
    X = lambda v: ml + (v - t0) / (t1 - t0) * W
    Y = lambda v: mt + (ymax - v) / (2 * ymax) * H
    o = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg" '
         f'font-family="-apple-system,Helvetica,Arial" font-size="11">',
         f'<rect x="{X(window[0]):.1f}" y="{mt}" width="{X(window[1]) - X(window[0]):.1f}" height="{H}" fill="#fff8c5"/>']
    step = _nice(t1 - t0)
    v = math.ceil(t0 / step) * step
    while v <= t1 + 1e-9:
        o.append(f'<line x1="{X(v):.1f}" y1="{mt}" x2="{X(v):.1f}" y2="{mt + H}" stroke="#eaeef2"/>'
                 f'<text x="{X(v):.1f}" y="{mt + H + 14}" text-anchor="middle" fill="#57606a">{v:g}</text>')
        v += step
    ys = _nice(2 * ymax)
    v = -math.floor(ymax / ys) * ys
    while v <= ymax + 1e-9:
        o.append(f'<line x1="{ml}" y1="{Y(v):.1f}" x2="{ml + W}" y2="{Y(v):.1f}" stroke="{"#8c959f" if abs(v) < 1e-9 else "#eaeef2"}"/>'
                 f'<text x="{ml - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" fill="#57606a">{v:g}</text>')
        v += ys
    if t0 < 0 < t1:
        o.append(f'<line x1="{X(0):.1f}" y1="{mt}" x2="{X(0):.1f}" y2="{mt + H}" stroke="#8c959f" stroke-dasharray="4 3"/>')
    for label, mean, sem, color, dashed in curves:
        if mean is None: continue
        if sem is not None:
            up = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in zip(times, mean + sem))
            lo = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in zip(times[::-1], (mean - sem)[::-1]))
            o.append(f'<polygon points="{up} {lo}" fill="{color}" fill-opacity="0.15" stroke="none"/>')
        pts = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in zip(times, mean))
        o.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{1.4 if dashed else 2}"'
                 + (' stroke-dasharray="5 3"' if dashed else "") + "/>")
    for i, (label, mean, _, color, dashed) in enumerate(curves):
        y = mt + 10 + i * 15
        o.append(f'<line x1="{ml + 8}" y1="{y}" x2="{ml + 26}" y2="{y}" stroke="{color}" stroke-width="2"'
                 + (' stroke-dasharray="5 3"' if dashed else "") + f'/><text x="{ml + 31}" y="{y + 4}" fill="#1f2328">{_esc(label)}</text>')
    o.append(f'<rect x="{ml}" y="{mt}" width="{W}" height="{H}" fill="none" stroke="#d0d7de"/>'
             f'<text x="{ml + W / 2}" y="{height - 6}" text-anchor="middle" fill="#1f2328">{_esc(xlabel)}</text>'
             f'<text transform="translate(14,{mt + H / 2}) rotate(-90)" text-anchor="middle" fill="#1f2328">µV</text></svg>')
    return "".join(o)


def svg_contact(contact, channels, start, xlabel, width=820):
    """One colour strip per channel: the contact level over the session."""
    rows = len(channels); ml, mr, mt, rh = 52, 12, 8, 22
    height = mt + rows * (rh + 6) + 34
    t = np.array([r["mono"] - start for r in contact]) / 60.0
    t1 = max(float(t[-1]) if t.size else 1.0, 1e-3)
    X = lambda v: ml + v / t1 * (width - ml - mr)
    o = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg" '
         f'font-family="-apple-system,Helvetica,Arial" font-size="11">']
    for k, c in enumerate(channels):
        y = mt + k * (rh + 6)
        o.append(f'<text x="{ml - 6}" y="{y + rh * 0.7:.1f}" text-anchor="end" fill="#1f2328">{_esc(c)}</text>')
        for i, r in enumerate(contact):
            lv = r["channels"].get(c, ("—",))[0]
            x0 = X(t[i]); x1 = X(t[i + 1]) if i + 1 < len(t) else X(t1)
            o.append(f'<rect x="{x0:.1f}" y="{y}" width="{max(1.0, x1 - x0):.1f}" height="{rh}" fill="{LEVEL_COLORS.get(lv, "#d0d7de")}"/>')
    yb = mt + rows * (rh + 6)
    step = _nice(t1)
    v = 0.0
    while v <= t1 + 1e-9:
        o.append(f'<text x="{X(v):.1f}" y="{yb + 12}" text-anchor="middle" fill="#57606a">{v:g}</text>'); v += step
    lx = ml
    for lv, col in LEVEL_COLORS.items():
        if lv == "—": continue
        o.append(f'<rect x="{lx}" y="{yb + 20}" width="10" height="10" fill="{col}"/><text x="{lx + 14}" y="{yb + 29}" fill="#1f2328">{lv}</text>')
        lx += 90
    o.append(f'<text x="{width - mr}" y="{yb + 29}" text-anchor="end" fill="#57606a">{_esc(xlabel)}</text></svg>')
    return "".join(o)


def svg_hist(values_ms, xlabel, ylabel, width=820, height=200, bins=30):
    v = np.asarray([x for x in values_ms if x is not None and np.isfinite(x)], dtype=float)
    if not v.size: return ""
    hi = max(1.0, float(np.percentile(v, 99.5)) * 1.05)
    counts, edges = np.histogram(np.clip(v, 0, hi), bins=bins, range=(0, hi))
    ml, mr, mt, mb = 52, 12, 10, 36
    W, H = width - ml - mr, height - mt - mb
    cmax = max(1, counts.max())
    o = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg" '
         f'font-family="-apple-system,Helvetica,Arial" font-size="11">']
    for c, a, b in zip(counts, edges[:-1], edges[1:]):
        x = ml + a / hi * W; w = (b - a) / hi * W; h = c / cmax * H
        o.append(f'<rect x="{x:.1f}" y="{mt + H - h:.1f}" width="{max(0.5, w - 1):.1f}" height="{h:.1f}" fill="#0969da" fill-opacity="0.7"/>')
    step = _nice(hi)
    x = 0.0
    while x <= hi + 1e-9:
        o.append(f'<text x="{ml + x / hi * W:.1f}" y="{mt + H + 14}" text-anchor="middle" fill="#57606a">{x:g}</text>'); x += step
    for q, col in ((50, "#1a7f37"), (95, "#9a6700")):
        pv = float(np.percentile(v, q)); px = ml + min(pv, hi) / hi * W
        o.append(f'<line x1="{px:.1f}" y1="{mt}" x2="{px:.1f}" y2="{mt + H}" stroke="{col}" stroke-dasharray="4 3"/>'
                 f'<text x="{px + 4:.1f}" y="{mt + 12}" fill="{col}">p{q} {pv:.1f}</text>')
    o.append(f'<rect x="{ml}" y="{mt}" width="{W}" height="{H}" fill="none" stroke="#d0d7de"/>'
             f'<text x="{ml + W / 2}" y="{height - 6}" text-anchor="middle" fill="#1f2328">{_esc(xlabel)}</text>'
             f'<text transform="translate(14,{mt + H / 2}) rotate(-90)" text-anchor="middle" fill="#1f2328">{_esc(ylabel)}</text></svg>')
    return "".join(o)


def _table(head, rows):
    h = "".join(f"<th>{_esc(x)}</th>" for x in head)
    b = "".join("<tr>" + "".join(f"<td>{x}</td>" for x in r) + "</tr>" for r in rows)
    return f"<table><tr>{h}</tr>{b}</table>"


def _f(v, fmt="{:+.2f}"):
    return "—" if v is None else fmt.format(v)


def _dist_row(name, d):
    return [_esc(name)] + (["—"] * 5 if not d else [d["n"], d["min"], d["median"], d["p95"], d["max"]])


# ---- the report ----------------------------------------------------------------------------------------------
def write(folder, lang="vi", window=WINDOW_S):
    """Analyse the session in ``folder`` and write report.html + erp_<signal>.csv; returns the report path."""
    L, R = T.get(lang, T["en"]), REASON_TEXT.get(lang, REASON_TEXT["en"])
    s = session.load(folder)
    cfg = s["config"]; folder = Path(folder)
    names = list(cfg["channels"])
    preset = epochs.Preset(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in cfg["preset"].items()})
    signals = [(f"{'+'.join(preset.channels)} ({preset.name})", preset)]
    signals += [(c, replace(preset, name=c, channels=(c,), combine="mean")) for c in names]
    analyses = []
    for label, pr in signals:
        try:
            res = epochs.analyse_session(s, pr, timing.fit_timeline)
        except ValueError:
            continue                                      # preset channels missing on this device
        analyses.append((label, pr, res, window_stats(res, window)))
    main = analyses[0] if analyses else None

    # summary numbers
    st = s["stimuli"]
    started = cfg.get("started_unix"); stopped = cfg.get("stopped_unix")
    dur = (stopped - started) if started and stopped else None
    contact = contact_summary(s["contact"], names)
    att = attention(s["trials"])
    qual = quality(s, main, list(preset.channels), att)
    qname = lambda k: (L["q_contact"] + k[7:]) if k.startswith("contact ") else L["q_names"].get(k, k)
    failed = [qname(k) for k, _, _, ok in qual if ok is False]
    unknown = [qname(k) for k, _, _, ok in qual if ok is None]
    parts = []
    head = [f'<b>{L["completed"] if cfg.get("completed") else L["incomplete"]}</b> ({_esc(cfg.get("stop_reason"))})',
            f'{L["mode"]}: {_esc(cfg.get("mode"))}', f'{L["duration"]}: {_f(dur, "{:.0f} s")}',
            f'{L["trials"]}: {len(s["trials"])}', f'{L["flashes"]}: {len(st)}']
    if main:
        c = main[2]["counts"]; total = len(main[2]["reasons"])
        head.append(f'{L["good_epochs"]} ({_esc(main[0])}): {c["kept"]}/{total} ({100 * c["kept"] / max(1, total):.0f} %)')
    summary = ["<p>" + " · ".join(head) + "</p>"]
    if main and main[3]["diff"] is not None:
        w = main[3]; td = np.array(w["trial_diffs"])
        summary.append(f'<p>{L["window"]} {window[0] * 1000:.0f}–{window[1] * 1000:.0f} ms · {L["diff"]} '
                       f'<b>{w["diff"]:+.2f} µV</b> · {L["valid_trials"]}: {w["n_trials"]} · '
                       f'{L["p_perm"]} {_f(w["p"], "{:.3f}")}</p>'
                       f'<p class="muted">{L["trial_range"]}: {td.min():+.2f} / {np.median(td):+.2f} / {td.max():+.2f} µV'
                       f' · {L["by_block"]}: ' + ", ".join(f"{b + 1}: {v:+.2f}" for b, v in w["block_diffs"].items())
                       + f' · {L["pooled"]}: {_f(w["diff_pooled"])} µV</p>')
    # reading order fixed before C1: measurement quality first, then ONE primary test (main signal, window, p, sign)
    n_tr = main[3]["n_trials"] if main else 0
    w0 = main[3] if main else {}
    if failed: verdict = L["verdict_fail"].format(items=", ".join(failed))
    elif 0 < n_tr <= 5: verdict = L["verdict_few"].format(n=n_tr, pmin=2 / 2 ** n_tr)     # min attainable p ≥ 0.0625
    elif w0.get("p") is not None and w0["p"] < 0.05 and w0["diff"] > 0: verdict = L["verdict_some"].format(chs=main[0])
    else: verdict = L["verdict_none"]
    summary.append(f'<p class="verdict">{_esc(verdict)}</p>')
    if not failed:
        summary.append('<p class="muted">' + _esc(L["q_overall_na"].format(items=", ".join(unknown)) if unknown
                                                    else L["q_overall_ok"]) + "</p>")
    r_eeg = np.asarray(s["eeg"]["r"], dtype=float); r_eeg = r_eeg[np.isfinite(r_eeg)]
    onsets = [x["planned_mono"] for x in st if x.get("planned_mono") is not None]
    if onsets:
        first, last = min(onsets), max(onsets)
        end = r_eeg.max() if r_eeg.size else first
        if last - end > 2.0:                             # EEG ends > 2 s before the last flash: the headset went silent
            got = 0.0 if not r_eeg.size else max(0.0, min(end, last) - max(r_eeg.min(), first))
            late = last - end
            summary.append(f'<p class="warn">⚠ {_esc(L["eeg_gap_warn"].format(got=got, need=last - first, late=late))}</p>')
    if contact:
        not_good = [1 - contact[c]["share"].get("Good", 0) for c in preset.channels if c in contact]
        if not_good and max(not_good) > 0.2:
            summary.append(f'<p class="warn">⚠ {_esc(L["contact_warn"].format(pct=100 * max(not_good)))}</p>')
    parts.append(f'<h2>{L["summary"]}</h2>' + "".join(summary))

    # measurement quality and attention
    okt = {True: f'<span style="color:#1a7f37">{L["ok_yes"]}</span>', False: f'<b class="warn">{L["ok_no"]}</b>',
           None: f'<span class="muted">{L["ok_na"]}</span>'}
    parts.append(f'<h2>{L["quality"]}</h2>' + _table([L["q_item"], L["q_value"], L["q_threshold"], L["q_ok"]],
                 [[_esc(qname(k)), _esc(v), _esc(th), okt[ok]] for k, v, th, ok in qual]))
    if att:
        at = _table([L["att_asked"], L["att_answered"], L["att_exact"], L["att_within1"]],
                    [[att["asked"], att["answered"], att["exact"], att["within1"]]])
        at += _table([L["att_trial"], L["att_reps"], L["att_answer"]],
                     [[t + 1, _f(r, "{}"), _f(a, "{}")] for t, r, a in att["rows"]])
        parts.append(f'<h2>{L["attention"]}</h2>' + at)

    # electrodes
    start_q = cfg.get("contact_at_start") or {}
    rows = []
    for c in names:
        cs = (contact or {}).get(c)
        share = " · ".join(f'<span style="color:{LEVEL_COLORS[lv]}">{lv} {100 * v:.0f} %</span>'
                           for lv, v in cs["share"].items()) if cs else "—"
        rows.append([_esc(c), f'<span style="color:{LEVEL_COLORS.get(start_q.get(c, "—"), "#57606a")}">{_esc(start_q.get(c, "—"))}</span>',
                     share, _f(cs and cs["signal"], "{:.1f} µV"), _f(cs and cs["mains"], "{:.1f} µV")])
    el = _table([L["channel"], L["at_start"], L["during"], L["sig"], L["mains"]], rows)
    if s["contact"]:
        start_mono = min(x["planned_mono"] for x in st) if st else s["contact"][0]["mono"]
        el += svg_contact(s["contact"], names, start_mono, L["session_time"])
    else:
        el += f'<p class="muted">{_esc(L["not_recorded"])}</p>'
    parts.append(f'<h2>{L["electrodes"]}</h2>' + el)

    # good epochs
    rows = []
    for label, pr, res, w in analyses:
        c = res["counts"]; total = len(res["reasons"])
        rej = ", ".join(f"{R.get(k, k)} {v}" for k, v in c.items() if k != "kept" and v) or "—"
        rows.append([_esc(label), total, f'{c["kept"]} ({100 * c["kept"] / max(1, total):.0f} %)',
                     res["erp"]["target"][2], res["erp"]["nontarget"][2], _esc(rej)])
    parts.append(f'<h2>{L["epochs"]}</h2>' + _table([L["signal"], L["total"], L["kept"], L["target"], L["nontarget"],
                                                       L["reason"]], rows))

    # ERP / P300
    erp_html, rows = [], []
    for label, pr, res, w in analyses:
        (mt, st_t, nt), (mn, st_n, nn) = res["erp"]["target"], res["erp"]["nontarget"]
        curves = [(f'{L["target"]} (n={nt})', None if mt is None else mt[0], None if st_t is None else st_t[0], TARGET, False),
                  (f'{L["nontarget"]} (n={nn})', None if mn is None else mn[0], None if st_n is None else st_n[0], NONTARGET, False)]
        if mt is not None and mn is not None: curves.append((L["diff_curve"], mt[0] - mn[0], None, DIFF, True))
        erp_html.append(f"<h3>{_esc(label)}</h3>" + svg_erp(res["times"], curves, window, L["time_s"]))
        rows.append([_esc(label), w["n_target"], w["n_nontarget"],
                     f'{_f(w["peak_amplitude"], "{:+.2f} µV")} @ '
                     f'{_f(None if w["peak_latency"] is None else w["peak_latency"] * 1000, "{:.0f} ms")}',
                     f'{_f(w["mean_target"])} / {_f(w["mean_nontarget"])} µV',
                     f'<b>{_f(w["diff"])} µV</b> (n={w["n_trials"]})',
                     ", ".join(f'{v:+.2f}' for v in w["block_diffs"].values()) or "—", f'{_f(w["diff_pooled"])} µV',
                     _f(w["p"], "{:.3f}")])
        _write_erp_csv(folder / f"erp_{_slug(label)}.csv", res)
    parts.append(f'<h2>{L["erp"]}</h2>'
                 + _table([L["signal"], f'{L["n"]} {L["target"]}', f'{L["n"]} {L["nontarget"]}', L["peak"],
                           f'{L["mean_amp"]} ({L["target"]} / {L["nontarget"]})', L["diff"], L["by_block"],
                           L["pooled"], L["p_perm"]], rows)
                 + "".join(erp_html))

    # timing deviations
    rep = {}
    tj = folder / "timing.json"
    if tj.exists():
        import json
        rep = json.loads(tj.read_text(encoding="utf-8"))
    meas, est = rep.get("measured", {}), rep.get("estimated", {})
    paint_plan = [(x.get("painted_mono") - x.get("planned_mono")) * 1000 for x in st
                  if x.get("painted_mono") is not None and x.get("planned_mono") is not None]
    tim = [_table(["", "n", "min", "median", "p95", "max"], [
        _dist_row("planned → timer (ms)", meas.get("timer_late_ms")),
        _dist_row("timer → painted (ms)", meas.get("paint_after_fire_ms")),
        _dist_row("planned → painted (ms)", meas.get("paint_after_plan_ms")),
        _dist_row("online − fit timeline (ms)", est.get("online_minus_fit_ms"))])]
    tim.append(svg_hist(paint_plan, L["paint_plan"], L["flashes_n"]))
    keys = ("missed", "no_paint")
    est_keys = ("samples", "duplicate_timestamps", "bursty_intervals", "receive_pauses", "longest_receive_interval_ms",
                "steps_back", "uncertain_samples", "segments", "rebases", "clock_steps_during_session")
    tim.append(f'<h3>{L["measured"]}</h3><p>' + " · ".join(f"{k}: {meas.get(k, '—')}" for k in keys) + "</p>")
    rate = (est.get("fit_per_segment") or [{}])[0].get("rate_hz")
    tim.append(f'<h3>{L["estimated"]}</h3><p>' + " · ".join(f"{k}: {est[k]}" for k in est_keys if k in est)
               + (f" · measured rate: {rate} Hz" if rate else "") + "</p>")
    pk = est.get("package_num_steps_not_0_or_1_during_session", est.get("package_num_anomalies_during_session"))
    if pk is not None:
        tim.append(f'<p class="muted">package_num steps ∉ {{0, 1}}: {pk} — ' + _esc(L["pkg_note"]) + "</p>")
    tim.append(f'<h3>{L["not_measured"]}</h3><p>' + " · ".join(f"{k}: {v}" for k, v in (rep.get("not_measured") or {}).items())
               + "</p>")
    parts.append(f'<h2>{L["timing"]}</h2>' + "".join(tim))

    # limits / method / files
    soa = cfg.get("schedule", {}).get("soa_s")
    rate = f"{1 / soa:g} Hz" if soa else "—"
    if lang == "vi":
        method = (f"Preset {preset.name}: {', '.join(preset.channels)} ({preset.combine}), lọc thông dải {preset.band_hz[0]}–"
                  f"{preset.band_hz[1]} Hz (bậc {preset.order}, hai chiều, theo từng khối), epoch {preset.tmin_s}…{preset.tmax_s} s, "
                  f"baseline {preset.baseline_s}, loại |biên độ| > {preset.reject_uv} µV. Onset = thời điểm Qt vẽ, đặt trên đường "
                  f"hồi quy toàn phiên của thời điểm nhận EEG. Cửa sổ P300 {window[0] * 1000:.0f}–{window[1] * 1000:.0f} ms; phép "
                  f"thử đảo dấu theo trial: mỗi trial hợp lệ (giữ ≥ {MIN_KEEP:.0%} epoch target và ≥ {MIN_KEEP:.0%} epoch non-target) "
                  f"cho một hiệu target − non-target (trung bình trong cửa sổ), đơn vị kiểm định là "
                  f"trial chứ không phải epoch (các epoch cách 400 ms chồng lên nhau). CHỈ MANG TÍNH THĂM DÒ: ít trial, nhiều tín "
                  f"hiệu được xem mà không hiệu chỉnh đa so sánh, tín hiệu và cửa sổ chưa được chốt trước, và độ trễ cố định chưa đo "
                  f"(màn hình, Bluetooth) làm dịch latency. Không dùng p này để kết luận có hay không có P300. Lịch kích thích đều "
                  f"đặn ({rate}) là MỘT giả thuyết cho dao động thấy trong ERP (đáp ứng trạng thái ổn định ở tần số đó và các hài), "
                  f"bên cạnh EEG nền, thứ tự kích thích và ảnh hưởng của lọc/baseline — chưa được kiểm chứng. Chặng A: chưa có bộ "
                  f"phân loại.")
    else:
        method = (f"Preset {preset.name}: {', '.join(preset.channels)} ({preset.combine}), band-pass {preset.band_hz[0]}–"
                  f"{preset.band_hz[1]} Hz (order {preset.order}, zero-phase, per block), epoch {preset.tmin_s}…{preset.tmax_s} s, "
                  f"baseline {preset.baseline_s}, reject |amplitude| > {preset.reject_uv} µV. Onsets = Qt paint times placed on the "
                  f"whole-session fit of the EEG receive times. P300 window {window[0] * 1000:.0f}–{window[1] * 1000:.0f} ms; "
                  f"sign-flip test over trials: one target − non-target difference (window mean) per valid trial (keeping ≥ "
                  f"{MIN_KEEP:.0%} of its target and of its non-target epochs) — the unit is the trial, "
                  f"not the epoch (epochs 400 ms apart overlap). EXPLORATORY: few trials, several signals looked at without "
                  f"correction, signal and window not fixed in advance, and a constant unmeasured delay (display, Bluetooth) "
                  f"shifts latencies. Do not use this p to conclude that a P300 is present or absent. The regular stimulation "
                  f"rate ({rate}) is ONE hypothesis for oscillations in the ERP (a steady-state response at that rate and its "
                  f"harmonics), next to background EEG, stimulus order and filter / baseline effects — not verified. Stage A: "
                  f"no classifier. "
                  + (preset.note or ""))
    files = sorted({p.name for p in folder.iterdir() if p.is_file()} | {"report.html"})
    doc = f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{_esc(L['title'])} {_esc(folder.name)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,Helvetica,Arial,sans-serif;color:#1f2328;background:#fff;max-width:900px;margin:24px auto;padding:0 16px}}
h1{{font-size:22px;margin-bottom:4px}} h2{{font-size:17px;margin-top:28px;border-bottom:1px solid #d0d7de;padding-bottom:4px}}
h3{{font-size:14px;margin:16px 0 6px}} .muted{{color:#59636e}} table{{border-collapse:collapse;font-size:12px;margin:6px 0}}
th,td{{border:1px solid #d0d7de;padding:4px 8px;text-align:left}} th{{background:#f6f8fa}}
.verdict{{font-size:15px;padding:8px 12px;background:#f6f8fa;border-left:4px solid #0969da}}
.warn{{color:#9a6700}} @media print{{body{{margin:0}} svg{{page-break-inside:avoid}}}}
</style></head><body>
<h1>{_esc(L['title'])}</h1>
<p><b>{_esc(L['subject'])}: {_esc(cfg.get('subject_id') or '—')}</b></p>
<p class="muted">{_esc(folder.name)} · {_esc(cfg.get('device', {}).get('name') or '—')} · {cfg.get('fs')} Hz · {_esc(', '.join(names))}
 · {time.strftime('%Y-%m-%d %H:%M', time.localtime(started)) if started else ''}</p>
{''.join(parts)}
<h2>{L['limits']}</h2><p class="muted">{_esc(method)}</p>
<h2>{L['files']}</h2><p class="muted">{' · '.join(_esc(x) for x in files)}</p>
</body></html>"""
    out = folder / "report.html"
    out.write_text(doc, encoding="utf-8")
    return out


def _slug(label):
    return "".join(ch if ch.isalnum() else "_" for ch in label.split(" (")[0]).strip("_").lower()


def _write_erp_csv(path, res):
    t, (mt, st, nt), (mn, sn, nn) = res["times"], res["erp"]["target"], res["erp"]["nontarget"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "target_mean_uv", "target_sem_uv", "nontarget_mean_uv", "nontarget_sem_uv", "difference_uv"])
        for i, tt in enumerate(t):
            g = lambda x: "" if x is None else f"{x[0][i]:.4f}"
            d = "" if mt is None or mn is None else f"{mt[0][i] - mn[0][i]:.4f}"
            w.writerow([f"{tt:.4f}", g(mt), g(st), g(mn), g(sn), d])
