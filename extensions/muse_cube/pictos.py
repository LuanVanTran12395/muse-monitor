"""Animated pictograms of the calibration / tilt-test movements, drawn with QPainter (no image files).

A front-facing head on shoulders, seen as in a MIRROR (your left is on the screen's left, as head_motion_plus's 3D
head): it turns, looks up, tilts, nods, blinks or clenches; an arrow shows the movement. During "get ready" the
movement is demonstrated in a loop; during "now" the pose to hold is shown (blinks and clenches keep looping, since
they are the movement). Skin and hair colours as head_motion_plus's head.
"""
import math

from PySide6 import QtCore, QtGui

SKIN, HAIR, SHIRT = (214, 162, 125), (58, 40, 30), (70, 86, 120)
ACCENT = QtGui.QColor(143, 163, 255)
LOOP_S = {"blink": 2.0, "jaw": 2.4, "nod": 1.6}


def _ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def pose(kind, a, hold=False):
    """(yaw°, pitch°, roll°, eyes closed 0..1, clench 0..1) at loop phase ``a`` (0..1). hold: the target pose.
    yaw > 0 = turned to the screen's left (your left, in a mirror); roll > 0 = tilted to the screen's right."""
    # demonstration: go out (0–0.35), hold (0.35–0.7), come back (0.7–0.9), rest
    out = 1.0 if hold else _ease(a / 0.35) if a < 0.35 else 1.0 if a < 0.7 else 1 - _ease((a - 0.7) / 0.2)
    yaw = pitch = roll = 0.0
    eyes = clench = 0.0
    if kind == "left": yaw = 35 * out
    elif kind == "point_left": yaw = 14 * out
    elif kind == "point_right": yaw = -14 * out
    elif kind == "up": pitch = 24 * out
    elif kind in ("tilt", "right"): roll = 24 * out
    elif kind == "left_tilt": roll = -24 * out
    elif kind == "nod": pitch = -12 * math.sin(2 * math.pi * 2 * a) * (1 if a < 0.6 else 0)
    elif kind == "blink":                        # two quick blinks, then a pause
        eyes = 1.0 if (0.10 < a < 0.18 or 0.28 < a < 0.36) else 0.0
    elif kind == "jaw":
        clench = _ease((a - 0.15) / 0.1) if a < 0.6 else 1 - _ease((a - 0.6) / 0.1)
        clench = clench if 0.15 < a < 0.7 else 0.0
    return yaw, pitch, roll, eyes, clench


def _col(rgb, k=1.0, alpha=255):
    return QtGui.QColor(*(max(0, min(255, int(c * k))) for c in rgb), alpha)


