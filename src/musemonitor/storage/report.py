"""End-of-session report: self-contained HTML (hand-drawn SVG charts, no plotting library) + psd_*.csv."""
import csv
import html
import math
import time

import numpy as np

from .. import config as C
from ..core.spectral import band_powers

COLORS = ["#0550ae", "#1a7f37", "#bc4c00", "#8250df", "#cf222e", "#0969da", "#9a6700", "#57606a",
          "#116329", "#953800", "#6639ba", "#a40e26", "#0a3069", "#4d2d00", "#1b7c83", "#7d4e00"]


# ---- SVG charts ---------------------------------------------------------------------
def _nice_step(span, target=8):
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


def svg_psd(f, ys, names, fmax, ylabel, shade=None, width=820, height=300, colors=COLORS):
    """PSD lines on a log y axis. ys: [n_ch, n_f]. shade: (lo, hi, label) to highlight a band."""
    outside = len(names) > 6                       # many channels → legend in the right margin, off the curves
    per_col = 12
    ml, mr, mt, mb = 64, (12 + 64 * math.ceil(len(names) / per_col)) if outside else 12, 12, 40
    W, H = width - ml - mr, height - mt - mb
    keep = (f > 0) & (f <= fmax)
    f, ys = f[keep], np.asarray(ys)[:, keep]
    pos = ys[ys > 0]
    if not len(pos): return "<p><i>No data.</i></p>"
    lo = math.floor(math.log10(np.percentile(pos, 0.5)))
    hi = math.ceil(math.log10(pos.max()))
    lo = max(lo, hi - 8); hi = max(hi, lo + 1)
    X = lambda v: ml + v / fmax * W
    Y = lambda v: mt + (hi - math.log10(max(v, 10.0 ** lo))) / (hi - lo) * H
    o = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg" '
         f'font-family="-apple-system,Helvetica,Arial" font-size="11">']
    if shade:
        a, b, lab = shade
        o.append(f'<rect x="{X(a):.1f}" y="{mt}" width="{X(b) - X(a):.1f}" height="{H}" fill="#fff8c5"/>'
                 f'<text x="{(X(a) + X(b)) / 2:.1f}" y="{mt + 12}" text-anchor="middle" fill="#9a6700">{lab}</text>')
    step = _nice_step(fmax)
    for k in range(int(fmax / step) + 1):
        v = k * step; x = X(v)
        o.append(f'<line x1="{x:.1f}" y1="{mt}" x2="{x:.1f}" y2="{mt + H}" stroke="#eaeef2"/>'
                 f'<text x="{x:.1f}" y="{mt + H + 14}" text-anchor="middle" fill="#57606a">{v:g}</text>')
    for e in range(lo, hi + 1):
        y = mt + (hi - e) / (hi - lo) * H
        o.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{ml + W}" y2="{y:.1f}" stroke="#eaeef2"/>'
                 f'<text x="{ml - 6}" y="{y + 4:.1f}" text-anchor="end" fill="#57606a">1e{e}</text>')
    o.append(f'<rect x="{ml}" y="{mt}" width="{W}" height="{H}" fill="none" stroke="#d0d7de"/>')
    o.append(f'<text x="{ml + W / 2}" y="{height - 6}" text-anchor="middle" fill="#1f2328">Frequency (Hz)</text>'
             f'<text transform="translate(14,{mt + H / 2}) rotate(-90)" text-anchor="middle" fill="#1f2328">{html.escape(ylabel)}</text>')
    for i, y in enumerate(ys):
        pts = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in zip(f, y))
        o.append(f'<polyline points="{pts}" fill="none" stroke="{colors[i % len(colors)]}" stroke-width="1.4"/>')
    lx = ml + W + 12 if outside else ml + 8
    rows = per_col if outside else 8
    for i, n in enumerate(names):
        c = colors[i % len(colors)]
        dx, y = (i // rows) * 64, mt + 6 + (i % rows) * 14
        o.append(f'<rect x="{lx + dx}" y="{y}" width="10" height="3" fill="{c}"/>'
                 f'<text x="{lx + dx + 14}" y="{y + 4}" fill="#1f2328">{html.escape(n)}</text>')
    o.append("</svg>")
    return "".join(o)


# ---- content ------------------------------------------------------------------------
def _write_psd_csv(path, f, psd, names):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["frequency_hz"] + list(names))
        w.writerows(np.column_stack([f, psd.T]).tolist())


def _table(head, rows):
    th = "".join(f"<th>{html.escape(str(h))}</th>" for h in head)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>"


def _peak(f, p, lo, hi):
    m = (f >= lo) & (f <= hi)
    return float(f[m][np.argmax(p[m])]) if m.any() else float("nan")


def _fmt_t(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) + f".{int((t % 1) * 1000):03d}"


