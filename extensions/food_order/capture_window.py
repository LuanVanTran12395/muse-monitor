"""F0 capture window (Qt): one large instruction at a time, a GO cue, a progress ring for the action window.

It opens on a **sign-in screen** (``show_login``): the participant's ID is typed like signing in to order, Enter
starts. Layout of the steps, the same on every step so the eye knows where to look:

    top bar     set (Hiệu chỉnh / Kiểm tra / Tự nhiên) · step k / n · time left
    centre      pictogram of the gesture · instruction in large type · phase word (CHUẨN BỊ / LÀM NGAY / VỀ GIỮA)
    ring        fills during the action window (green), grey while preparing
    bottom      keys: Backspace = this repetition was wrong · P = pause after this step · Esc = stop

The window draws only; the extension drives the steps and records the times.
"""
import math

from PySide6 import QtCore, QtGui, QtWidgets

BG, PANEL, TEXT, MUTED, GO, PREP, REST, BAD = "#0f1115", "#1a1d24", "#eef0f4", "#9aa3b2", "#2fbf71", "#e3b341", \
    "#5b6475", "#e5534b"
SET_NAMES = {"calib": "Hiệu chỉnh", "test": "Kiểm tra", "": ""}
KIND_NAMES = {"done": "Hoàn tất", "baseline": "Đường nền", "segment": "Quét hướng đầu", "negative": "Cử động tự nhiên", "pause": "Tạm nghỉ"}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _pen(color, width):
    pen = QtGui.QPen(QtGui.QColor(color), width)
    pen.setCapStyle(QtCore.Qt.RoundCap); pen.setJoinStyle(QtCore.Qt.RoundJoin)
    return pen


