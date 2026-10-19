"""P300 session report: self-contained HTML (hand-drawn SVG, no plotting library), written into the session folder.

Sections: summary · electrodes (at start + during the session) · good epochs · ERP / P300 per signal · timing
deviations · limits and method. Statistics are EXPLORATORY: epochs of one session are not independent, the
permutation test only shuffles target labels across kept epochs, and no correction for testing several channels is
applied. Stage A: no classifier.
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
LEVEL_COLORS = {"Good": "#1a7f37", "Fair": "#9a6700", "Bad": "#cf222e", "No signal": "#6e7781", "—": "#d0d7de"}
TARGET, NONTARGET, DIFF = "#cf222e", "#0550ae", "#57606a"

T = {
    "en": dict(
        title="P300 session report", summary="Summary", electrodes="Electrodes", epochs="Good epochs", erp="ERP and P300",
        timing="Timing deviations", limits="Limits and method", files="Files",
        completed="completed", incomplete="INCOMPLETE", mode="mode", duration="duration", trials="trials", flashes="flashes",
        good_epochs="good epochs", window="P300 window", diff="target − non-target", p_perm="p (permutation, exploratory)",
        at_start="at start", during="during the session (share of time)", sig="signal RMS (median)",
        mains="50 Hz noise (median)", not_recorded="Contact was not recorded during this session (older session).",
        channel="channel", total="total", kept="kept", target="target", nontarget="non-target", reason="reason",
        peak="target peak in window", mean_amp="mean amplitude in window", signal="signal", n="n",
        measured="Measured (software)", estimated="Estimated (EEG receive times)", not_measured="Not measured",
        verdict_none="No reliable target / non-target difference in the P300 window (exploratory test).",
        verdict_some="A target / non-target difference in the P300 window on: {chs} (exploratory — check across sessions).",
        contact_warn="Contact on the preset channels was not Good for {pct:.0f} % of the time.",
        time_s="time from onset (s)", session_time="session time (min)", paint_plan="planned → painted (ms)",
        flashes_n="flashes", subject="Subject ID",
        pkg_note="not a lost-packet count (Athena's package_num rule is unverified); data loss is judged from the "
                 "sample count against the session length (measured rate)."),
    "vi": dict(
        title="Báo cáo phiên P300", summary="Tóm tắt", electrodes="Tình trạng điện cực", epochs="Epoch đạt", erp="ERP và P300",
        timing="Độ lệch thời gian", limits="Giới hạn và phương pháp", files="Tệp",
        completed="hoàn chỉnh", incomplete="CHƯA HOÀN CHỈNH", mode="chế độ", duration="thời lượng", trials="lượt",
        flashes="lần sáng", good_epochs="epoch đạt", window="cửa sổ P300", diff="target − non-target",
        p_perm="p (hoán vị, thăm dò)", at_start="lúc bắt đầu", during="trong phiên (tỉ lệ thời gian)",
        sig="biên độ tín hiệu (trung vị)", mains="nhiễu 50 Hz (trung vị)",
        not_recorded="Phiên này không ghi chất lượng tiếp xúc trong lúc đo (phiên cũ).",
        channel="kênh", total="tổng", kept="giữ", target="target", nontarget="non-target", reason="lý do",
        peak="đỉnh target trong cửa sổ", mean_amp="biên độ trung bình trong cửa sổ", signal="tín hiệu", n="n",
        measured="Đo được (phần mềm)", estimated="Ước lượng được (thời điểm nhận EEG)", not_measured="Chưa đo được",
        verdict_none="Chưa thấy khác biệt target / non-target đáng tin trong cửa sổ P300 (kiểm định thăm dò).",
        verdict_some="Có khác biệt target / non-target trong cửa sổ P300 ở: {chs} (thăm dò — cần kiểm tra qua nhiều phiên).",
        contact_warn="Tiếp xúc ở các kênh của preset không đạt Good trong {pct:.0f} % thời gian.",
        time_s="thời gian từ onset (s)", session_time="thời gian phiên (phút)", paint_plan="lên lịch → vẽ (ms)",
        flashes_n="lần sáng", subject="Mã người tham gia",
        pkg_note="không phải số gói bị mất (quy tắc package_num của Athena chưa được xác minh); mất dữ liệu được đánh giá "
                 "bằng số mẫu so với thời lượng phiên (tần số đo được)."),
}
REASON_TEXT = {
    "en": dict(missed="timer late", no_paint="not painted", out_of_range="outside the EEG", uncertain="timing flagged",
               segment_boundary="timeline rebase", gap="gap", amplitude="amplitude"),
    "vi": dict(missed="timer trễ", no_paint="không được vẽ", out_of_range="ngoài dữ liệu EEG", uncertain="timing bị đánh dấu",
               segment_boundary="timeline tái neo", gap="đứt quãng", amplitude="biên độ lớn"),
}


# ---- statistics -------------------------------------------------------------------------------------------
def window_stats(res, window=WINDOW_S, n_perm=N_PERM, seed=0):
    """Target / non-target mean amplitude in the window, their difference, an exploratory permutation p, and the
    target peak (latency, amplitude) in the window — for the first signal of an analyse_session result."""
    keep = np.array([r is None for r in res["reasons"]]); tg = np.array(res["is_target"], bool)
    t = res["times"]; m = (t >= window[0]) & (t < window[1])
    amp = np.full(len(keep), np.nan)
    amp[keep] = res["epochs"][keep][:, 0, m].mean(axis=1)          # rejected epochs are NaN-filled: skip them
    a_t, a_n = amp[keep & tg], amp[keep & ~tg]
    out = dict(n_target=int(a_t.size), n_nontarget=int(a_n.size), mean_target=None, mean_nontarget=None,
               diff=None, p=None, peak_latency=None, peak_amplitude=None)
    if a_t.size < 2 or a_n.size < 2: return out
    diff = float(a_t.mean() - a_n.mean())
    rng = np.random.default_rng(seed); pool = np.r_[a_t, a_n]; k = a_t.size
    perm = np.array([(lambda q: q[:k].mean() - q[k:].mean())(rng.permutation(pool)) for _ in range(n_perm)])
    mean_t = res["erp"]["target"][0][0]
    i = int(np.argmax(mean_t[m])); tm = t[m]
    out.update(mean_target=float(a_t.mean()), mean_nontarget=float(a_n.mean()), diff=diff,
               p=float((np.sum(np.abs(perm) >= abs(diff)) + 1) / (n_perm + 1)),
               peak_latency=float(tm[i]), peak_amplitude=float(mean_t[m][i]))
    return out


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
    sig_chs = [lab for lab, _, _, w in analyses if w["p"] is not None and w["p"] < 0.05]
    parts = []
    head = [f'<b>{L["completed"] if cfg.get("completed") else L["incomplete"]}</b> ({_esc(cfg.get("stop_reason"))})',
            f'{L["mode"]}: {_esc(cfg.get("mode"))}', f'{L["duration"]}: {_f(dur, "{:.0f} s")}',
            f'{L["trials"]}: {len(s["trials"])}', f'{L["flashes"]}: {len(st)}']
    if main:
        c = main[2]["counts"]; total = len(main[2]["reasons"])
        head.append(f'{L["good_epochs"]} ({_esc(main[0])}): {c["kept"]}/{total} ({100 * c["kept"] / max(1, total):.0f} %)')
    summary = ["<p>" + " · ".join(head) + "</p>"]
    if main and main[3]["diff"] is not None:
        w = main[3]
        summary.append(f'<p>{L["window"]} {window[0] * 1000:.0f}–{window[1] * 1000:.0f} ms · {L["diff"]} '
                       f'<b>{w["diff"]:+.2f} µV</b> · {L["p_perm"]} {w["p"]:.3f}</p>')
    summary.append(f'<p class="verdict">{_esc(L["verdict_some"].format(chs=", ".join(sig_chs)) if sig_chs else L["verdict_none"])}</p>')
    if contact:
        not_good = [1 - contact[c]["share"].get("Good", 0) for c in preset.channels if c in contact]
        if not_good and max(not_good) > 0.2:
            summary.append(f'<p class="warn">⚠ {_esc(L["contact_warn"].format(pct=100 * max(not_good)))}</p>')
    parts.append(f'<h2>{L["summary"]}</h2>' + "".join(summary))

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
        if mt is not None and mn is not None: curves.append((L["diff"], mt[0] - mn[0], None, DIFF, True))
        erp_html.append(f"<h3>{_esc(label)}</h3>" + svg_erp(res["times"], curves, window, L["time_s"]))
        rows.append([_esc(label), w["n_target"], w["n_nontarget"],
                     f'{_f(w["peak_amplitude"], "{:+.2f} µV")} @ '
                     f'{_f(None if w["peak_latency"] is None else w["peak_latency"] * 1000, "{:.0f} ms")}',
                     f'{_f(w["mean_target"])} / {_f(w["mean_nontarget"])} µV', f'<b>{_f(w["diff"])} µV</b>',
                     _f(w["p"], "{:.3f}")])
        _write_erp_csv(folder / f"erp_{_slug(label)}.csv", res)
    parts.append(f'<h2>{L["erp"]}</h2>'
                 + _table([L["signal"], f'{L["n"]} {L["target"]}', f'{L["n"]} {L["nontarget"]}', L["peak"],
                           f'{L["mean_amp"]} ({L["target"]} / {L["nontarget"]})', L["diff"], L["p_perm"]], rows)
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
                  f"thử hoán vị: xáo nhãn target {N_PERM} lần trên các epoch đạt. CHỈ MANG TÍNH THĂM DÒ: các epoch trong một phiên "
                  f"không độc lập, nhiều tín hiệu được kiểm định mà không hiệu chỉnh, và độ trễ cố định chưa đo (màn hình, "
                  f"Bluetooth) làm dịch latency. Lịch kích thích đều đặn ({rate}) có thể tạo đáp ứng trạng thái ổn định ở tần số "
                  f"đó và các hài của nó, chồng lên ERP. Chặng A: chưa có bộ phân loại.")
    else:
        method = (f"Preset {preset.name}: {', '.join(preset.channels)} ({preset.combine}), band-pass {preset.band_hz[0]}–"
                  f"{preset.band_hz[1]} Hz (order {preset.order}, zero-phase, per block), epoch {preset.tmin_s}…{preset.tmax_s} s, "
                  f"baseline {preset.baseline_s}, reject |amplitude| > {preset.reject_uv} µV. Onsets = Qt paint times placed on the "
                  f"whole-session fit of the EEG receive times. P300 window {window[0] * 1000:.0f}–{window[1] * 1000:.0f} ms; "
                  f"permutation test: target labels shuffled {N_PERM}× across kept epochs. EXPLORATORY: epochs of one session "
                  f"are not independent, several signals are tested without correction, and a constant unmeasured delay "
                  f"(display, Bluetooth) shifts latencies. The regular stimulation rate ({rate}) can evoke a steady-state "
                  f"response at that rate and its harmonics, superimposed on the ERP. Stage A: no classifier. "
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
