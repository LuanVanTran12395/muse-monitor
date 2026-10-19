"""Line pictograms for the participant instructions (QPainter only, no image files).

Style: one light stroke colour on black, the same yellow as the target outline for the one thing that matters, no
fills that compete with the text. Every function draws inside ``rect`` (a QRectF) and keeps its aspect ratio.
"""
import math

from PySide6 import QtCore, QtGui

INK, MUTED, ACCENT, DIM, LIT = "#e6e6e6", "#8c8c8c", "#e3b341", "#4a4a4a", "#ffffff"


def _pen(color=INK, width=3.0):
    pen = QtGui.QPen(QtGui.QColor(color), width)
    pen.setCapStyle(QtCore.Qt.RoundCap); pen.setJoinStyle(QtCore.Qt.RoundJoin)
    return pen


def _square(rect):
    s = min(rect.width(), rect.height())
    return QtCore.QRectF(rect.center().x() - s / 2, rect.center().y() - s / 2, s, s)


def grid(p, rect, target=1, lit=None, ring=True):
    """Small 3 × 3 grid of discs; ``target`` outlined in yellow, ``lit`` white."""
    r = _square(rect); step = r.width() / 3
    for cell in range(9):
        row, col = divmod(cell, 3)
        c = QtCore.QPointF(r.left() + (col + 0.5) * step, r.top() + (row + 0.5) * step)
        rad = step * 0.22
        p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(LIT if cell == lit else DIM)); p.drawEllipse(c, rad, rad)
        if ring and cell == target:
            p.setPen(_pen(ACCENT, max(2.5, step * 0.05))); p.setBrush(QtCore.Qt.NoBrush)
            p.drawEllipse(c, rad * 1.5, rad * 1.5)


def eye(p, rect, closed=False, color=INK):
    r = _square(rect); w, h = r.width(), r.width() * 0.55
    box = QtCore.QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h)
    p.setPen(_pen(color, max(2.5, w * 0.05))); p.setBrush(QtCore.Qt.NoBrush)
    path = QtGui.QPainterPath()
    path.moveTo(box.left(), box.center().y())
    path.quadTo(box.center().x(), box.top() - h * 0.35, box.right(), box.center().y())
    if closed:
        p.drawPath(path); return
    path.quadTo(box.center().x(), box.bottom() + h * 0.35, box.left(), box.center().y())
    p.drawPath(path)
    p.setBrush(QtGui.QColor(color)); p.drawEllipse(box.center(), h * 0.28, h * 0.28)


def session(p, rect):
    """A clock and two blocks of trials with a break between them."""
    r = rect
    clock = QtCore.QRectF(r.left(), r.top() + r.height() * 0.15, r.height() * 0.7, r.height() * 0.7)
    p.setPen(_pen(INK, 3.5)); p.setBrush(QtCore.Qt.NoBrush); p.drawEllipse(clock)
    c = clock.center()
    p.drawLine(c, QtCore.QPointF(c.x(), clock.top() + clock.height() * 0.22))
    p.drawLine(c, QtCore.QPointF(clock.right() - clock.width() * 0.25, c.y()))
    x = clock.right() + r.height() * 0.3
    bw = (r.right() - x - r.height() * 0.35) / 2
    for b in range(2):
        box = QtCore.QRectF(x + b * (bw + r.height() * 0.35), r.top() + r.height() * 0.3, bw, r.height() * 0.4)
        p.setPen(_pen(MUTED, 2.5)); p.setBrush(QtCore.Qt.NoBrush); p.drawRoundedRect(box, 10, 10)
        for k in range(5):
            cx = box.left() + (k + 0.5) * box.width() / 5
            p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(ACCENT if k == 2 else DIM))
            p.drawEllipse(QtCore.QPointF(cx, box.center().y()), box.height() * 0.17, box.height() * 0.17)
    gap = x + bw + r.height() * 0.175
    p.setPen(_pen(MUTED, 3)); p.drawLine(QtCore.QPointF(gap - 5, r.center().y() - 10), QtCore.QPointF(gap - 5, r.center().y() + 10))
    p.drawLine(QtCore.QPointF(gap + 5, r.center().y() - 10), QtCore.QPointF(gap + 5, r.center().y() + 10))