class CaptureWindow(QtWidgets.QWidget):
    def __init__(self, on_key, on_closed, on_click=None):
        super().__init__()
        self.on_key, self.on_closed, self.on_click = on_key, on_closed, on_click
        self.setWindowTitle("Thu cử chỉ — Food order (F0)")
        self.resize(1100, 720)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.state = dict(phase="idle", title="Sẵn sàng", text="Bấm Start trong tab Food order để bắt đầu.",
                          extra="", glyph="ready", set="", kind="", k=0, n=0, fraction=0.0, seconds=None,
                          left_total=None, bad=False, paused=False, warning="")
        self.login_cb, self.login_msg = None, ""
        self.edit = QtWidgets.QLineEdit(self)
        self.edit.setPlaceholderText("M01")
        self.edit.setAlignment(QtCore.Qt.AlignCenter)
        self.edit.setAccessibleName("Mã người dùng")
        self.edit.returnPressed.connect(self._submit)
        self.edit.textEdited.connect(self._clean)
        self.edit.hide()

    # ---- sign-in ------------------------------------------------------------------------------------------------
    def show_login(self, prefill, on_login, message=""):
        """on_login(id) → "" when signed in (the caller then shows the steps), else the message to show."""
        self.login_cb = on_login
        self.state.update(phase="login", title="Đăng nhập", glyph="ready", set="", kind="", k=0, n=0, fraction=0.0,
                          seconds=None, left_total=None, bad=False, warning="", text="", extra="")
        self.edit.setText(prefill); self.edit.selectAll()
        self._set_msg(message)
        self._place_edit(); self.edit.show(); self.edit.setFocus()
        self.update()

    def _clean(self, text):
        """Keep a folder-safe code as the participant types: spaces → _, accents removed (to_subject)."""
        from .capture import to_subject
        clean = to_subject(text)
        if clean != text:
            pos = self.edit.cursorPosition() - (len(text) - len(clean))
            self.edit.setText(clean); self.edit.setCursorPosition(max(0, pos))
        self._set_msg("")

    def focus_steps(self):
        """Take the keyboard back (Space / Enter / ⌫ / P / Esc must reach this window, not the main window)."""
        self.raise_(); self.activateWindow(); self.setFocus()

    def _set_msg(self, msg):
        self.login_msg = msg; self.update()

    def _submit(self):
        if self.login_cb is None: return
        msg = self.login_cb(self.edit.text().strip())
        if msg: self._set_msg(msg); self.edit.setFocus(); self.edit.selectAll()

    def _card(self):
        w, h = self.width(), self.height()
        cw, ch = min(640.0, w * 0.8), min(420.0, h * 0.7)
        return QtCore.QRectF((w - cw) / 2, (h - ch) / 2, cw, ch)

    def _place_edit(self):
        card = self._card(); unit = _clamp(self.height() / 720, 0.6, 1.8)
        f = QtGui.QFont(self.font()); f.setPointSizeF(30 * unit); f.setBold(True); self.edit.setFont(f)
        self.edit.setGeometry(int(card.left() + 60 * unit), int(card.top() + card.height() * 0.42),
                              int(card.width() - 120 * unit), int(76 * unit))
        self.edit.setStyleSheet(f"QLineEdit{{background:{BG};color:{TEXT};border:2px solid {MUTED};"
                                f"border-radius:{int(14 * unit)}px;padding:4px 12px}}"
                                f"QLineEdit:focus{{border:3px solid {GO}}}")

    def resizeEvent(self, ev):
        if self.edit.isVisible(): self._place_edit()
        super().resizeEvent(ev)

    def show_state(self, **kw):
        self.state.update(kw)
        if self.state["phase"] != "login" and self.edit.isVisible(): self.edit.hide(); self.focus_steps()
        self.setAccessibleDescription(f"{self.state['title']}. {self.state['text']}")
        self.update()

    # ---- painting ------------------------------------------------------------------------------------------------
    def _font(self, p, size, bold=False):
        f = QtGui.QFont(self.font()); f.setPointSizeF(size); f.setBold(bold); p.setFont(f)
        return QtGui.QFontMetricsF(f)

    def _fit(self, text, rect, size, bold=False, min_size=14):
        flags = QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap
        while size > min_size:
            f = QtGui.QFont(self.font()); f.setPointSizeF(size); f.setBold(bold)
            if QtGui.QFontMetricsF(f).boundingRect(rect, flags, text).height() <= rect.height(): break
            size *= 0.94
        return size

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing); p.setRenderHint(QtGui.QPainter.TextAntialiasing)
        w, h, s = self.width(), self.height(), self.state
        p.fillRect(self.rect(), QtGui.QColor(BG))
        unit = _clamp(h / 720, 0.6, 1.8)
        if s["phase"] == "login": self._paint_login(p, unit); p.end(); return
        # top bar
        bar = QtCore.QRectF(0, 0, w, 56 * unit)
        p.fillRect(bar, QtGui.QColor(PANEL))
        self._font(p, 15 * unit, bold=True); p.setPen(QtGui.QColor(TEXT))
        where = SET_NAMES.get(s["set"]) or KIND_NAMES.get(s["kind"], "")
        p.drawText(bar.adjusted(24 * unit, 0, 0, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, where)
        right = f"{s['k']} / {s['n']}" if s["n"] else ""
        if s["left_total"] is not None: right += f"   ·   còn khoảng {s['left_total'] / 60:.0f} phút"
        self._font(p, 14 * unit); p.setPen(QtGui.QColor(MUTED))
        p.drawText(bar.adjusted(0, 0, -24 * unit, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight, right)
        if s["n"]:
            p.fillRect(QtCore.QRectF(0, bar.bottom() - 4 * unit, w * s["k"] / s["n"], 4 * unit), QtGui.QColor(GO))
        # phase colour
        color = {"go": GO, "prep": PREP, "rest": REST}.get(s["phase"], MUTED)
        # pictogram inside the ring
        radius = min(w, h) * 0.17
        center = QtCore.QPointF(w / 2, bar.bottom() + 40 * unit + radius)
        p.setPen(QtGui.QPen(QtGui.QColor(PANEL), 12 * unit)); p.setBrush(QtCore.Qt.NoBrush)
        p.drawEllipse(center, radius, radius)
        if s["fraction"] > 0:
            p.setPen(_pen(color, 12 * unit))
            rect = QtCore.QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
            p.drawArc(rect, 90 * 16, -int(360 * 16 * _clamp(s["fraction"], 0, 1)))
        draw_glyph(p, s["glyph"], center, radius * 0.62, QtGui.QColor(color if s["phase"] == "go" else TEXT))
        # phase word + seconds
        y = center.y() + radius + 18 * unit
        word = {"prep": "CHUẨN BỊ", "go": "LÀM NGAY", "rest": "VỀ GIỮA · NGHỈ", "pause": "TẠM NGHỈ",
                "done": "XONG", "stopped": "ĐÃ DỪNG"}.get(s["phase"], "")
        if s["phase"] == "go" and s["kind"] in ("baseline", "segment", "negative"): word = "ĐANG THU"
        if s["seconds"] is not None and s["phase"] in ("prep", "go", "rest"): word += f"   {math.ceil(s['seconds'])}"
        self._font(p, 22 * unit, bold=True); p.setPen(QtGui.QColor(color))
        p.drawText(QtCore.QRectF(0, y, w, 40 * unit), QtCore.Qt.AlignCenter, word)
        # title + instruction
        y += 48 * unit
        self._font(p, 30 * unit, bold=True); p.setPen(QtGui.QColor(TEXT))
        p.drawText(QtCore.QRectF(0, y, w, 46 * unit), QtCore.Qt.AlignCenter, s["title"])
        y += 52 * unit
        rect = QtCore.QRectF(w * 0.08, y, w * 0.84, max(40.0, h - y - 120 * unit))
        text = s["text"] + (f"\n\n«{s['extra']}»" if s["extra"] else "")
        self._font(p, self._fit(text, rect, 21 * unit)); p.setPen(QtGui.QColor(MUTED))
        p.drawText(rect, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop | QtCore.Qt.TextWordWrap, text)
        # marks
        if s["bad"]:
            self._font(p, 16 * unit, bold=True); p.setPen(QtGui.QColor(BAD))
            p.drawText(QtCore.QRectF(0, h - 104 * unit, w, 28 * unit), QtCore.Qt.AlignCenter, "✕ Lượt này được đánh dấu hỏng")
        if s["warning"]:
            self._font(p, 16 * unit, bold=True); p.setPen(QtGui.QColor(BAD))
            p.drawText(QtCore.QRectF(0, h - 104 * unit, w, 28 * unit), QtCore.Qt.AlignCenter, "⚠ " + s["warning"])
        # keys
        keys = [("⌫", "lượt này hỏng"), ("P", "tạm dừng sau bước này" if not s["paused"] else "tiếp tục"),
                ("Esc", "dừng")]
        if s["phase"] == "pause": keys = [("Space / Enter / click", "tiếp tục")] + keys[2:]
        elif s["phase"] in ("done", "stopped"): keys = [("Space / Enter / click", "thu thêm 1 phiên"), ("Esc", "đóng")]
        self._paint_keys(p, keys, h - 66 * unit, unit)
        p.end()

    def _paint_login(self, p, unit):
        card = self._card()
        p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(PANEL)); p.drawRoundedRect(card, 24 * unit, 24 * unit)
        self._font(p, 30 * unit, bold=True); p.setPen(QtGui.QColor(TEXT))
        p.drawText(QtCore.QRectF(card.left(), card.top() + 34 * unit, card.width(), 50 * unit), QtCore.Qt.AlignCenter,
                   "Đăng nhập")
        self._font(p, 17 * unit); p.setPen(QtGui.QColor(MUTED))
        p.drawText(QtCore.QRectF(card.left() + 40 * unit, card.top() + 92 * unit, card.width() - 80 * unit, 60 * unit),
                   QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap,
                   "Nhập mã người dùng (ví dụ M01) rồi nhấn Enter — dấu cách thành «_», tiếng Việt tự bỏ dấu")
        y = card.top() + card.height() * 0.42 + 92 * unit
        if self.login_msg:
            self._font(p, 15 * unit, bold=True); p.setPen(QtGui.QColor(BAD))
            p.drawText(QtCore.QRectF(card.left() + 30 * unit, y, card.width() - 60 * unit, 54 * unit),
                       QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap, self.login_msg)
        else:
            self._font(p, 14 * unit); p.setPen(QtGui.QColor(MUTED))
            p.drawText(QtCore.QRectF(card.left(), y, card.width(), 30 * unit), QtCore.Qt.AlignCenter,
                       "Mã chỉ dùng để đặt tên dữ liệu — không cần tên thật")
        self._paint_keys(p, [("Enter", "đăng nhập và bắt đầu"), ("F11", "toàn màn hình")], self.height() - 66 * unit, unit)

    def _paint_keys(self, p, keys, y, unit):
        fm = self._font(p, 14 * unit)
        parts = [(k, t, fm.horizontalAdvance(k) + 22 * unit, fm.horizontalAdvance(t)) for k, t in keys]
        total = sum(kw + tw + 40 * unit for _, _, kw, tw in parts)
        x = (self.width() - total) / 2
        for k, t, kw, tw in parts:
            box = QtCore.QRectF(x, y, kw, 34 * unit)
            p.setPen(QtGui.QPen(QtGui.QColor(MUTED), 1.5)); p.setBrush(QtGui.QColor(PANEL))
            p.drawRoundedRect(box, 6 * unit, 6 * unit)
            p.setPen(QtGui.QColor(TEXT)); p.drawText(box, QtCore.Qt.AlignCenter, k)
            p.setPen(QtGui.QColor(MUTED))
            p.drawText(QtCore.QRectF(box.right() + 8 * unit, y, tw + 4, 34 * unit), QtCore.Qt.AlignVCenter, t)
            x += kw + tw + 40 * unit

    # ---- input ---------------------------------------------------------------------------------------------------
    def keyPressEvent(self, ev):
        if ev.key() in (QtCore.Qt.Key_F, QtCore.Qt.Key_F11) and not ev.isAutoRepeat():
            self.showNormal() if self.isFullScreen() else self.showFullScreen(); return
        self.on_key(ev)

    def mousePressEvent(self, ev):
        if ev.button() == QtCore.Qt.LeftButton and self.on_click is not None and self.state["phase"] != "login":
            self.on_click()
        super().mousePressEvent(ev)

    def closeEvent(self, ev):
        self.on_closed()
        super().closeEvent(ev)


def draw_glyph(p, name, c, r, color):
    """Line pictograms (no image files): a head seen from above / the front, arrows, eyes."""
    p.setPen(_pen(color, max(3.0, r * 0.07))); p.setBrush(QtCore.Qt.NoBrush)

    def head(cx=c.x(), cy=c.y(), rr=r * 0.55):
        p.drawEllipse(QtCore.QPointF(cx, cy), rr, rr * 1.12)

    def arrow(x0, y0, x1, y1):
        p.drawLine(QtCore.QPointF(x0, y0), QtCore.QPointF(x1, y1))
        ang = math.atan2(y1 - y0, x1 - x0); a = r * 0.18
        for d in (2.5, -2.5):
            p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x1 - a * math.cos(ang + d / 3 * 1.2),
                                                              y1 - a * math.sin(ang + d / 3 * 1.2)))

    def curved(direction, big, hold=False):
        """Arc over the head from the nose (top) towards the turn: +1 = the participant's left (screen left)."""
        span = 80 if big else 38
        R = r * 0.95
        rect = QtCore.QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R)
        p.drawArc(rect, 90 * 16, int(span * direction * 16))
        th = math.radians(90 + span * direction)
        ex, ey = c.x() + R * math.cos(th), c.y() - R * math.sin(th)
        tx, ty = -math.sin(th) * direction, -math.cos(th) * direction        # direction of travel on screen
        a = r * 0.22
        for rot in (0.5, -0.5):
            bx = -(tx * math.cos(rot) - ty * math.sin(rot)); by = -(tx * math.sin(rot) + ty * math.cos(rot))
            p.drawLine(QtCore.QPointF(ex, ey), QtCore.QPointF(ex + a * bx, ey + a * by))
        if hold:                                            # a bar beyond the arrow: go there and stay
            nx, ny = math.cos(th), -math.sin(th)
            q = QtCore.QPointF(ex + tx * r * 0.16, ey + ty * r * 0.16)
            p.drawLine(q - QtCore.QPointF(nx, ny) * r * 0.16, q + QtCore.QPointF(nx, ny) * r * 0.16)
        elif big:                                           # and back: a return arrow inside
            R2 = r * 0.72
            p.drawArc(QtCore.QRectF(c.x() - R2, c.y() - R2, 2 * R2, 2 * R2), int((90 + span * direction) * 16),
                      int(-span * direction * 0.8 * 16))

    def eye(cx, cy, closed=False):
        w2, h2 = r * 0.32, r * 0.18
        if closed:
            p.drawArc(QtCore.QRectF(cx - w2, cy - h2, 2 * w2, 2 * h2), 180 * 16, 180 * 16)
        else:
            path = QtGui.QPainterPath(QtCore.QPointF(cx - w2, cy))
            path.quadTo(QtCore.QPointF(cx, cy - 2 * h2), QtCore.QPointF(cx + w2, cy))
            path.quadTo(QtCore.QPointF(cx, cy + 2 * h2), QtCore.QPointF(cx - w2, cy))
            p.drawPath(path); p.setBrush(color); p.drawEllipse(QtCore.QPointF(cx, cy), h2 * 0.6, h2 * 0.6)
            p.setBrush(QtCore.Qt.NoBrush)

    if name in ("point_left", "point_right", "turn_left", "turn_right"):
        head(); d = 1 if name.endswith("left") else -1
        nose = QtCore.QPointF(c.x(), c.y() - r * 0.62)
        p.drawLine(nose + QtCore.QPointF(-r * 0.08, r * 0.04), nose); p.drawLine(nose, nose + QtCore.QPointF(r * 0.08, r * 0.04))
        curved(d, name.startswith("turn"), hold=name.startswith("point"))
    elif name == "nod":
        head(cx=c.x() - r * 0.2, rr=r * 0.45); arrow(c.x() + r * 0.55, c.y() - r * 0.4, c.x() + r * 0.55, c.y() + r * 0.4)
        arrow(c.x() + r * 0.55, c.y() + r * 0.4, c.x() + r * 0.55, c.y() - r * 0.4)
    elif name == "shake":
        head(rr=r * 0.45); arrow(c.x() - r * 0.5, c.y() + r * 0.8, c.x() + r * 0.5, c.y() + r * 0.8)
        arrow(c.x() + r * 0.5, c.y() + r * 0.8, c.x() - r * 0.5, c.y() + r * 0.8)
    elif name == "look_up":
        head(rr=r * 0.45); arrow(c.x(), c.y() - r * 0.15, c.x(), c.y() - r * 0.95)
    elif name in ("double_blink", "eyes_closed", "relax"):
        closed = name == "eyes_closed"
        eye(c.x() - r * 0.42, c.y(), closed); eye(c.x() + r * 0.42, c.y(), closed)
        if name == "double_blink":
            fm_font = QtGui.QFont(); fm_font.setPointSizeF(r * 0.32); fm_font.setBold(True); p.setFont(fm_font)
            p.drawText(QtCore.QRectF(c.x() - r, c.y() + r * 0.3, 2 * r, r * 0.6), QtCore.Qt.AlignCenter, "× 2")
    elif name in ("look_around", "glance_turn", "sweep"):
        head(rr=r * 0.45); curved(1, False); curved(-1, False)
    elif name == "talk":
        head(cx=c.x() - r * 0.3, rr=r * 0.45)
        for k in (0.25, 0.42, 0.59):
            p.drawArc(QtCore.QRectF(c.x() - r * 0.05 + r * 0.1 - k * r, c.y() - r * k, r * k * 2, r * k * 2),
                      -40 * 16, 80 * 16)
    elif name == "hands":
        head(cx=c.x() - r * 0.15, rr=r * 0.45)
        p.drawEllipse(QtCore.QPointF(c.x() + r * 0.5, c.y() + r * 0.35), r * 0.18, r * 0.24)
    elif name == "pause":
        for dx in (-0.22, 0.22):
            p.drawLine(QtCore.QPointF(c.x() + r * dx, c.y() - r * 0.45), QtCore.QPointF(c.x() + r * dx, c.y() + r * 0.45))
    else:                                                   # ready / done: a check mark
        p.drawLine(QtCore.QPointF(c.x() - r * 0.45, c.y()), QtCore.QPointF(c.x() - r * 0.1, c.y() + r * 0.35))
        p.drawLine(QtCore.QPointF(c.x() - r * 0.1, c.y() + r * 0.35), QtCore.QPointF(c.x() + r * 0.5, c.y() - r * 0.35))
