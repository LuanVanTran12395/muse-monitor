"""HTML strings for indicators used on several pages (channel quality, battery)."""
from ... import config as C


def quality_html(name, q, th):
    """q = (level, band RMS, mains RMS) or None when there is no data yet."""
    if q is None:
        level, txt = "—", "&nbsp;<br>&nbsp;"
    else:
        level, b, l = q
        txt = f"signal {b:.0f} µV<br>{C.NOTCH_HZ:.0f} Hz noise {l:.0f} µV"    # RMS in BAND_HZ / around mains
    c = th["q"][level]
    return (f"<span style='color:{c};font-size:16pt'>●</span> <b>{name}</b><br>"
            f"<span style='color:{c}'>{level}</span><br>"
            f"<span style='color:{th['muted']};font-size:9pt'>{txt}</span>")


def quality_summary(names, qs):
    """'Contact: TP9 Good, AF7 Fair, …' — the plot's accessible description (plots are invisible to screen readers)."""
    return "Contact: " + ", ".join(f"{n} {qs[i][0] if qs else 'not measured'}" for i, n in enumerate(names))


def fill_quality_labels(labels, names, qs, th):
    """Update the pyqtgraph LabelItems shown at the start of each channel."""
    for i, lab in enumerate(labels):
        lab.setText(quality_html(names[i], qs[i] if qs else None, th), color=th["fg"])


def battery_html(pct, th):
    if pct is None: return "🔋 —"
    q = th["q"]
    c = q["Good"] if pct > 50 else (q["Fair"] if pct > 20 else q["Bad"])
    return f"🔋 <span style='color:{c}'><b>{pct:.0f}%</b></span>"
