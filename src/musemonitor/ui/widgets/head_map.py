from PySide6 import QtCore, QtGui, QtWidgets

from ..theme import THEMES, DEFAULT_THEME


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

    def set_quality(self, q):
        self.q = q; self.update()

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
        for name, (ux, uy) in self.pos.items():
            if name not in self.q: continue
            c = QtGui.QColor(self.colors[self.q[name]])
            x, y = cx + ux * r, cy + uy * r * 1.1
            p.setPen(QtGui.QPen(c.darker(140), 2)); p.setBrush(c)
            p.drawEllipse(QtCore.QPointF(x, y), er, er)
            p.setPen(QtGui.QColor("white"))
            p.drawText(QtCore.QRectF(x - er, y - er, 2 * er, 2 * er), QtCore.Qt.AlignCenter, name)
            p.setPen(c)
            p.drawText(QtCore.QRectF(x - er * 2, y + er, er * 4, er * 1.3), QtCore.Qt.AlignCenter, self.q[name])
        p.end()
