"""Event marker lines (Space key) on every time-based plot."""
import pyqtgraph as pg
from PySide6 import QtCore


class EventMarkers:
    def __init__(self, ctx):
        self.ctx = ctx
        self.events = []                 # [(t_wall, label, [(InfiniteLine, MarkerTarget), ...])]

    def __len__(self):
        return len(self.events)

    def add(self, t, label):
        lines = []
        for tg in self.ctx.plots.marker_targets:
            line = pg.InfiniteLine(angle=90, movable=False, label=label if tg.show_label else None,
                                   labelOpts=dict(position=0.92))
            line.setVisible(False)
            self._style(line, tg)
            tg.plot.addItem(line); lines.append((line, tg))
        self.events.append((t, label, lines))
        self.place()

    def place(self, max_age_sec=None):
        """Place x = t_event − time_ref(stream) — same time frame as the signal curves; drop events that are too old."""
        st = self.ctx.store
        refs = {k: st.time_ref(k) for k in st.last_ts}
        newest = max((v for v in st.last_ts.values() if v is not None), default=None)
        keep = []
        for t, label, lines in self.events:
            if max_age_sec and newest is not None and t < newest - max_age_sec:
                self._remove(lines); continue
            keep.append((t, label, lines))
            for line, tg in lines:
                ref = refs[tg.stream]
                if ref is None: continue
                line.setPos(t - ref); line.setVisible(True)
        self.events = keep

    def forget_plots(self, plots):
        """Drop marker lines on plots that were removed (unloaded extension tab)."""
        self.events = [(t, label, [(ln, tg) for ln, tg in lines if tg.plot not in plots])
                       for t, label, lines in self.events]

    def clear(self):
        for _, _, lines in self.events: self._remove(lines)
        self.events = []

    def apply_theme(self):
        for _, _, lines in self.events:
            for line, tg in lines: self._style(line, tg)

    def _style(self, line, tg):
        th = self.ctx.th
        c = th["event_img"] if tg.on_image else th["event"]      # stands out on a colormap
        line.setPen(pg.mkPen(c, width=2 if tg.on_image else 1.5, style=QtCore.Qt.DashLine))
        if getattr(line, "label", None) is not None:
            line.label.setColor(c); line.label.fill = pg.mkBrush(th["bg"]); line.label.update()

    @staticmethod
    def _remove(lines):
        for line, _ in lines:
            if line.scene(): line.scene().removeItem(line)
