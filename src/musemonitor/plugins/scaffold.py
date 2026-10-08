"""Create a new extension skeleton from a template, and suggest where it appears in the menu bar."""
import re
from pathlib import Path

from .api import CATEGORIES, category_of, menu_location

# words in an extension's name → suggested category (first match wins, checked in this order)
KEYWORDS = (
    ("Eyes", ("eye", "blink", "gaze", "glance", "saccade", "wink")),
    ("Motion", ("head", "imu", "motion", "gyro", "accel", "posture", "nod", "tilt")),
    ("Heart & optics", ("heart", "hrv", "ppg", "pulse", "fnirs", "oxygen", "hbo", "breath", "optic")),
    ("Data quality", ("artifact", "artefact", "quality", "noise", "contact", "impedance", "clean")),
    ("EEG", ("eeg", "alpha", "beta", "theta", "delta", "gamma", "band", "psd", "spectr", "asymmetry", "erp", "focus", "calm")),
)

TEMPLATE = '''"""{name} — extension for Muse Monitor.

Put this folder in extensions/ (or ~/.musemonitor/extensions) and restart the app.
API docs: docs/EXTENSIONS.md
"""
import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets

from musemonitor.plugins.api import BaseTab, Extension


class {cls}Tab(BaseTab):
    """Tab shown on the Recording screen. Create plots via ctx.plots.plot(...) so they follow
    the theme and time range and show event markers."""
    title = "{name}"

    def __init__(self, ctx):
        super().__init__(ctx)
        v = QtWidgets.QVBoxLayout(self)
        self.info = ctx.plots.muted_label("Waiting for data…", wrap=False)
        v.addWidget(self.info)
        pw = ctx.plots.widget(pg.PlotWidget())
        self.plot = ctx.plots.plot(pw.getPlotItem(), marker="eeg")
        self.plot.setLabel("left", "Mean EEG (µV)"); self.plot.setLabel("bottom", "Time", units="s")
        self.curve = self.plot.plot()
        v.addWidget(pw, 1)

    def on_analysis(self):                 # ~4 times/s while the tab is visible
        st, fs = self.ctx.store, self.ctx.spec.eeg.fs
        n = min(st.eeg_f.n, int(self.ctx.window_sec * fs))
        if n < 2: return
        y = st.eeg_display(n).mean(axis=0)
        self.curve.setData((np.arange(n) - n) / fs, y)
        self.info.setText(f"{{n}} samples · RMS {{y.std():.1f}} µV")

    def apply_theme(self, th):
        self.curve.setPen(pg.mkPen(th["eeg"][0], width=1.5))

    def clear(self):
        self.curve.clear()


class {cls}(Extension):
    id = "{slug}"
    name = "{name}"
    version = "0.1.0"
    description = "Describe what this extension does."
    # Menu placement of its panel (tab): {location}.
    # One of: {categories}
    category = "{category}"

    def activate(self, app):
        app.add_tab({cls}Tab)                 # hidden until ticked in the menu above
        app.add_action("Mark test event", lambda: app.mark_event("{slug} test"))   # Extensions ▸ {name} ▸ …

    # Uncomment the hooks you need — hooks that are not overridden are never called.
    # def on_eeg(self, x, ts): ...
    # def on_event(self, t, label): ...
    # def on_recording_started(self, path): ...
    # def on_recording_stopped(self): ...
    # def deactivate(self): ...


EXTENSION = {cls}
'''


def slugify(name):
    s = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower()).strip("_")
    if not s: raise ValueError("extension name must contain letters or digits")
    return s if not s[0].isdigit() else f"ext_{s}"


def suggest_category(name):
    """Category suggested from words in the extension's name (e.g. "Alpha Peak" → EEG), else "Other"."""
    words = name.lower()
    for category, keys in KEYWORDS:
        if any(k in words for k in keys): return category
    return "Other"


def placement(name, category):
    """Lines telling where a new extension will appear."""
    return [f"Its panel will appear in:   {menu_location(category)} ▸ {name.strip()}   (hidden until ticked)",
            f"Its actions will appear in: Extensions ▸ {name.strip()} ▸ …"]


def create_extension(name, dest_dir, category=None):
    """Create <dest_dir>/<slug>/__init__.py; return the folder path. Never overwrites an existing one.
    category: a key of CATEGORIES; None = suggested from the name."""
    if category is not None and category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r} — choose one of: {', '.join(CATEGORIES)}")
    category = category_of(category or suggest_category(name))
    slug = slugify(name)
    cls = "".join(p.capitalize() for p in slug.split("_")) or "My"
    folder = Path(dest_dir) / slug
    if folder.exists(): raise FileExistsError(f"{folder} already exists")
    folder.mkdir(parents=True)
    (folder / "__init__.py").write_text(TEMPLATE.format(
        name=name.strip(), slug=slug, cls=cls, category=category, location=menu_location(category),
        categories=", ".join(CATEGORIES)), encoding="utf-8")
    return folder
