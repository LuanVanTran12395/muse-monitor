"""Muse Bistro — the ordering kiosk window (Qt, hand-drawn, no image files). It draws a view dict and forwards keys;
the extension owns the state (order.Order), the gestures and the camera.

Layout (the same on every screen, so the eye knows where to look):
    top bar     brand · category segmented control · signal states · user
    heading     title + what to do here (left) · page dots (right)
    centre      three cards — the pointed one is lifted, outlined and labelled "↕ Gật để chọn" · head-direction track
    bottom      a floating dock: mode · the gestures usable now
    side        with the camera on ("demo layout"): the camera image, the 3D head and the eyes in a right column;
                otherwise the head and eyes sit above the dock, bottom-right
    overlays    toast · details / cart sheets · confirmation popup · ● REC while a demo video is recorded
"""
import math

from PySide6 import QtCore, QtGui, QtWidgets

from . import menu
from .text import t as _t

BG_TOP, BG_BOTTOM = "#FBF7F2", "#F3EAE0"
SURFACE, INK, MUTED, LINE, DOCK = "#FFFFFF", "#1F1A17", "#8A7F77", "#ECE3D9", "#1F1A17"
GOOD, WARN, OFF, REC = "#2F9E5B", "#E9952B", "#A39990", "#E5484D"
TINT = {"Pizza": "#FDE7DF", "Burger": "#FDEFD9", "Drink": "#DDF3F0", "Dessert": "#FBE3EE", "Giỏ": "#E7E7FB"}


def _pen(c, w):
    q = QtGui.QPen(QtGui.QColor(c), w); q.setCapStyle(QtCore.Qt.RoundCap); q.setJoinStyle(QtCore.Qt.RoundJoin)
    return q


def _alpha(c, a):
    q = QtGui.QColor(c); q.setAlpha(a); return q


def food_art(p, kind, c, r, top="#D9472B"):
    """Flat illustrations with soft shading, no image files."""
    p.save(); p.setPen(QtCore.Qt.NoPen)
    shadow = QtGui.QRadialGradient(QtCore.QPointF(c.x(), c.y() + r * 0.95), r * 1.0)
    shadow.setColorAt(0, QtGui.QColor(60, 30, 10, 60)); shadow.setColorAt(1, QtGui.QColor(60, 30, 10, 0))
    p.setBrush(shadow); p.drawEllipse(QtCore.QPointF(c.x(), c.y() + r * 0.95), r * 0.95, r * 0.22)
    if kind == "pizza":
        g = QtGui.QRadialGradient(QtCore.QPointF(c.x() - r * 0.3, c.y() - r * 0.3), r * 1.4)
        g.setColorAt(0, QtGui.QColor("#F6C866")); g.setColorAt(1, QtGui.QColor("#D9922E"))
        p.setBrush(g); p.drawEllipse(c, r, r)
        g2 = QtGui.QRadialGradient(QtCore.QPointF(c.x() - r * 0.2, c.y() - r * 0.25), r)
        g2.setColorAt(0, QtGui.QColor("#FFE7A3")); g2.setColorAt(1, QtGui.QColor("#F4C65E"))
        p.setBrush(g2); p.drawEllipse(c, r * 0.84, r * 0.84)
        for a in range(0, 360, 60):
            q = QtCore.QPointF(c.x() + r * 0.5 * math.cos(math.radians(a + 20)), c.y() + r * 0.5 * math.sin(math.radians(a + 20)))
            p.setBrush(QtGui.QColor(top or "#D9472B")); p.drawEllipse(q, r * 0.14, r * 0.14)
            p.setBrush(QtGui.QColor(255, 255, 255, 70)); p.drawEllipse(q - QtCore.QPointF(r * 0.04, r * 0.04), r * 0.05, r * 0.05)
        p.setBrush(QtGui.QColor("#4E8B3A"))
        for a in (60, 200, 320):
            p.drawEllipse(QtCore.QPointF(c.x() + r * 0.25 * math.cos(math.radians(a)), c.y() + r * 0.25 * math.sin(math.radians(a))), r * 0.07, r * 0.045)
        p.setPen(_pen(_alpha("#C98B2E", 140), max(1.2, r * 0.025)))
        for a in range(0, 360, 60):
            p.drawLine(c, QtCore.QPointF(c.x() + r * 0.84 * math.cos(math.radians(a)), c.y() + r * 0.84 * math.sin(math.radians(a))))
    elif kind == "burger":
        w = r * 1.9; x0 = c.x() - w / 2
        bun = QtGui.QLinearGradient(0, c.y() - r * 0.95, 0, c.y() - r * 0.3)
        bun.setColorAt(0, QtGui.QColor("#F2B866")); bun.setColorAt(1, QtGui.QColor("#D98E3A"))
        p.setBrush(bun); p.drawChord(QtCore.QRectF(x0, c.y() - r * 0.95, w, r * 1.3), 0, 180 * 16)
        p.setBrush(QtGui.QColor("#FFF3D6"))
        for dx, dy in ((-0.4, -0.62), (0.0, -0.75), (0.38, -0.6), (-0.15, -0.5), (0.2, -0.45)):
            p.drawEllipse(QtCore.QPointF(c.x() + r * dx, c.y() + r * dy), r * 0.05, r * 0.03)
        p.setBrush(QtGui.QColor("#5AA346")); p.drawRoundedRect(QtCore.QRectF(x0 - r * 0.06, c.y() - r * 0.32, w + r * 0.12, r * 0.16), 8, 8)
        p.setBrush(QtGui.QColor("#F4C430")); p.drawRect(QtCore.QRectF(x0 + r * 0.05, c.y() - r * 0.17, w - r * 0.1, r * 0.12))
        meat = QtGui.QLinearGradient(0, c.y() - r * 0.05, 0, c.y() + r * 0.26)
        meat.setColorAt(0, QtGui.QColor("#7A4429")); meat.setColorAt(1, QtGui.QColor("#4E2A18"))
        p.setBrush(meat); p.drawRoundedRect(QtCore.QRectF(x0, c.y() - r * 0.05, w, r * 0.31), 10, 10)
        p.setBrush(bun); p.drawRoundedRect(QtCore.QRectF(x0, c.y() + r * 0.3, w, r * 0.38), 14, 14)
    elif kind == "drink":
        path = QtGui.QPainterPath(QtCore.QPointF(c.x() - r * 0.6, c.y() - r * 0.7))
        path.lineTo(c.x() + r * 0.6, c.y() - r * 0.7); path.lineTo(c.x() + r * 0.45, c.y() + r * 0.9)
        path.lineTo(c.x() - r * 0.45, c.y() + r * 0.9); path.closeSubpath()
        g = QtGui.QLinearGradient(0, c.y() - r * 0.7, 0, c.y() + r * 0.9)
        base = QtGui.QColor(top or "#F6B26B")
        g.setColorAt(0, base.lighter(120)); g.setColorAt(1, base.darker(110))
        p.setBrush(g); p.drawPath(path)
        p.setBrush(QtGui.QColor(255, 255, 255, 120))
        for dx, dy in ((-0.2, -0.3), (0.15, -0.1), (-0.05, 0.25)):
            p.drawRoundedRect(QtCore.QRectF(c.x() + r * dx - r * 0.12, c.y() + r * dy - r * 0.12, r * 0.24, r * 0.24), 4, 4)
        p.setBrush(QtGui.QColor(255, 255, 255, 60))
        p.drawRect(QtCore.QRectF(c.x() - r * 0.5, c.y() - r * 0.66, r * 0.12, r * 1.4))
        p.setPen(_pen("#1FA39A", max(2.0, r * 0.07)))
        p.drawLine(QtCore.QPointF(c.x() + r * 0.15, c.y() - r * 0.7), QtCore.QPointF(c.x() + r * 0.4, c.y() - r * 1.1))
    elif kind == "dessert":
        g = QtGui.QLinearGradient(0, c.y() - r * 0.2, 0, c.y() + r * 0.7)
        g.setColorAt(0, QtGui.QColor("#F7DDAA")); g.setColorAt(1, QtGui.QColor("#E9BF7A"))
        p.setBrush(g); p.drawRoundedRect(QtCore.QRectF(c.x() - r * 0.8, c.y() - r * 0.2, r * 1.6, r * 0.9), 18, 18)
        p.setBrush(QtGui.QColor("#8C4F27")); p.drawRoundedRect(QtCore.QRectF(c.x() - r * 0.8, c.y() - r * 0.35, r * 1.6, r * 0.3), 14, 14)
        p.setBrush(QtGui.QColor(top or "#D9578F")); p.drawEllipse(QtCore.QPointF(c.x(), c.y() - r * 0.52), r * 0.17, r * 0.17)
        p.setBrush(QtGui.QColor(255, 255, 255, 110)); p.drawEllipse(QtCore.QPointF(c.x() - r * 0.05, c.y() - r * 0.57), r * 0.05, r * 0.05)
    elif kind == "cart":
        p.setPen(_pen(INK, max(3.0, r * 0.09))); p.setBrush(QtCore.Qt.NoBrush)
        p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(c.x() - r * 0.8, c.y() - r * 0.6), QtCore.QPointF(c.x() - r * 0.55, c.y() - r * 0.6),
                                        QtCore.QPointF(c.x() - r * 0.3, c.y() + r * 0.3), QtCore.QPointF(c.x() + r * 0.6, c.y() + r * 0.3),
                                        QtCore.QPointF(c.x() + r * 0.75, c.y() - r * 0.35), QtCore.QPointF(c.x() - r * 0.45, c.y() - r * 0.35)]))
        for dx in (-0.2, 0.45): p.drawEllipse(QtCore.QPointF(c.x() + r * dx, c.y() + r * 0.6), r * 0.1, r * 0.1)
    p.restore()