def task(p, rect):
    """Eye → outlined target in the grid, and the counting."""
    r = rect; h = r.height()
    eye(p, QtCore.QRectF(r.left(), r.top() + h * 0.2, h * 0.6, h * 0.6))
    arrow_y = r.center().y()
    x0, x1 = r.left() + h * 0.7, r.left() + h * 1.05
    p.setPen(_pen(MUTED, 3)); p.drawLine(QtCore.QPointF(x0, arrow_y), QtCore.QPointF(x1, arrow_y))
    p.drawLine(QtCore.QPointF(x1, arrow_y), QtCore.QPointF(x1 - 10, arrow_y - 8))
    p.drawLine(QtCore.QPointF(x1, arrow_y), QtCore.QPointF(x1 - 10, arrow_y + 8))
    grid(p, QtCore.QRectF(r.left() + h * 1.15, r.top(), h, h), target=4, lit=4)
    bubble = QtCore.QRectF(r.left() + h * 2.3, r.top() + h * 0.28, h * 0.95, h * 0.44)
    p.setPen(_pen(INK, 3)); p.setBrush(QtCore.Qt.NoBrush); p.drawRoundedRect(bubble, 14, 14)
    f = p.font(); f.setPointSizeF(h * 0.16); f.setBold(True); p.setFont(f)
    p.drawText(bubble, QtCore.Qt.AlignCenter, "1, 2, 3…")


def still(p, rect):
    """Head and shoulders, centred: sit still."""
    r = _square(rect)
    p.setPen(_pen(INK, max(2.5, r.width() * 0.05))); p.setBrush(QtCore.Qt.NoBrush)
    p.drawEllipse(QtCore.QPointF(r.center().x(), r.top() + r.height() * 0.33), r.width() * 0.17, r.width() * 0.2)
    p.drawArc(QtCore.QRectF(r.left() + r.width() * 0.15, r.top() + r.height() * 0.58, r.width() * 0.7, r.height() * 0.7),
              0, 180 * 16)


def blink(p, rect):
    """Eye with a stroke through it: do not blink while cells flash."""
    eye(p, rect)
    r = _square(rect)
    p.setPen(_pen(ACCENT, max(3.0, r.width() * 0.06)))
    p.drawLine(QtCore.QPointF(r.left() + r.width() * 0.12, r.bottom() - r.height() * 0.2),
               QtCore.QPointF(r.right() - r.width() * 0.12, r.top() + r.height() * 0.2))


def gaze(p, rect):
    """Eye looking at the outlined target."""
    r = _square(rect)
    eye(p, QtCore.QRectF(r.left(), r.top() + r.height() * 0.25, r.width() * 0.5, r.height() * 0.5))
    c = QtCore.QPointF(r.right() - r.width() * 0.18, r.center().y())
    p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(DIM)); p.drawEllipse(c, r.width() * 0.1, r.width() * 0.1)
    p.setPen(_pen(ACCENT, max(2.5, r.width() * 0.04))); p.setBrush(QtCore.Qt.NoBrush)
    p.drawEllipse(c, r.width() * 0.15, r.width() * 0.15)
    pen = _pen(MUTED, 2.5); pen.setStyle(QtCore.Qt.DotLine); p.setPen(pen)
    p.drawLine(QtCore.QPointF(r.left() + r.width() * 0.52, r.center().y()), QtCore.QPointF(c.x() - r.width() * 0.18, c.y()))


def count(p, rect):
    r = _square(rect)
    p.setPen(_pen(INK, max(2.5, r.width() * 0.045))); p.setBrush(QtCore.Qt.NoBrush)
    box = QtCore.QRectF(r.left() + r.width() * 0.05, r.top() + r.height() * 0.22, r.width() * 0.9, r.height() * 0.5)
    p.drawRoundedRect(box, r.width() * 0.12, r.width() * 0.12)
    tail = QtGui.QPolygonF([QtCore.QPointF(box.left() + box.width() * 0.25, box.bottom()),
                            QtCore.QPointF(box.left() + box.width() * 0.2, box.bottom() + r.height() * 0.18),
                            QtCore.QPointF(box.left() + box.width() * 0.42, box.bottom())])
    p.drawPolyline(tail)
    f = p.font(); f.setPointSizeF(r.height() * 0.2); f.setBold(True); p.setFont(f)
    p.drawText(box, QtCore.Qt.AlignCenter, "1 2 3")