def draw(p, rect, kind, now, hold=False):
    """Draw the pictogram of ``kind`` in ``rect`` at time ``now`` (seconds)."""
    period = LOOP_S.get(kind, 2.6)
    a = (now % period) / period
    yaw, pitch, roll, eyes, clench = pose(kind, a, hold=hold and kind not in ("blink", "jaw", "nod"))
    s = min(rect.width(), rect.height())
    cx, cy = rect.center().x(), rect.center().y() + s * 0.04
    r = s * 0.24                                 # head radius
    p.save()
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    # backdrop disc
    p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(30, 36, 50)); p.drawEllipse(QtCore.QPointF(cx, cy), s * 0.47, s * 0.47)
    # shoulders (they stay still: only the head moves)
    sh = QtGui.QPainterPath()
    base_y = cy + r * 1.9
    sh.moveTo(cx - r * 1.9, base_y); sh.cubicTo(cx - r * 1.8, cy + r * 1.05, cx - r * 0.6, cy + r * 1.0, cx, cy + r * 1.0)
    sh.cubicTo(cx + r * 0.6, cy + r * 1.0, cx + r * 1.8, cy + r * 1.05, cx + r * 1.9, base_y); sh.closeSubpath()
    p.setBrush(_col(SHIRT)); p.drawPath(sh)
    # head: rotate (roll) about the neck
    neck = QtCore.QPointF(cx, cy + r * 0.95)
    p.translate(neck); p.rotate(roll); p.translate(-neck)
    p.setBrush(_col(SKIN, 0.85)); p.drawRect(QtCore.QRectF(cx - r * 0.28, cy + r * 0.55, r * 0.56, r * 0.5))     # neck
    sy, sp = math.sin(math.radians(yaw)), math.sin(math.radians(pitch))
    hx, hy = cx - sy * r * 0.15, cy - sp * r * 0.1                    # the skull shifts a little
    fx, fy = hx - sy * r * 0.75, hy - sp * r * 0.75                   # the face (features) shifts a lot: easy to read
    squeeze = math.cos(math.radians(yaw)) ** 1.5
    # ears: the far one hides as the head turns
    for side in (-1, 1):
        vis = 1.0 - max(0.0, side * sy) * 1.6
        if vis <= 0.05: continue
        ex = hx + side * r * 0.98 * squeeze - sy * r * 0.15
        p.setBrush(_col(SKIN, 0.9)); p.drawEllipse(QtCore.QPointF(ex, hy + r * 0.05), r * 0.16 * vis, r * 0.26)
    p.setBrush(_col(SKIN)); p.drawEllipse(QtCore.QPointF(hx, hy), r * (0.88 + 0.12 * squeeze), r * 1.12)
    if pitch > 3:                                                      # looking up: the underside of the chin shows
        p.setBrush(_col(SKIN, 0.78))
        p.drawEllipse(QtCore.QPointF(hx, hy + r * 0.95), r * 0.55, r * 0.22 * min(1.0, pitch / 20))
    # hair cap
    hair = QtGui.QPainterPath()
    hair.moveTo(hx - r, hy - r * 0.05)
    hair.cubicTo(hx - r * 1.02, hy - r * 1.35, hx + r * 1.02, hy - r * 1.35, hx + r, hy - r * 0.05)
    hair.cubicTo(hx + r * 0.7, hy - r * 0.62 - sp * r * 0.3, hx - r * 0.7, hy - r * 0.62 - sp * r * 0.3, hx - r, hy - r * 0.05)
    p.setBrush(_col(HAIR)); p.drawPath(hair)
    # eyes
    eye_dx, eye_y = r * 0.36 * squeeze, fy - r * 0.08
    for side in (-1, 1):
        ex = fx + side * eye_dx
        if eyes > 0.5:
            p.setPen(QtGui.QPen(_col(HAIR), r * 0.07, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)); p.setBrush(QtCore.Qt.NoBrush)
            p.drawArc(QtCore.QRectF(ex - r * 0.15, eye_y - r * 0.08, r * 0.3, r * 0.16), 200 * 16, 140 * 16)
        else:
            p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(250, 250, 250))
            p.drawEllipse(QtCore.QPointF(ex, eye_y), r * 0.15 * squeeze + r * 0.02, r * 0.1)
            p.setBrush(_col(HAIR)); p.drawEllipse(QtCore.QPointF(ex - sy * r * 0.05, eye_y - sp * r * 0.02), r * 0.065, r * 0.065)
    # nose: points the way the head turns (a profile wedge when turned)
    p.setPen(QtCore.Qt.NoPen); p.setBrush(_col(SKIN, 0.8))
    tip = QtCore.QPointF(fx - sy * r * 0.32, fy + r * 0.2 - sp * r * 0.1)
    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(fx - r * 0.04, fy - r * 0.02), tip, QtCore.QPointF(fx + r * 0.06, fy + r * 0.24)]))
    # mouth / teeth
    my = fy + r * 0.48
    if clench > 0.05:
        w = r * 0.5 * squeeze
        p.setPen(QtGui.QPen(_col(HAIR, 0.8), r * 0.04)); p.setBrush(QtGui.QColor(245, 245, 240))
        p.drawRoundedRect(QtCore.QRectF(fx - w / 2, my - r * 0.1, w, r * 0.2), r * 0.05, r * 0.05)
        p.drawLine(QtCore.QPointF(fx - w / 2, my), QtCore.QPointF(fx + w / 2, my))
        for k in range(1, 4):
            x = fx - w / 2 + w * k / 4; p.drawLine(QtCore.QPointF(x, my - r * 0.1), QtCore.QPointF(x, my + r * 0.1))
        # tense jaw muscles at the temples
        p.setPen(QtGui.QPen(ACCENT, r * 0.06, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        for side in (-1, 1):
            for k in range(3):
                x = hx + side * (r * 1.12 + k * r * 0.13)
                p.drawLine(QtCore.QPointF(x, my - r * 0.25 + k * r * 0.04), QtCore.QPointF(x + side * r * 0.08, my - r * 0.05))
    else:
        p.setPen(QtGui.QPen(_col(SKIN, 0.55), r * 0.06, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)); p.setBrush(QtCore.Qt.NoBrush)
        p.drawArc(QtCore.QRectF(fx - r * 0.22 * squeeze, my - r * 0.1, r * 0.44 * squeeze, r * 0.16), 200 * 16, 140 * 16)
    p.restore()
    _arrow(p, kind, cx, cy, r, s, now)


def _arrow(p, kind, cx, cy, r, s, now):
    """The movement, as an arrow / marks in the accent colour."""
    p.save(); p.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(ACCENT, max(2.0, s * 0.018), QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
    p.setPen(pen); p.setBrush(QtCore.Qt.NoBrush)

    def head_at(x, y, ang):
        p.save(); p.translate(x, y); p.rotate(ang); p.setBrush(ACCENT); p.setPen(QtCore.Qt.NoPen)
        k = s * 0.035
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(k, 0), QtCore.QPointF(-k, -k * 0.8), QtCore.QPointF(-k, k * 0.8)]))
        p.restore()

    if kind in ("left", "point_left", "point_right"):
        d = -1 if kind != "point_right" else 1                      # screen direction
        y = cy - r * 1.55
        path = QtGui.QPainterPath(); path.moveTo(cx - d * r * 0.7, y + r * 0.15)
        path.quadTo(cx, y - r * 0.25, cx + d * r * 0.9, y + r * 0.15); p.drawPath(path)
        head_at(cx + d * r * 0.9, y + r * 0.15, 30 if d > 0 else 150)
    elif kind == "up":
        x = cx + r * 1.55
        p.drawLine(QtCore.QPointF(x, cy + r * 0.4), QtCore.QPointF(x, cy - r * 0.6)); head_at(x, cy - r * 0.6, -90)
    elif kind in ("tilt", "right", "left_tilt"):
        d = 1 if kind != "left_tilt" else -1                        # 1: the top of the head goes to the screen's right
        R, ccy = r * 1.6, cy + r * 0.1                              # an arc over the head, about the neck
        p.drawArc(QtCore.QRectF(cx - R, ccy - R, 2 * R, 2 * R), 90 * 16, -d * 50 * 16)
        th = math.radians(90 - d * 50)                              # the arc's end; tangent along the movement
        tx, ty = (math.sin(th), math.cos(th)) if d > 0 else (-math.sin(th), -math.cos(th))
        head_at(cx + R * math.cos(th), ccy - R * math.sin(th), math.degrees(math.atan2(ty, tx)))
    elif kind == "nod":
        x = cx + r * 1.55
        p.drawLine(QtCore.QPointF(x, cy - r * 0.5), QtCore.QPointF(x, cy + r * 0.5))
        head_at(x, cy - r * 0.5, -90); head_at(x, cy + r * 0.5, 90)
    elif kind == "centre":
        k = 1 + 0.08 * math.sin(now * 4)
        p.drawEllipse(QtCore.QPointF(cx, cy - r * 0.05), r * 1.45 * k, r * 1.45 * k)
        for ang in range(0, 360, 90):
            a = math.radians(ang)
            p.drawLine(QtCore.QPointF(cx + math.cos(a) * r * 1.3 * k, cy - r * 0.05 + math.sin(a) * r * 1.3 * k),
                       QtCore.QPointF(cx + math.cos(a) * r * 1.65 * k, cy - r * 0.05 + math.sin(a) * r * 1.65 * k))
    elif kind == "neutral":
        p.setPen(QtGui.QPen(ACCENT, max(1.5, s * 0.012), QtCore.Qt.DashLine))
        p.drawLine(QtCore.QPointF(cx, cy - r * 1.75), QtCore.QPointF(cx, cy + r * 2.1))
    elif kind in ("blink", "jaw"):
        f = QtGui.QFont(); f.setBold(True); f.setPointSizeF(max(8.0, s * 0.07)); p.setFont(f)
        p.drawText(QtCore.QRectF(cx + r * 0.9, cy - r * 1.75, r * 1.4, r * 0.6), QtCore.Qt.AlignCenter,
                   "×2" if kind == "blink" else "1 s")
    p.restore()