class KioskWindow(QtWidgets.QWidget):
    AVATAR_W = (260, 130)                       # head (its caption needs the width), eyes
    SIDE_W = 380                                # demo layout: right column width (camera, head, eyes)

    def __init__(self, on_key, on_closed, on_login, on_click=None):
        super().__init__()
        self.on_key, self.on_closed, self.on_login, self.on_click = on_key, on_closed, on_login, on_click
        self.setWindowTitle("Muse Bistro — đặt món bằng đầu và mắt (demo)")
        self.resize(1280, 800)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.view = dict(mode="order", screen="login", cards=[], focus=1)
        self.avatars = []
        self.camera_image = None                # QImage (mirrored) while the camera runs → demo layout
        self.camera_caption = ""
        self.recording = None                   # seconds recorded while a demo video is written
        self.hits = []                          # (rect, action) of every control, as last painted — clicks use these
        self.setMinimumSize(1024, 700)          # below this the dock and cards get too small to read and to hit
        self.edit = QtWidgets.QLineEdit(self)
        self.edit.setPlaceholderText("Mã khách hàng, ví dụ M01"); self.edit.setAlignment(QtCore.Qt.AlignCenter)
        self.edit.setAccessibleName("Mã khách hàng")
        self.edit.returnPressed.connect(self._submit_login)
        self._swallow_enter = False
        self.edit.textEdited.connect(self._clean)
        self.edit.hide()

    # ---- widgets reused from the other extensions --------------------------------------------------------------
    def set_avatars(self, widgets):
        """Live views: head_motion_plus.HeadCanvas and eye_interaction.EyeCanvas."""
        self.avatars = []
        for wdg in widgets:
            if wdg is None: continue
            wdg.setParent(self); wdg.setMinimumSize(10, 10); wdg.show(); self.avatars.append(wdg)
        self._place()

    def set_camera(self, image, caption=""):
        """Camera frame (QImage) or None; switches the demo layout on / off."""
        was = self.camera_image is not None
        self.camera_image, self.camera_caption = image, caption
        if was != (image is not None): self._place()
        self.update()

    def demo(self):
        return self.camera_image is not None

    def _side(self):
        """The demo column (x, width) or None."""
        if not self.demo(): return None
        u = self._unit(); sw = self.SIDE_W * u
        return self.width() - sw - 20 * u, sw

    def content_right(self):
        side = self._side()
        return side[0] - 16 * self._unit() if side else self.width()

    def _camera_rect(self):
        u = self._unit(); x, sw = self._side()
        return QtCore.QRectF(x, 96 * u, sw, sw * 0.75)

    def _place(self):
        u = self._unit()
        side = self._side()
        if side:                                                    # head and eyes under the camera
            cam = self._camera_rect()
            y = cam.bottom() + 14 * u
            widths = (side[1] * 0.64, side[1] * 0.36 - 10 * u)
            x = side[0]
            for wdg, w in zip(self.avatars, widths):
                wdg.setGeometry(int(x), int(y), int(w), int(124 * u)); x += w + 10 * u
                self._round(wdg, w, 124 * u)
        else:
            x = self.width() - 20 * u
            y = self.height() - self._dock_h() - 22 * u - 112 * u
            for wdg, base in zip(reversed(self.avatars), reversed(self.AVATAR_W[:len(self.avatars)])):
                w, h = base * u, 104 * u
                x -= w; wdg.setGeometry(int(x), int(y), int(w), int(h)); x -= 10 * u
                self._round(wdg, w, h)
        if self.edit.isVisible():
            f = QtGui.QFont(self.font()); f.setPointSizeF(24 * u); f.setBold(True); self.edit.setFont(f)
            w = 520 * u
            self.edit.setGeometry(int((self.content_right() - w) / 2), int(214 * u), int(w), int(68 * u))
            self.edit.setStyleSheet(f"QLineEdit{{background:{SURFACE};color:{INK};border:2px solid {LINE};"
                                    f"border-radius:{int(34 * u)}px;padding:4px 24px}}"
                                    f"QLineEdit:focus{{border:2px solid {menu.ACCENT['Pizza']}}}")

    def _round(self, wdg, w, h):
        path = QtGui.QPainterPath(); path.addRoundedRect(QtCore.QRectF(0, 0, w, h), 16 * self._unit(), 16 * self._unit())
        wdg.setMask(QtGui.QRegion(path.toFillPolygon().toPolygon()))

    def avatars_left(self):
        if self.demo(): return self.content_right()
        u = self._unit()
        return self.width() - (20 + sum(self.AVATAR_W[:len(self.avatars)]) + 10 * max(0, len(self.avatars) - 1)) * u

    def resizeEvent(self, ev):
        self._place(); super().resizeEvent(ev)

    def _submit_login(self):
        """The code field's Enter signs in. QLineEdit then passes the same key event on to this window, where Enter
        means "choose" — swallow that one event, or signing in would also choose the first dish."""
        self._swallow_enter = True
        QtCore.QTimer.singleShot(0, lambda: setattr(self, "_swallow_enter", False))
        self.on_login(self.edit.text())

    def _clean(self, text):
        from .capture import to_subject
        clean = to_subject(text)
        if clean != text:
            pos = self.edit.cursorPosition() - (len(text) - len(clean))
            self.edit.setText(clean); self.edit.setCursorPosition(max(0, pos))

    # ---- view -----------------------------------------------------------------------------------------------------
    def set_view(self, view):
        login = view.get("mode") == "order" and view.get("screen") == "login" and not view.get("popup")
        if login and not self.edit.isVisible():
            self.edit.setText(view.get("prefill", "")); self.edit.show(); self._place(); self.edit.setFocus()
        elif not login and self.edit.isVisible():
            self.edit.hide(); self.setFocus()
        self.view = view
        self._describe(view)
        self.update()

    def _describe(self, v):
        """What a screen reader would say: mode, heading, the pointed card, and the commands available now. The cards
        are painted, not widgets, so this description is their spoken form."""
        if v.get("mode") == "calib":
            text = f"{v.get('title', '')}. {v.get('text', '')}"
        else:
            parts = [v.get("mode_label", ""), v.get("heading") or ""]
            cards = v.get("cards", []); f = v.get("focus", 0)
            if v.get("popup"): parts.append(v["popup"]["title"])
            elif cards and 0 <= f < len(cards):
                c = cards[f]
                parts.append(self.tr("a11y.pointed", x=" ".join(x for x in (c.get("title", ""), c.get("price", "")) if x)))
            parts.append(" · ".join(f"{g} {t}" for g, t in v.get("chips", [])))
            text = " ".join(p for p in parts if p)
        if text != self.accessibleDescription(): self.setAccessibleDescription(text)

    def _hit(self, rect, action):
        """Register a clickable area exactly where it was drawn (later = on top)."""
        self.hits.append((QtCore.QRectF(rect), action))

    def hit_at(self, pos):
        """The action under ``pos`` (topmost first), or None. A modal layer registers a "block" covering what is
        behind it, so a click can never fall through to a card or tab underneath."""
        for rect, action in reversed(self.hits):
            if rect.contains(pos): return action
        return None

    def tr(self, key, **kw):
        return _t(key, self.view.get("lang", "vi"), **kw)

    def _unit(self):
        return max(0.55, min(1.6, min(self.width() / 1440, self.height() / 900)))

    def _dock_h(self):
        return 76 * self._unit()

    def _font(self, p, size, bold=False):
        f = QtGui.QFont(self.font()); f.setPointSizeF(size * self._unit()); f.setBold(bold); p.setFont(f)
        return QtGui.QFontMetricsF(f)

    def _shadow(self, p, r, radius, lift=0.0):
        """Soft layered shadow under a rounded rect (bigger and lower when the card is lifted)."""
        u = self._unit()
        for i in range(10 if lift else 6, 0, -1):
            spread = i * (2.2 if lift else 1.6) * u
            p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(70, 40, 20, 5))
            p.drawRoundedRect(r.adjusted(-spread, -spread + (8 + lift) * u, spread, spread + (8 + lift) * u),
                              radius + spread, radius + spread)

    def _surface(self, p, r, radius, fill=SURFACE, border=None, bw=0.0, lift=0.0):
        self._shadow(p, r, radius, lift=lift)
        p.setBrush(QtGui.QColor(fill) if isinstance(fill, str) else fill)
        p.setPen(_pen(border, bw) if border else QtCore.Qt.NoPen)
        p.drawRoundedRect(r, radius, radius)

    def _pill(self, p, r, fill, text, color, size=13, bold=True, border=None):
        u = self._unit()
        p.setBrush(QtGui.QColor(fill) if isinstance(fill, str) else fill)
        p.setPen(_pen(border, 1.5 * u) if border else QtCore.Qt.NoPen)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        self._font(p, size, bold); p.setPen(QtGui.QColor(color)); p.drawText(r, QtCore.Qt.AlignCenter, text)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing); p.setRenderHint(QtGui.QPainter.TextAntialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        self.hits = []
        bg = QtGui.QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0, QtGui.QColor(BG_TOP)); bg.setColorAt(1, QtGui.QColor(BG_BOTTOM))
        p.fillRect(self.rect(), bg)
        v = self.view
        accent = self._accent(v)
        blob = QtGui.QRadialGradient(QtCore.QPointF(self.width() * 0.85, -40), self.width() * 0.5)
        blob.setColorAt(0, _alpha(accent, 34)); blob.setColorAt(1, _alpha(accent, 0))
        p.fillRect(self.rect(), blob)
        self._top(p, v)
        if self.demo(): self._camera(p)
        if v.get("mode") == "calib": self._calib(p, v)
        else: self._order(p, v, accent)
        self._dock(p, v)
        if v.get("eye"): self._eye(p, v["eye"])
        if self.recording is not None: self._rec(p)
        p.end()

    def _accent(self, v):
        if v.get("screen") in ("cart", "row"): return menu.ACCENT["Giỏ"]
        return menu.ACCENT.get(v.get("category"), menu.ACCENT["Pizza"])

    # ---- top bar --------------------------------------------------------------------------------------------------
    def _top(self, p, v):
        u = self._unit(); w = self.width()
        c = QtCore.QPointF(48 * u, 46 * u)
        p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(menu.ACCENT["Pizza"])); p.drawEllipse(c, 20 * u, 20 * u)
        p.setPen(_pen("white", 2.6 * u))
        p.drawLine(c + QtCore.QPointF(-6 * u, -9 * u), c + QtCore.QPointF(-6 * u, 9 * u))
        for dx in (-9, -3): p.drawLine(c + QtCore.QPointF(dx * u, -9 * u), c + QtCore.QPointF(dx * u, -3 * u))
        p.drawLine(c + QtCore.QPointF(6 * u, -9 * u), c + QtCore.QPointF(6 * u, 9 * u))
        self._font(p, 21, True); p.setPen(QtGui.QColor(INK))
        p.drawText(QtCore.QRectF(78 * u, 24 * u, 220 * u, 44 * u), QtCore.Qt.AlignVCenter, "Muse Bistro")
        if v.get("mode") == "order" and v.get("screen") != "login":
            items = list(menu.CATEGORIES) + ["Giỏ"]
            lang = v.get("lang", "vi")
            cart = (self.tr("cart_seg_total", n=v["cart_n"], total=v["cart_total"]) if v.get("cart_n")   # the total, always visible
                    else self.tr("cart_seg", n=0))
            labels = [cart if c == "Giỏ" else menu.category_name(c, lang) for c in items]
            fm = self._font(p, 14, True)
            widths = [fm.horizontalAdvance(t) + 40 * u for t in labels]
            box = QtCore.QRectF(290 * u, 22 * u, sum(widths) + 12 * u, 48 * u)
            self._surface(p, box, 24 * u)
            x = box.left() + 6 * u
            for c, t, cw in zip(items, labels, widths):
                active = (c == v.get("category") and v.get("screen") == "browse") or (c == "Giỏ" and v.get("screen") in ("cart", "row"))
                r = QtCore.QRectF(x, box.top() + 6 * u, cw, 36 * u)
                self._hit(r, ("cart",) if c == "Giỏ" else ("cat", c))
                if active:
                    g = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
                    g.setColorAt(0, QtGui.QColor(menu.ACCENT[c]).lighter(112)); g.setColorAt(1, QtGui.QColor(menu.ACCENT[c]))
                    self._pill(p, r, g, t, "white", 14)
                else:
                    self._font(p, 14, False); p.setPen(QtGui.QColor(MUTED)); p.drawText(r, QtCore.Qt.AlignCenter, t)
                x += cw
        x = w - 24 * u
        if v.get("mode") == "order" and v.get("screen") == "login":   # the language switch: VI | EN
            lang = v.get("lang", "vi")
            box = QtCore.QRectF(self.content_right() - 24 * u - 132 * u, 24 * u, 132 * u, 44 * u)
            self._surface(p, box, 22 * u)
            for i, code in enumerate(("vi", "en")):
                r = QtCore.QRectF(box.left() + 5 * u + i * 61 * u, box.top() + 5 * u, 61 * u, 34 * u)
                self._hit(r, ("lang", code))
                if code == lang: self._pill(p, r, INK, code.upper(), "white", 13)
                else:
                    self._font(p, 13, True); p.setPen(QtGui.QColor(MUTED)); p.drawText(r, QtCore.Qt.AlignCenter, code.upper())
            self._font(p, 11); p.setPen(QtGui.QColor(MUTED))
            p.drawText(QtCore.QRectF(box.right() - 420 * u, box.bottom() + 6 * u, 420 * u, 20 * u),
                       QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, self.tr("login.lang"))
            x = box.left() - 12 * u                                   # the signal states go left of the switch
        if v.get("user"):
            fm = self._font(p, 13, True); t = v["user"]
            cw = fm.horizontalAdvance(t) + 58 * u
            r = QtCore.QRectF(x - cw, 24 * u, cw, 44 * u); self._surface(p, r, 22 * u)
            cc = QtCore.QPointF(r.left() + 22 * u, r.center().y())
            p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(INK)); p.drawEllipse(cc, 14 * u, 14 * u)
            self._font(p, 12, True); p.setPen(QtGui.QColor("white"))
            p.drawText(QtCore.QRectF(cc.x() - 14 * u, cc.y() - 14 * u, 28 * u, 28 * u), QtCore.Qt.AlignCenter, v["user"][:1].upper())
            self._font(p, 13, True); p.setPen(QtGui.QColor(INK))
            p.drawText(r.adjusted(42 * u, 0, -12 * u, 0), QtCore.Qt.AlignVCenter, t)
            x = r.left() - 12 * u
        for name, state in reversed(v.get("signals") or []):
            fm = self._font(p, 12, True); cw = fm.horizontalAdvance(name) + 34 * u
            r = QtCore.QRectF(x - cw, 30 * u, cw, 32 * u)
            col = {"ok": GOOD, "weak": WARN}.get(state, OFF)
            p.setBrush(_alpha(col, 28)); p.setPen(QtCore.Qt.NoPen); p.drawRoundedRect(r, 16 * u, 16 * u)
            p.setBrush(QtGui.QColor(col)); p.drawEllipse(QtCore.QPointF(r.left() + 13 * u, r.center().y()), 4.5 * u, 4.5 * u)
            p.setPen(QtGui.QColor(col)); p.drawText(r.adjusted(22 * u, 0, 0, 0), QtCore.Qt.AlignVCenter, name)
            x = r.left() - 8 * u

    # ---- demo column ----------------------------------------------------------------------------------------------
    def _camera(self, p):
        u = self._unit()
        r = self._camera_rect()
        self._shadow(p, r, 20 * u)
        path = QtGui.QPainterPath(); path.addRoundedRect(r, 20 * u, 20 * u)
        p.save(); p.setClipPath(path)
        img = self.camera_image
        scaled = img.scaled(int(r.width()), int(r.height()), QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
        p.drawImage(QtCore.QPointF(r.center().x() - scaled.width() / 2, r.center().y() - scaled.height() / 2), scaled)
        p.restore()
        tag = QtCore.QRectF(r.left() + 12 * u, r.top() + 12 * u, 112 * u, 30 * u)
        self._pill(p, tag, QtGui.QColor(0, 0, 0, 140), self.tr("cam.tag"), "white", 12)
        if self.camera_caption:
            fm = self._font(p, 12, True); cw = min(r.width() - 24 * u, fm.horizontalAdvance(self.camera_caption) + 28 * u)
            cr = QtCore.QRectF(r.left() + 12 * u, r.bottom() - 42 * u, cw, 30 * u)
            self._pill(p, cr, QtGui.QColor(0, 0, 0, 140), self.camera_caption, "white", 12)

    def _rec(self, p):
        """Recording a demo video: says what is being recorded and how to stop it, and is itself the stop button."""
        u = self._unit()
        t = self.tr("rec", t=f"{int(self.recording) // 60}:{int(self.recording) % 60:02d}")
        fm = self._font(p, 13, True); w = fm.horizontalAdvance(t) + 32 * u
        r = QtCore.QRectF((self.content_right() - w) / 2, 80 * u, w, 34 * u)
        self._pill(p, r, REC, t, "white", 13)
        self._hit(r, ("rec_stop",))

    # ---- calibration ----------------------------------------------------------------------------------------------
    def _calib(self, p, v):
        u = self._unit(); w, h = self.content_right(), self.height()
        n, k = v.get("n", 1), v.get("k", 1)
        for i in range(n):                                          # step dots
            x = w / 2 - (n - 1) * 14 * u + i * 28 * u
            cur = i == k - 1
            p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(INK if cur else (MUTED if i < k else LINE)))
            p.drawRoundedRect(QtCore.QRectF(x - (11 if cur else 5) * u, 128 * u, (22 if cur else 10) * u, 10 * u), 5 * u, 5 * u)
        self._font(p, 13, True); p.setPen(QtGui.QColor(MUTED))
        p.drawText(QtCore.QRectF(0, 148 * u, w, 26 * u), QtCore.Qt.AlignCenter, self.tr("calib.step", k=k, n=n))
        r = min(w, h) * 0.15; c = QtCore.QPointF(w / 2, 200 * u + r + 20 * u)
        self._shadow(p, QtCore.QRectF(c.x() - r - 24 * u, c.y() - r - 24 * u, 2 * r + 48 * u, 2 * r + 48 * u), r + 24 * u)
        p.setBrush(QtGui.QColor(SURFACE)); p.setPen(QtCore.Qt.NoPen); p.drawEllipse(c, r + 24 * u, r + 24 * u)
        p.setPen(_pen(LINE, 12 * u)); p.setBrush(QtCore.Qt.NoBrush); p.drawEllipse(c, r, r)
        frac = v.get("fraction", 0.0)
        color = {"go": GOOD, "prep": WARN, "ok": GOOD, "fail": "#D9473B"}.get(v.get("phase"), MUTED)
        if frac > 0:
            p.setPen(_pen(color, 12 * u))
            p.drawArc(QtCore.QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), 90 * 16, int(-360 * 16 * min(1.0, frac)))
        self._font(p, r * 0.46 / u, True); p.setPen(QtGui.QColor(color))
        p.drawText(QtCore.QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), QtCore.Qt.AlignCenter, v.get("big", ""))
        y = c.y() + r + 50 * u
        self._font(p, 32, True); p.setPen(QtGui.QColor(INK))
        p.drawText(QtCore.QRectF(0, y, w, 50 * u), QtCore.Qt.AlignCenter, v.get("title", ""))
        self._font(p, 18); p.setPen(QtGui.QColor(MUTED))
        p.drawText(QtCore.QRectF(w * 0.12, y + 56 * u, w * 0.76, 64 * u), QtCore.Qt.AlignHCenter | QtCore.Qt.TextWordWrap,
                   v.get("text", ""))
        if v.get("message"):
            self._font(p, 15, True); p.setPen(QtGui.QColor("#D9473B"))
            p.drawText(QtCore.QRectF(0, y + 124 * u, w, 28 * u), QtCore.Qt.AlignCenter, v["message"])

    # ---- ordering -------------------------------------------------------------------------------------------------
    def _order(self, p, v, accent):
        u = self._unit(); w, h = self.content_right(), self.height()
        screen = v.get("screen")
        margin = 56 * u
        top = 104 * u
        if screen == "login":
            self._font(p, 36, True); p.setPen(QtGui.QColor(INK))
            p.drawText(QtCore.QRectF(0, 104 * u, w, 56 * u), QtCore.Qt.AlignCenter, v.get("heading", ""))
            self._font(p, 16); p.setPen(QtGui.QColor(MUTED))
            p.drawText(QtCore.QRectF(0, 160 * u, w, 30 * u), QtCore.Qt.AlignCenter, self.tr("login.sub"))
            top = 318 * u
        else:
            title = v.get("heading") or ""
            self._font(p, 30, True); p.setPen(QtGui.QColor(INK))
            p.drawText(QtCore.QRectF(margin, top, w * 0.6, 44 * u), QtCore.Qt.AlignVCenter, title)
            if v.get("hint"):
                self._font(p, 15); p.setPen(QtGui.QColor(MUTED))
                p.drawText(QtCore.QRectF(margin, top + 42 * u, w - 2 * margin, 26 * u), QtCore.Qt.AlignVCenter, v["hint"])
            k, n = v.get("page", (0, 1))
            if n > 1:
                self._font(p, 13, True); p.setPen(QtGui.QColor(MUTED))
                x1 = w - margin
                p.drawText(QtCore.QRectF(x1 - 320 * u, top + 4 * u, 320 * u, 24 * u), QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                           self.tr("page", k=k + 1, n=n))
                for j in range(n - 1, -1, -1):
                    on = j == k; dw = (22 if on else 8) * u
                    x1 -= dw
                    p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(accent if on else LINE))
                    p.drawRoundedRect(QtCore.QRectF(x1, top + 34 * u, dw, 8 * u), 4 * u, 4 * u); x1 -= 6 * u
            top += 86 * u
        cards = v.get("cards", [])
        bottom_limit = h - self._dock_h() - 22 * u - 60 * u
        card_h = max(180 * u, min(bottom_limit - top - 30 * u, 470 * u))
        gap = 28 * u
        cw = min(400 * u, (w - 2 * margin - 2 * gap) / 3)
        x0 = (w - (3 * cw + 2 * gap)) / 2
        for i, c in enumerate(cards):
            focus = i == v.get("focus") and not v.get("popup") and not v.get("overlay")
            r = QtCore.QRectF(x0 + i * (cw + gap), top, cw, card_h)
            if focus: r.translate(0, -10 * u)
            self._card(p, r, c, i, focus, accent, v.get("dwell", 0.0) if focus else 0.0, screen)
            self._hit(r, ("card", i))
        if v.get("pointer") is not None and cards and not v.get("keyboard_only"):   # no head signal: no head track
            self._track(p, x0, top + card_h + 26 * u, 3 * cw + 2 * gap, v["pointer"], v.get("focus", 1), len(cards), accent)
        if v.get("toast"): self._toast(p, v["toast"])
        if v.get("overlay") and not v.get("popup"): self._overlay(p, v["overlay"], accent)
        if v.get("popup"): self._popup(p, v["popup"])

    def _card(self, p, r, c, i, focus, accent, dwell, screen):
        u = self._unit()
        radius = 26 * u
        if focus:                                                    # glow behind the lifted card
            for k in range(6, 0, -1):
                p.setPen(QtCore.Qt.NoPen); p.setBrush(_alpha(accent, 10))
                p.drawRoundedRect(r.adjusted(-k * 3 * u, -k * 3 * u, k * 3 * u, k * 3 * u), radius + k * 3 * u, radius + k * 3 * u)
        self._surface(p, r, radius, SURFACE, accent if focus else None, 3.5 * u if focus else 0, lift=8 if focus else 0)
        k = c.get("kind")
        art = c.get("art") or {"category": {"Pizza": "pizza", "Burger": "burger", "Drink": "drink", "Dessert": "dessert"}.get(c.get("cat")),
                               "go_cart": "cart", "checkout": "cart"}.get(k)
        tint_key = c.get("cat") if k == "category" else ("Giỏ" if screen in ("cart", "row") or k in ("go_cart", "checkout") else self.view.get("category"))
        tint = TINT.get(tint_key, TINT["Pizza"])
        img = QtCore.QRectF(r.left() + 10 * u, r.top() + 10 * u, r.width() - 20 * u, r.height() * 0.5)
        big = None
        if k in ("size", "minus", "add", "plus"): big = c.get("title")
        elif k in ("account", "guest"): big = "+" if k == "guest" else c.get("title", "")[:1].upper()
        elif k == "extras_done": big = "✓"
        elif k == "logout": big = "↩"
        elif k in ("extra", "row_minus", "row_delete", "row_plus", "new_order"):
            big = {"extra": "✓" if c.get("selected") else "+", "row_minus": "−", "row_delete": "✕", "row_plus": "+",
                   "new_order": "↻"}[k]
        if art or big:
            g = QtGui.QLinearGradient(img.topLeft(), img.bottomRight())
            g.setColorAt(0, QtGui.QColor(tint).lighter(103)); g.setColorAt(1, QtGui.QColor(tint).darker(104))
            p.setPen(QtCore.Qt.NoPen); p.setBrush(g); p.drawRoundedRect(img, radius - 8 * u, radius - 8 * u)
            if art:
                rr = min(img.width() * 0.3, img.height() * 0.34)
                food_art(p, art, QtCore.QPointF(img.center().x(), img.center().y() - rr * 0.05), rr, c.get("color"))
            else:
                self._font(p, 56 if len(big) <= 2 else 34, True); p.setPen(QtGui.QColor(accent))
                p.drawText(img, QtCore.Qt.AlignCenter, big)
            ty = img.bottom() + 18 * u
        else:
            ty = r.top() + r.height() * 0.3
        b = QtCore.QRectF(r.left() + 22 * u, r.top() + 22 * u, 34 * u, 34 * u)       # which head zone
        p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(accent) if focus else QtGui.QColor(255, 255, 255, 210)); p.drawEllipse(b)
        self._font(p, 13, True); p.setPen(QtGui.QColor("white" if focus else MUTED)); p.drawText(b, QtCore.Qt.AlignCenter, str(i + 1))
        title = c.get("title", "")
        if k == "size": title = c.get("sub", "")
        elif k in ("minus", "plus"): title = self.tr(k)
        elif k == "add": title = self.tr("add")
        self._font(p, 20, True); p.setPen(QtGui.QColor(INK))
        p.drawText(QtCore.QRectF(r.left() + 24 * u, ty, r.width() - 48 * u, 56 * u),
                   QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop | QtCore.Qt.TextWordWrap, title)
        sub = "" if k == "size" else c.get("sub", "")
        if sub:
            self._font(p, 14); p.setPen(QtGui.QColor(MUTED))
            p.drawText(QtCore.QRectF(r.left() + 24 * u, ty + 54 * u, r.width() - 48 * u, 44 * u),
                       QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop | QtCore.Qt.TextWordWrap, sub)
        if c.get("price"):
            fm = self._font(p, 16, True); pw = fm.horizontalAdvance(c["price"]) + 32 * u
            self._pill(p, QtCore.QRectF(r.left() + 20 * u, r.bottom() - 56 * u, pw, 38 * u), _alpha(accent, 30), c["price"], accent, 16)
        if c.get("selected") and k != "extra":
            cc = QtCore.QPointF(r.right() - 36 * u, r.top() + 38 * u)
            p.setBrush(QtGui.QColor(accent)); p.setPen(_pen("white", 2.5 * u)); p.drawEllipse(cc, 16 * u, 16 * u)
        if c.get("selected"):                                        # a selected option: a check on the corner
            cc = QtCore.QPointF(r.right() - 36 * u, r.top() + 38 * u)
            p.setBrush(QtGui.QColor(accent)); p.setPen(_pen("white", 2.5 * u)); p.drawEllipse(cc, 16 * u, 16 * u)
            p.setPen(_pen("white", 3.5 * u))
            p.drawLine(cc + QtCore.QPointF(-7 * u, 0), cc + QtCore.QPointF(-2 * u, 5 * u))
            p.drawLine(cc + QtCore.QPointF(-2 * u, 5 * u), cc + QtCore.QPointF(8 * u, -6 * u))
        if focus:                                                    # what to do now, on the card itself
            fm = self._font(p, 13, True)
            t = self.tr("nod_to_choose_key" if self.view.get("keyboard_only") else "nod_to_choose")
            tw = fm.horizontalAdvance(t) + 30 * u
            price_w = (self._font(p, 16, True).horizontalAdvance(c["price"]) + 32 * u) if c.get("price") else 0
            if r.width() - 40 * u - price_w - 12 * u >= tw:          # room beside the price
                tr = QtCore.QRectF(r.right() - tw - 18 * u, r.bottom() - 54 * u, tw, 36 * u)
            else:                                                    # narrow card: on the image, top right
                tr = QtCore.QRectF(r.right() - tw - 22 * u, r.top() + 22 * u + (40 * u if c.get("selected") else 0), tw, 36 * u)
            self._pill(p, tr, INK, t, "white", 13)
        if dwell > 0:
            cc = QtCore.QPointF(r.right() - 36 * u, r.top() + 38 * u + (40 * u if c.get("selected") else 0))
            p.setPen(_pen(LINE, 5 * u)); p.setBrush(QtCore.Qt.NoBrush); p.drawEllipse(cc, 15 * u, 15 * u)
            p.setPen(_pen(accent, 5 * u))
            p.drawArc(QtCore.QRectF(cc.x() - 15 * u, cc.y() - 15 * u, 30 * u, 30 * u), 90 * 16, int(-360 * 16 * dwell))

    def _track(self, p, x, y, width, pos, focus, n, accent):
        """Three segments under the cards: the pointed zone is filled; a dot follows the head."""
        u = self._unit()
        seg = (width - 20 * u) / 3
        for i in range(3):
            r = QtCore.QRectF(x + i * (seg + 10 * u), y, seg, 8 * u)
            p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(accent) if i == focus and i < n else QtGui.QColor(LINE))
            p.drawRoundedRect(r, 4 * u, 4 * u)
        cx = x + width * max(0.0, min(1.0, pos))
        p.setBrush(QtGui.QColor(SURFACE)); p.setPen(_pen(INK, 3 * u)); p.drawEllipse(QtCore.QPointF(cx, y + 4 * u), 9 * u, 9 * u)
        self._font(p, 12); p.setPen(QtGui.QColor(MUTED))
        p.drawText(QtCore.QRectF(x, y + 14 * u, width, 22 * u), QtCore.Qt.AlignCenter, self.tr("track"))

    def _toast(self, p, t):
        u = self._unit()
        text, hint = t["text"], t.get("right", "")
        fm = self._font(p, 15, True)
        right_edge = self.avatars_left() - 20 * u
        width = min(right_edge - 40 * u, max(fm.horizontalAdvance(text), fm.horizontalAdvance(hint)) + 76 * u)
        height = (64 if hint else 46) * u
        r = QtCore.QRectF(40 * u, self.height() - self._dock_h() - 22 * u - height - 14 * u, width, height)
        self._surface(p, r, 18 * u, INK)
        cc = QtCore.QPointF(r.left() + 26 * u, r.top() + 23 * u)
        p.setBrush(QtGui.QColor(GOOD)); p.setPen(QtCore.Qt.NoPen); p.drawEllipse(cc, 10 * u, 10 * u)
        p.setPen(_pen("white", 2.5 * u))
        p.drawLine(cc + QtCore.QPointF(-4 * u, 0), cc + QtCore.QPointF(-1 * u, 3 * u))
        p.drawLine(cc + QtCore.QPointF(-1 * u, 3 * u), cc + QtCore.QPointF(5 * u, -4 * u))
        inner = r.adjusted(46 * u, 8 * u, -18 * u, -8 * u)
        self._font(p, 15, True); p.setPen(QtGui.QColor("white"))
        p.drawText(QtCore.QRectF(inner.left(), inner.top(), inner.width(), 28 * u), QtCore.Qt.AlignVCenter,
                   fm.elidedText(text.lstrip("✓ "), QtCore.Qt.ElideRight, inner.width()))
        if hint:
            self._font(p, 13); p.setPen(QtGui.QColor("#FFD08A"))
            p.drawText(QtCore.QRectF(inner.left(), inner.top() + 26 * u, inner.width(), 22 * u), QtCore.Qt.AlignVCenter, hint)

    def _scrim(self, p):
        u = self._unit()
        p.fillRect(QtCore.QRectF(0, 0, self.content_right(), self.height() - self._dock_h() - 22 * u), QtGui.QColor(31, 26, 23, 110))
        self._hit(QtCore.QRectF(self.rect()), ("block",))         # modal: nothing behind can be clicked

    def _buttons(self, p, left, width, yes, no, accent, y):
        u = self._unit()
        bw = (width - 3 * 28 * u) / 2
        b1 = QtCore.QRectF(left + 28 * u, y, bw, 62 * u)
        b2 = QtCore.QRectF(b1.right() + 28 * u, y, bw, 62 * u)
        g = QtGui.QLinearGradient(b1.topLeft(), b1.bottomLeft())
        g.setColorAt(0, QtGui.QColor(accent).lighter(110)); g.setColorAt(1, QtGui.QColor(accent))
        self._pill(p, b1, g, yes, "white", 15)
        self._pill(p, b2, SURFACE, no, INK, 15, border=LINE)
        return b1, b2

    def _overlay(self, p, ov, accent):
        """Eye shortcuts: the details sheet (closed by a shake), or the cart sheet."""
        u = self._unit(); w, h = self.content_right(), self.height()
        self._scrim(p)
        if ov["kind"] == "details":
            c = ov["card"]
            sw = min(940 * u, w - 60 * u)
            r = QtCore.QRectF((w - sw) / 2, 118 * u, sw, min(520 * u, h - self._dock_h() - 180 * u))
            self._surface(p, r, 32 * u)
            hero = QtCore.QRectF(r.left() + 16 * u, r.top() + 16 * u, r.width() * 0.4, r.height() - 32 * u)
            g = QtGui.QLinearGradient(hero.topLeft(), hero.bottomRight())
            tint = QtGui.QColor(TINT.get(self.view.get("category"), TINT["Pizza"]))
            g.setColorAt(0, tint.lighter(104)); g.setColorAt(1, tint.darker(108))
            p.setPen(QtCore.Qt.NoPen); p.setBrush(g); p.drawRoundedRect(hero, 24 * u, 24 * u)
            food_art(p, c.get("art"), hero.center(), min(hero.width(), hero.height()) * 0.3, c.get("color"))
            x0 = hero.right() + 36 * u; tw = r.right() - x0 - 32 * u
            self._font(p, 13, True); p.setPen(QtGui.QColor(accent))
            p.drawText(QtCore.QRectF(x0, r.top() + 36 * u, tw, 22 * u), QtCore.Qt.AlignVCenter,
                       self.tr("sheet.details_tag", cat=menu.category_name(self.view.get("category"), self.view.get("lang", "vi")).upper()))
            self._font(p, 30, True); p.setPen(QtGui.QColor(INK))
            p.drawText(QtCore.QRectF(x0, r.top() + 60 * u, tw, 46 * u), QtCore.Qt.AlignVCenter, c["title"])
            lines = list(ov.get("lines", []))
            desc = lines.pop(0) if lines else ""
            self._font(p, 16); p.setPen(QtGui.QColor(MUTED))
            p.drawText(QtCore.QRectF(x0, r.top() + 110 * u, tw, 50 * u), QtCore.Qt.AlignLeft | QtCore.Qt.TextWordWrap, desc)
            y = r.top() + 166 * u
            for line in lines:
                label, _, rest = line.partition(": ")
                self._font(p, 12, True); p.setPen(QtGui.QColor(MUTED))
                p.drawText(QtCore.QRectF(x0, y, tw, 20 * u), QtCore.Qt.AlignVCenter, label.upper())
                y += 26 * u; x = x0
                for chip in [t.strip() for t in rest.replace(" · ", ",").split(",") if t.strip()]:
                    fm = self._font(p, 14, True); cwid = fm.horizontalAdvance(chip) + 28 * u
                    if x + cwid > x0 + tw: x = x0; y += 42 * u
                    self._pill(p, QtCore.QRectF(x, y, cwid, 34 * u), _alpha(accent, 24), chip, INK, 14)
                    x += cwid + 8 * u
                y += 50 * u
            b1, b2 = self._buttons(p, x0 - 28 * u, tw + 56 * u, self.tr("btn.choose_this"), self.tr("btn.close"), accent, r.bottom() - 98 * u)
            self._hit(b1, ("overlay_yes",)); self._hit(b2, ("overlay_no",))
            self._font(p, 12); p.setPen(QtGui.QColor(MUTED))
            p.drawText(QtCore.QRectF(x0, r.bottom() - 30 * u, tw, 20 * u), QtCore.Qt.AlignCenter,
                       self.tr("sheet.details_note"))
        else:
            n = max(1, min(6, len(ov["lines"])))
            sw = min(800 * u, w - 60 * u)
            r = QtCore.QRectF((w - sw) / 2, 130 * u, sw, (210 + 50 * n + 70) * u)
            self._surface(p, r, 32 * u)
            self._font(p, 13, True); p.setPen(QtGui.QColor(menu.ACCENT["Giỏ"]))
            p.drawText(QtCore.QRectF(r.left() + 40 * u, r.top() + 34 * u, 400 * u, 22 * u), QtCore.Qt.AlignVCenter, self.tr("sheet.peek_tag"))
            self._font(p, 30, True); p.setPen(QtGui.QColor(INK))
            p.drawText(QtCore.QRectF(r.left() + 40 * u, r.top() + 58 * u, 500 * u, 44 * u), QtCore.Qt.AlignVCenter, self.tr("sheet.cart"))
            y = r.top() + 120 * u
            if not ov["lines"]:
                self._font(p, 17); p.setPen(QtGui.QColor(MUTED))
                p.drawText(QtCore.QRectF(r.left() + 40 * u, y, r.width() - 80 * u, 40 * u), QtCore.Qt.AlignVCenter, self.tr("sheet.empty"))
            for name, qty, price in ov["lines"][:6]:
                row = QtCore.QRectF(r.left() + 32 * u, y, r.width() - 64 * u, 44 * u)
                p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(BG_TOP)); p.drawRoundedRect(row, 14 * u, 14 * u)
                self._font(p, 16, True); p.setPen(QtGui.QColor(INK))
                p.drawText(row.adjusted(18 * u, 0, -240 * u, 0), QtCore.Qt.AlignVCenter, name)
                self._font(p, 16)
                p.drawText(QtCore.QRectF(row.right() - 230 * u, row.top(), 60 * u, row.height()), QtCore.Qt.AlignVCenter, f"× {qty}")
                self._font(p, 16, True); p.setPen(QtGui.QColor(menu.ACCENT["Giỏ"]))
                p.drawText(row.adjusted(0, 0, -18 * u, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight, price)
                y += 50 * u
            if ov["lines"]:
                self._font(p, 22, True); p.setPen(QtGui.QColor(INK))
                p.drawText(QtCore.QRectF(r.left() + 40 * u, y + 4 * u, r.width() - 80 * u, 40 * u),
                           QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight, self.tr("sheet.total", total=ov["total"]))
            b1, b2 = self._buttons(p, r.left(), r.width(), self.tr("btn.order") if ov["lines"] else self.tr("btn.nod"), self.tr("btn.close"),
                                   menu.ACCENT["Giỏ"], r.bottom() - 100 * u)
            self._hit(b1, ("overlay_yes",)); self._hit(b2, ("overlay_no",))
            if ov.get("left") is not None:
                self._font(p, 12); p.setPen(QtGui.QColor(MUTED))
                p.drawText(QtCore.QRectF(r.left(), r.bottom() - 30 * u, r.width(), 20 * u), QtCore.Qt.AlignCenter,
                           self.tr("sheet.closes", s=f"{ov['left']:.0f}"))

    def _popup(self, p, pop):
        u = self._unit(); w, h = self.content_right(), self.height()
        self._scrim(p)
        pw = min(720 * u, w - 60 * u)
        r = QtCore.QRectF((w - pw) / 2, h / 2 - 200 * u, pw, 300 * u)
        self._surface(p, r, 32 * u)
        self._font(p, 26, True); p.setPen(QtGui.QColor(INK))
        p.drawText(QtCore.QRectF(r.left() + 30 * u, r.top() + 40 * u, r.width() - 60 * u, 44 * u), QtCore.Qt.AlignCenter, pop["title"])
        self._font(p, 15); p.setPen(QtGui.QColor(MUTED))
        p.drawText(QtCore.QRectF(r.left(), r.top() + 88 * u, r.width(), 26 * u), QtCore.Qt.AlignCenter, pop.get("sub", ""))
        b1, b2 = self._buttons(p, r.left(), r.width(), pop.get("yes", self.tr("btn.yes")), pop.get("no", self.tr("btn.cancel")), GOOD,
                               r.top() + 150 * u)
        self._hit(b1, ("popup_yes",)); self._hit(b2, ("popup_no",))
        self._font(p, 12); p.setPen(QtGui.QColor(MUTED))
        p.drawText(QtCore.QRectF(r.left(), r.bottom() - 46 * u, r.width(), 22 * u), QtCore.Qt.AlignCenter,
                   self.tr("pop.timeout", s=f"{pop.get('left', 0):.0f}"))

    # ---- dock -----------------------------------------------------------------------------------------------------
    def _dock(self, p, v):
        u = self._unit(); w, h = self.width(), self.height()
        r = QtCore.QRectF(20 * u, h - self._dock_h() - 16 * u, w - 40 * u, self._dock_h())
        self._surface(p, r, r.height() / 2, DOCK)
        mode = v.get("mode_label", "")
        fm = self._font(p, 14, True)
        mr = QtCore.QRectF(r.left() + 14 * u, r.top() + 14 * u, fm.horizontalAdvance(mode) + 36 * u, r.height() - 28 * u)
        self._pill(p, mr, SURFACE, mode, INK, 14)
        right = r.right() - 14 * u
        if v.get("received"):                                       # the last command understood, right end
            t = "✓ " + v["received"]
            fm = self._font(p, 13, True); rw = fm.horizontalAdvance(t) + 32 * u
            rr = QtCore.QRectF(right - rw, r.top() + 14 * u, rw, r.height() - 28 * u)
            self._pill(p, rr, GOOD, t, "white", 13)
            right = rr.left() - 12 * u
        x = mr.right() + 16 * u
        chips = v.get("chips", [])
        for n, (g, t) in enumerate(chips):
            fm = self._font(p, 13); gw = max(30 * u, self._font(p, 13, True).horizontalAdvance(g) + 16 * u)
            cw = fm.horizontalAdvance(t) + gw + 30 * u
            if x + cw > right - (54 * u if n < len(chips) - 1 else 0):        # no room: say how many are hidden
                more = QtCore.QRectF(x, r.top() + 14 * u, 46 * u, r.height() - 28 * u)
                self._pill(p, more, QtGui.QColor(255, 255, 255, 30), f"+{len(chips) - n}", "#F3E9DD", 13)
                break
            cr = QtCore.QRectF(x, r.top() + 14 * u, cw, r.height() - 28 * u)
            p.setBrush(QtGui.QColor(255, 255, 255, 18)); p.setPen(QtCore.Qt.NoPen); p.drawRoundedRect(cr, cr.height() / 2, cr.height() / 2)
            ic = QtCore.QRectF(cr.left() + 7 * u, cr.center().y() - 15 * u, gw, 30 * u)    # icon, or a key cap
            p.setBrush(QtGui.QColor(255, 208, 138, 40)); p.drawRoundedRect(ic, 15 * u, 15 * u)
            self._font(p, 13, True); p.setPen(QtGui.QColor("#FFD08A"))
            p.drawText(ic, QtCore.Qt.AlignCenter, g)
            self._font(p, 13); p.setPen(QtGui.QColor("#F3E9DD"))
            p.drawText(QtCore.QRectF(ic.right() + 8 * u, cr.top(), cw - gw - 18 * u, cr.height()), QtCore.Qt.AlignVCenter, t)
            x += cw + 8 * u

    def _eye(self, p, eye):
        """Eye feedback: an eye that blinks with every blink seen; while the eyes are closed, a ring fills up to the
        moment of the tone, with the seconds in words."""
        u = self._unit()
        r = 24 * u
        if self.demo():
            side = self._side()
            c = QtCore.QPointF(side[0] + r + 12 * u, self._camera_rect().bottom() + 14 * u + 124 * u + 20 * u + r + 12 * u)
        else:
            c = QtCore.QPointF(self.avatars_left() - 50 * u, self.height() - self._dock_h() - 22 * u - 60 * u)
        self._surface(p, QtCore.QRectF(c.x() - r - 12 * u, c.y() - r - 12 * u, 2 * r + 24 * u, 2 * r + 24 * u), r + 12 * u)
        closing = eye.get("closing") or eye.get("since", 0) > 0
        if closing:
            frac = min(1.0, eye.get("since", 0.0) / max(0.1, eye.get("closed_s", 3.0)))
            p.setPen(_pen(menu.ACCENT["Giỏ"], 5 * u)); p.setBrush(QtCore.Qt.NoBrush)
            p.drawArc(QtCore.QRectF(c.x() - r - 5 * u, c.y() - r - 5 * u, 2 * r + 10 * u, 2 * r + 10 * u), 90 * 16, int(-360 * 16 * frac))
            fm = self._font(p, 13, True)
            t = self.tr("eye.closing", s=f"{eye.get('since', 0):.1f}", n=f"{eye.get('closed_s', 3):.0f}")
            tw = fm.horizontalAdvance(t) + 28 * u
            tx = c.x() + r + 22 * u if self.demo() else c.x() - r - 22 * u - tw
            self._pill(p, QtCore.QRectF(tx, c.y() - 17 * u, tw, 34 * u), _alpha(menu.ACCENT["Giỏ"], 30), t, menu.ACCENT["Giỏ"], 13)
        p.setPen(_pen(INK, 3 * u)); p.setBrush(QtCore.Qt.NoBrush)
        if eye.get("blink") or closing:
            p.drawArc(QtCore.QRectF(c.x() - r * 0.75, c.y() - r * 0.3, r * 1.5, r * 0.6), 180 * 16, 180 * 16)
        else:
            path = QtGui.QPainterPath(QtCore.QPointF(c.x() - r * 0.75, c.y()))
            path.quadTo(QtCore.QPointF(c.x(), c.y() - r * 0.7), QtCore.QPointF(c.x() + r * 0.75, c.y()))
            path.quadTo(QtCore.QPointF(c.x(), c.y() + r * 0.7), QtCore.QPointF(c.x() - r * 0.75, c.y()))
            p.drawPath(path); p.setBrush(QtGui.QColor(INK)); p.drawEllipse(c, r * 0.2, r * 0.2)

    # ---- input ----------------------------------------------------------------------------------------------------
    def keyPressEvent(self, ev):
        if self._swallow_enter and ev.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self._swallow_enter = False; return
        if ev.key() == QtCore.Qt.Key_F11 and not ev.isAutoRepeat():
            self.showNormal() if self.isFullScreen() else self.showFullScreen(); return
        self.on_key(ev)

    def mousePressEvent(self, ev):
        """Clicks go to the control drawn under the pointer — never to an area computed apart from the drawing."""
        if ev.button() == QtCore.Qt.LeftButton and self.on_click is not None:
            action = self.hit_at(ev.position())
            if action is not None and action != ("block",): self.on_click(action)
        super().mousePressEvent(ev)

    def closeEvent(self, ev):
        self.on_closed()
        super().closeEvent(ev)