def pause(p, rect, color=INK):
    r = _square(rect)
    p.setPen(_pen(color, max(3.0, r.width() * 0.05))); p.setBrush(QtCore.Qt.NoBrush)
    p.drawEllipse(r.adjusted(r.width() * 0.08, r.width() * 0.08, -r.width() * 0.08, -r.width() * 0.08))
    p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(color))
    bw, bh = r.width() * 0.1, r.height() * 0.34
    for dx in (-0.12, 0.12):
        p.drawRoundedRect(QtCore.QRectF(r.center().x() + dx * r.width() - bw / 2, r.center().y() - bh / 2, bw, bh), 3, 3)


def breaks(p, rect):
    r = rect; h = r.height()
    pause(p, QtCore.QRectF(r.center().x() - h * 1.1, r.top(), h, h))
    still(p, QtCore.QRectF(r.center().x() + h * 0.1, r.top(), h, h))


def ready(p, rect, label="Space"):
    """A large Space key and a start triangle."""
    r = rect; h = r.height()
    key = QtCore.QRectF(r.center().x() - h * 1.6, r.top() + h * 0.2, h * 2.4, h * 0.6)
    keycap(p, key, label, size=h * 0.2)
    tri_c = QtCore.QPointF(key.right() + h * 0.6, key.center().y())
    p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(ACCENT))
    s = h * 0.24
    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(tri_c.x() - s * 0.6, tri_c.y() - s),
                                   QtCore.QPointF(tri_c.x() - s * 0.6, tri_c.y() + s),
                                   QtCore.QPointF(tri_c.x() + s, tri_c.y())]))


def keycap(p, rect, label, size=None, enabled=True):
    """A keyboard key: rounded, with a slightly darker bottom edge, label centred."""
    color = QtGui.QColor(INK if enabled else DIM)
    p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor("#101010" if enabled else "#0a0a0a"))
    p.drawRoundedRect(rect.translated(0, 4), 12, 12)
    p.setBrush(QtGui.QColor("#262626" if enabled else "#141414")); p.setPen(_pen(color.name(), 2.5))
    p.drawRoundedRect(rect, 12, 12)
    f = p.font(); f.setPointSizeF(size or rect.height() * 0.42); f.setBold(True); p.setFont(f)
    p.setPen(color); p.drawText(rect, QtCore.Qt.AlignCenter, label)


def mouse(p, rect, enabled=True):
    r = _square(rect)
    body = QtCore.QRectF(r.center().x() - r.width() * 0.28, r.top() + r.height() * 0.05, r.width() * 0.56, r.height() * 0.9)
    color = INK if enabled else DIM
    p.setPen(_pen(color, max(2.5, r.width() * 0.05))); p.setBrush(QtCore.Qt.NoBrush)
    p.drawRoundedRect(body, body.width() * 0.48, body.width() * 0.48)
    p.drawLine(QtCore.QPointF(body.center().x(), body.top()), QtCore.QPointF(body.center().x(), body.top() + body.height() * 0.35))
    p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(ACCENT if enabled else DIM))
    left = QtGui.QPainterPath(); left.addRoundedRect(QtCore.QRectF(body.left() + 3, body.top() + 3, body.width() / 2 - 4,
                                                                    body.height() * 0.33), 8, 8)
    p.drawPath(left)


ICONS = dict(session=session, task=task, still=still, blink=blink, gaze=gaze, count=count, breaks=breaks, ready=ready)


def ring(p, center, radius, fraction, color=ACCENT):
    """Progress ring (countdown): ``fraction`` of the circle drawn, clockwise from the top."""
    p.setPen(_pen(DIM, radius * 0.07)); p.setBrush(QtCore.Qt.NoBrush)
    p.drawEllipse(center, radius, radius)
    p.setPen(_pen(color, radius * 0.07))
    box = QtCore.QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
    p.drawArc(box, 90 * 16, -int(360 * 16 * max(0.0, min(1.0, fraction))))
