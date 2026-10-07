"""App Qt style: Fusion + a custom checkbox indicator.

Fusion centres the 14×14 indicator on the widget height with integer division, while the label is centred on
the whole line box (ascent + descent) → on macOS the box sits ~0.8 px above the cap-height centre; in the Dark
theme the box border nearly matches the background, so the tick looks floating/offset (measured from a user video, 2026-10-06).
Only two things change here: the vertical position of the box (cap-height centre) and how the box + tick are drawn
(centred, border from the palette). Widget size and hit area are unchanged.
"""
from PySide6 import QtCore, QtGui, QtWidgets

QStyle = QtWidgets.QStyle


def _mix(a, b, t):
    return QtGui.QColor.fromRgbF(*(a.getRgbF()[i] * (1 - t) + b.getRgbF()[i] * t for i in range(3)))


class AppStyle(QtWidgets.QProxyStyle):
    def __init__(self):
        super().__init__("Fusion")

    def subElementRect(self, element, option, widget=None):
        r = super().subElementRect(element, option, widget)
        if element == QStyle.SE_CheckBoxIndicator and option.text:
            # Shift the box so its centre matches the label's cap-height centre (label is AlignVCenter on the line box)
            fm = option.fontMetrics
            h = option.rect.height()
            baseline = option.rect.top() + (h - fm.height()) / 2 + fm.ascent()
            cap_center = baseline - fm.capHeight() / 2
            dy = round(cap_center - (r.top() + r.height() / 2))
            dy = max(option.rect.top() - r.top(), min(dy, option.rect.bottom() - r.bottom()))  # stay inside the widget
            r.translate(0, dy)
        return r

    def drawControl(self, element, option, painter, widget=None):
        # QCommonStyle draws CE_CheckBox with its own subElementRect (not through the proxy) → redraw it
        # in the original order (box → label → focus frame) so the adjusted box position above is used.
        if element != QStyle.CE_CheckBox or not isinstance(option, QtWidgets.QStyleOptionButton):
            return super().drawControl(element, option, painter, widget)
        sub = QtWidgets.QStyleOptionButton(option)
        sub.rect = self.subElementRect(QStyle.SE_CheckBoxIndicator, option, widget)
        self.drawPrimitive(QStyle.PE_IndicatorCheckBox, sub, painter, widget)
        sub.rect = self.subElementRect(QStyle.SE_CheckBoxContents, option, widget)
        self.drawControl(QStyle.CE_CheckBoxLabel, sub, painter, widget)
        if option.state & QStyle.State_HasFocus:
            fr = QtWidgets.QStyleOptionFocusRect()
            fr.state, fr.palette, fr.direction = option.state, option.palette, option.direction
            fr.fontMetrics, fr.backgroundColor = option.fontMetrics, option.palette.window().color()
            fr.rect = self.subElementRect(QStyle.SE_CheckBoxFocusRect, option, widget)
            self.drawPrimitive(QStyle.PE_FrameFocusRect, fr, painter, widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        if element != QStyle.PE_IndicatorCheckBox:
            return super().drawPrimitive(element, option, painter, widget)
        pal, st = option.palette, option.state
        group = QtGui.QPalette.Normal if st & QStyle.State_Enabled else QtGui.QPalette.Disabled
        base = pal.color(group, QtGui.QPalette.Base)
        text = pal.color(group, QtGui.QPalette.Text)
        hl = pal.color(group, QtGui.QPalette.Highlight)
        r = QtCore.QRectF(option.rect).adjusted(0.5, 0.5, -0.5, -0.5)
        s = min(r.width(), r.height())
        r = QtCore.QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s)        # square, centred
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        fill = _mix(base, hl, 0.25) if st & QStyle.State_Sunken else base
        border = _mix(base, text, 0.45)                       # enough contrast in both Dark and Light
        painter.setPen(QtGui.QPen(border, 1.0)); painter.setBrush(fill)
        painter.drawRoundedRect(r, 2.5, 2.5)
        pen = QtGui.QPen(text, max(1.5, s * 0.13), QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
        painter.setPen(pen); painter.setBrush(QtCore.Qt.NoBrush)
        p = lambda fx, fy: QtCore.QPointF(r.left() + fx * s, r.top() + fy * s)
        if st & QStyle.State_NoChange:                                                  # tristate
            painter.drawLine(p(0.28, 0.5), p(0.72, 0.5))
        elif st & QStyle.State_On:
            # tick bounding box: x 0.24–0.76, y 0.30–0.70 → centre (0.5, 0.5) matches the box centre
            painter.drawPolyline(QtGui.QPolygonF([p(0.24, 0.52), p(0.42, 0.70), p(0.76, 0.30)]))
        painter.restore()


def apply_app_style(app):
    app.setStyle(AppStyle())
