from PySide6 import QtCore, QtGui, QtWidgets

from ..theme import THEMES, DEFAULT_THEME, text_on


class HeadWidget(QtWidgets.QWidget):
    """Top-down head diagram (nose up), Muse electrodes coloured by contact quality."""
    POS = {"AF7": (-0.38, -0.62), "AF8": (0.38, -0.62), "TP9": (-0.92, 0.18), "TP10": (0.92, 0.18)}

    def __init__(self, channel_names, positions=None):
        """positions: {electrode name: (x, y)} for other devices, merged into POS."""
        super().__init__()
        self.pos = {**self.POS, **(positions or {})}
        self.q = {n: "—" for n in channel_names}
        self.colors = THEMES[DEFAULT_THEME]["q"]
        self.setMinimumSize(320, 340)
        self.setAccessibleName("Electrode contact map")

    def set_quality(self, q):
        self.q = q; self.update()
        self.setAccessibleDescription("Contact: " + ", ".join(f"{n} {lvl}" for n, lvl in q.items()))

    def set_colors(self, colors):
        self.colors = colors; self.update()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = min(w, h) * 0.36; cx, cy = w / 2, h / 2 + r * 0.08
        fg = self.palette().color(QtGui.QPalette.WindowText)
        pen = QtGui.QPen(fg); pen.setWidthF(2); p.setPen(pen); p.setBrush(QtCore.Qt.NoBrush)
        p.drawEllipse(QtCore.QPointF(cx, cy), r, r * 1.1)                       # head
        nose = QtGui.QPolygonF([QtCore.QPointF(cx - r * .12, cy - r * 1.08),
                                QtCore.QPointF(cx, cy - r * 1.28), QtCore.QPointF(cx + r * .12, cy - r * 1.08)])
        p.drawPolyline(nose)                                                        # nose
        for sx in (-1, 1):                                                          # tai
            p.drawEllipse(QtCore.QPointF(cx + sx * r * 1.04, cy), r * .1, r * .22)
        er = r * 0.17
        f = p.font(); f.setBold(True); f.setPointSizeF(max(9, er * 0.42)); p.setFont(f)
        fm = QtGui.QFontMetricsF(f)
        window = self.palette().color(QtGui.QPalette.Window)
        for name, (ux, uy) in self.pos.items():
            if name not in self.q: continue
            fill = self.colors[self.q[name]]
            c = QtGui.QColor(fill)
            x, y = cx + ux * r, cy + uy * r * 1.1
            p.setPen(QtGui.QPen(c.darker(140), 2)); p.setBrush(c)
            p.drawEllipse(QtCore.QPointF(x, y), er, er)
            p.setPen(QtGui.QColor(text_on(fill)))                  # white or dark, whichever reads on this fill
            p.drawText(QtCore.QRectF(x - er, y - er, 2 * er, 2 * er), QtCore.Qt.AlignCenter, name)
            # level below the electrode on a window-coloured pill, so the head outline does not run through it
            text = self.q[name]
            w, h = fm.horizontalAdvance(text) + er * 0.6, fm.height() + er * 0.2
            pill = QtCore.QRectF(x - w / 2, y + er * 1.12, w, h)
            p.setPen(QtCore.Qt.NoPen); p.setBrush(window)
            p.drawRoundedRect(pill, h / 2, h / 2)
            p.setPen(c)
            p.drawText(pill, QtCore.Qt.AlignCenter, text)
        p.end()
