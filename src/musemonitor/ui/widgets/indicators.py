"""HTML strings for indicators used on several pages (channel quality, battery)."""


def quality_html(name, q, th):
    """q = (level, band RMS, 50 Hz RMS) or None when there is no data yet."""
    if q is None:
        level, txt = "—", "&nbsp;"
    else:
        level, b, l = q; txt = f"{b:.0f} µV · 50Hz {l:.0f}"
    c = th["q"][level]
    return (f"<span style='color:{c};font-size:16pt'>●</span> <b>{name}</b><br>"
            f"<span style='color:{c}'>{level}</span><br>"
            f"<span style='color:{th['muted']};font-size:8pt'>{txt}</span>")


def fill_quality_labels(labels, names, qs, th):
    """Update the pyqtgraph LabelItems shown at the start of each channel."""
    for i, lab in enumerate(labels):
        lab.setText(quality_html(names[i], qs[i] if qs else None, th), color=th["fg"])


def battery_html(pct, th):
    if pct is None: return "🔋 —"
    q = th["q"]
    c = q["Good"] if pct > 50 else (q["Fair"] if pct > 20 else q["Bad"])
    return f"🔋 <span style='color:{c}'><b>{pct:.0f}%</b></span>"