def write_report(session, health):
    sp, folder = session.spec, session.folder
    dur = (session.ended or time.time()) - session.started
    parts, files = [], []
    names = {"eeg": sp.eeg.names, "opt": sp.optics.names, "imu": sp.imu.names}
    csv_name = {"eeg": "psd_eeg.csv", "opt": "psd_optics.csv", "imu": "psd_imu.csv"}
    results = {k: a.result() for k, a in session.acc.items()}
    for k, r in results.items():
        if r is not None:
            _write_psd_csv(folder / csv_name[k], r[0], r[1], names[k]); files.append(csv_name[k])

    # Summary
    rows = []
    for k, label in (("eeg", "EEG"), ("opt", "Optics / PPG"), ("imu", "IMU")):
        if k not in session.acc: continue
        a, h = session.acc[k], health.get(k, {})
        fs_meas = h.get("effective_fs")
        rows.append([label, f"{a.total:,}", f"{a.fs} Hz", f"{fs_meas:.2f} Hz" if fs_meas else "—",
                     h.get("backsteps", "—"), h.get("seq_anomalies", "—"),
                     f"{results[k][2]} × {a.nperseg / a.fs:g} s" if results[k] else "not enough data"])
    parts.append("<h2>Session</h2>" + _table(
        ["Stream", "Samples", "Nominal rate", "Measured rate", "Timestamp backsteps", "package_num steps ∉ {0,1}",
         "Welch segments"], rows))

    # Event
    ev = session.events
    parts.append("<h2>Events</h2>" + (_table(["#", "Time", "t − start (s)", "Label"],
                                              [[i + 1, _fmt_t(t), f"{t - session.started:.3f}", html.escape(l)]
                                               for i, (t, l) in enumerate(ev)]) if ev else "<p>None.</p>"))

    # EEG
    r = results.get("eeg")
    if r is not None:
        f, p, _ = r
        parts.append("<h2>EEG power spectral density</h2>"
                     + svg_psd(f, p, names["eeg"], min(C.REPORT_EEG_FMAX, sp.eeg.fs / 2), "PSD (µV²/Hz)",
                               shade=(8, 13, "alpha")))
        bp = band_powers(f, p, C.REPORT_BANDS)
        total = sum(bp.values())
        head = ["Channel"] + [f"{b} {lo}–{hi} Hz" for b, (lo, hi) in C.REPORT_BANDS.items()] + ["Alpha peak"]
        rows = []
        for i, n in enumerate(names["eeg"]):
            cells = [f"{bp[b][i]:.1f} µV² <span class='muted'>({bp[b][i] / total[i] * 100:.0f}%)</span>"
                     if total[i] > 0 else "—" for b in C.REPORT_BANDS]
            rows.append([f"<b>{html.escape(n)}</b>"] + cells + [f"{_peak(f, p[i], 7, 14):.2f} Hz"])
        parts.append("<h3>Band power (absolute, % of 1–45 Hz)</h3>" + _table(head, rows))

    # Optics
    r = results.get("opt")
    if r is not None:
        f, p, _ = r
        parts.append("<h2>Optics / PPG power spectral density</h2>"
                     "<p class='muted'>Raw optical intensity per channel (mean removed per segment). "
                     "The peak in 0.7–3 Hz is the cardiac pulse.</p>"
                     + svg_psd(f, p, names["opt"], min(5.0, sp.optics.fs / 2), "PSD (counts²/Hz)", shade=(0.7, 3, "heart")))
        rows = [[html.escape(n), f"{_peak(f, p[i], 0.7, 3.0):.3f} Hz", f"{_peak(f, p[i], 0.7, 3.0) * 60:.0f} bpm"]
                for i, n in enumerate(names["opt"])]
        parts.append("<h3>Dominant cardiac peak per channel</h3>" + _table(["Channel", "Peak", "≈ HR"], rows))

    # IMU
    r = results.get("imu")
    if r is not None:
        f, p, _ = r
        na = sp.n_acc
        parts.append("<h2>IMU power spectral density</h2>"
                     + "<h3>Accelerometer</h3>" + svg_psd(f, p[:na], names["imu"][:na], sp.imu.fs / 2, "PSD (g²/Hz)")
                     + "<h3>Gyroscope</h3>" + svg_psd(f, p[na:], names["imu"][na:], sp.imu.fs / 2, "PSD ((°/s)²/Hz)"))

    method = ("Welch method on the <b>raw</b> recorded signals (no band-pass or notch filter), Hann window, "
              "50% overlap, mean removed per segment, one-sided density. Segment length: "
              + ", ".join(f"{k} {v:g} s" for k, v in C.REPORT_PSD_SEG_SEC.items())
              + ". PSD is accumulated from the samples the app received during recording; it can differ from "
                "the CSV by the few samples recorded before the first / after the last update (≤ one poll, ~20 ms).")
    files = sorted(p.name for p in folder.iterdir() if p.is_file() and p.name != "report.html") + ["report.html"]
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>Muse session {session.stamp}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,Helvetica,Arial,sans-serif;color:#1f2328;background:#fff;max-width:900px;margin:24px auto;padding:0 16px}}
h1{{font-size:22px;margin-bottom:4px}} h2{{font-size:17px;margin-top:28px;border-bottom:1px solid #d0d7de;padding-bottom:4px}}
h3{{font-size:14px;margin:16px 0 6px}} .muted{{color:#59636e}} table{{border-collapse:collapse;font-size:12px;margin:6px 0}}
th,td{{border:1px solid #d0d7de;padding:4px 8px;text-align:left}} th{{background:#f6f8fa}}
@media print{{body{{margin:0}}}}
</style></head><body>
<h1>Muse Monitor — session report</h1>
<p class="muted">{html.escape(folder.name)} · device {html.escape(session.device or '—')} ·
{_fmt_t(session.started)} → {_fmt_t(session.ended or time.time())} · duration {dur:.1f} s</p>
{''.join(parts)}
<h2>Method</h2><p class="muted">{method}</p>
<h2>Files</h2><p class="muted">{' · '.join(html.escape(x) for x in files)}</p>
</body></html>"""
    out = folder / "report.html"
    out.write_text(doc, encoding="utf-8")
    return out
