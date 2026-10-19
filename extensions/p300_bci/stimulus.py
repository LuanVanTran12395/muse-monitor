"""Stimulus window (Qt): a 3 × 3 grid on black, one white disc while a cell is lit.

It reports the monotonic time of the FIRST paint after each change (``on_painted(tag, mono)``): the software onset
estimate. Qt has then drawn into its buffer; when the pixels appear on the display (compositor, refresh, pixel
response) is not known without an external optical measurement.

A small square in the bottom-left corner is white exactly while a cell is lit (black otherwise): a ready-made
target for a photodiode later (proposal, appendix B), without changing the schedule.

Participant screens (no stimuli, no onsets): instructions (``show_page``), countdown (``show_countdown``) and the
break between blocks (``show_rest``). Layout, the same on every page so the eye knows where to look:

    progress dots · title · illustration · text (large, scaled to the window) · navigation keys at the bottom
"""
from PySide6 import QtCore, QtGui, QtWidgets

from . import pictograms as pic
from .schedule import COMMANDS, GRID

DIM, LIT, CUE, LABEL, BG, TEXT = "#4a4a4a", "#ffffff", "#e3b341", "#9a9a9a", "#000000", "#e8e8e8"


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


class StimulusWindow(QtWidgets.QWidget):
    def __init__(self, clock, on_painted, on_key, on_closed, on_click=None):
        super().__init__(None, QtCore.Qt.Window)
        self.setWindowTitle("P300 stimulus")
        self.setAccessibleName("P300 stimulus grid")
        self.setMinimumSize(800, 560); self.resize(1100, 760)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        pal = self.palette(); pal.setColor(QtGui.QPalette.Window, QtGui.QColor(BG)); self.setPalette(pal)
        self.setAutoFillBackground(True)
        self.clock, self.on_painted, self.on_key, self.on_closed = clock, on_painted, on_key, on_closed
        self.on_click = on_click or (lambda: None)
        self.lit = None          # cell index currently lit
        self.cue = None          # target cell outlined during the cue
        self.message = ""
        self.show_labels = True
        self.pending = []        # tags waiting for their first paint
        self.page = None         # instructions page: dict(title, lines, icon, icons, demo, index, total, nav)
        self.countdown = None    # (number, caption, fraction of the second left) during a countdown
        self.rest = None         # (seconds left, title, hint) during a break

    # ---- participant screens -------------------------------------------------------------------------------
    def show_page(self, page, footer="", index=0, total=1, nav=None):
        """Instructions page. ``nav``: labels dict(next, back, click, esc); ``footer``: page counter text (also read
        by screen readers)."""
        self.page = dict(page, footer=footer, index=index, total=total, nav=nav or {})
        self.countdown = self.rest = None
        self.setAccessibleDescription(page["title"] + ". " + " ".join(page.get("lines", [])))
        self.update()

    def show_countdown(self, number, caption="", fraction=1.0):
        self.page, self.rest, self.countdown = None, None, (number, caption, fraction)
        self.setAccessibleDescription(f"{caption} {number}")
        self.update()

    def show_rest(self, seconds, title, hint):
        self.page, self.countdown, self.rest = None, None, (seconds, title, hint)
        self.update()

    def clear_overlay(self):
        self.page = self.countdown = self.rest = None
        self.update()

    def set_state(self, lit=..., cue=..., message=..., tag=None):
        if lit is not ...: self.lit = lit
        if cue is not ...: self.cue = cue
        if message is not ...: self.message = message
        if tag is not None: self.pending.append(tag)
        self.update()

    # ---- geometry ------------------------------------------------------------------------------------------------
    def cell_rect(self, cell):
        w, h = self.width(), self.height() - 70                      # bottom 70 px: messages
        size = min(w, h) / GRID
        x0, y0 = (w - size * GRID) / 2, (h - size * GRID) / 2 + 10
        r, c = divmod(cell, GRID)
        return QtCore.QRectF(x0 + c * size, y0 + r * size, size, size)

    def _sizes(self):
        h = self.height()
        return dict(title=_clamp(h * 0.062, 26, 56), body=_clamp(h * 0.036, 18, 32), small=_clamp(h * 0.024, 13, 20),
                    key=_clamp(h * 0.085, 48, 84))

    # ---- painting ------------------------------------------------------------------------------------------------
    def _font(self, p, size, bold=False):
        f = QtGui.QFont(self.font()); f.setPointSizeF(size); f.setBold(bold); p.setFont(f)
        return QtGui.QFontMetricsF(f)

    def _fit_size(self, texts_rects, size, min_size, flags):
        """Largest size ≤ ``size`` (≥ ``min_size``) at which every text fits its rect — never cut off."""
        while size > min_size:
            f = QtGui.QFont(self.font()); f.setPointSizeF(size); fm = QtGui.QFontMetricsF(f)
            if all(fm.boundingRect(r, flags, t).height() <= r.height() for t, r in texts_rects): return size
            size *= 0.94
        return min_size

    def _paint_nav(self, p, top):
        """Bottom bar, readable from the chair: ← (back) apart on the left; Space / → / click grouped under ONE
        caption (next, or start on the last page) so the same action is not labelled three times. ← is dimmed on the
        first page."""
        page, sz = self.page, self._sizes()
        nav, kh = page["nav"], sz["key"]
        first, last = page["index"] == 0, page["index"] == page["total"] - 1
        w = self.width()
        cap = sz["body"] * 0.85
        gap, sep = kh * 0.35, kh * 1.6
        back_w, space_w, arrow_w, mouse_w = kh * 1.2, kh * 2.6, kh * 1.2, kh * 0.95
        group_w = space_w + arrow_w + mouse_w + 2 * gap
        total = back_w + sep + group_w
        x = (w - total) / 2
        pic.keycap(p, QtCore.QRectF(x, top, back_w, kh), "←", size=kh * 0.48, enabled=not first)
        self._font(p, cap); p.setPen(QtGui.QColor(TEXT if not first else DIM))
        p.drawText(QtCore.QRectF(x - sep / 2, top + kh + 10, back_w + sep, cap * 2), QtCore.Qt.AlignHCenter,
                   nav.get("back", "back"))
        gx = x + back_w + sep
        pic.keycap(p, QtCore.QRectF(gx, top, space_w, kh), "Space", size=kh * 0.32)
        pic.keycap(p, QtCore.QRectF(gx + space_w + gap, top, arrow_w, kh), "→", size=kh * 0.48)
        pic.mouse(p, QtCore.QRectF(gx + space_w + arrow_w + 2 * gap, top, mouse_w, kh))
        label = nav.get("start" if last else "next", "next")
        self._font(p, cap, bold=True); p.setPen(QtGui.QColor(pic.ACCENT if last else TEXT))
        p.drawText(QtCore.QRectF(gx, top + kh + 10, group_w, cap * 2), QtCore.Qt.AlignHCenter, label)
        self._font(p, sz["small"]); p.setPen(QtGui.QColor(LABEL))
        p.drawText(QtCore.QRectF(0, self.height() - sz["small"] * 2.2, w - 24, sz["small"] * 2),
                   QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, f"Esc  {nav.get('esc', 'cancel')}")

    def _paint_dots(self, p, y):
        page = self.page
        n, i = page["total"], page["index"]
        r, step = 6.0, 26.0
        x0 = self.width() / 2 - (n - 1) * step / 2
        for k in range(n):
            p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(CUE if k == i else (TEXT if k < i else DIM)))
            p.drawEllipse(QtCore.QPointF(x0 + k * step, y), r if k == i else r * 0.7, r if k == i else r * 0.7)

    def _paint_page(self, p):
        page, sz = self.page, self._sizes()
        w, h = self.width(), self.height()
        margin = w * 0.08
        self._paint_dots(p, 28)
        fm = self._font(p, sz["title"], bold=True); p.setPen(QtGui.QColor(LIT))
        title_rect = QtCore.QRectF(margin, 48, w - 2 * margin, fm.height() * 1.4)
        p.drawText(title_rect, QtCore.Qt.AlignCenter, page["title"])
        nav_top = h - sz["key"] - sz["small"] * 4.2
        top = title_rect.bottom() + 16
        icon, lines = page.get("icon"), page.get("lines", [])
        if page.get("icons"):                                         # notes: one pictogram per line, left-aligned
            row_h = (nav_top - top - 16) / max(1, len(lines))
            ic = _clamp(row_h * 0.62, 40, 100)
            col_w = min(w - 2 * margin, ic + 36 + sz["body"] * 30)
            x0 = (w - col_w) / 2
            flags = QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter | QtCore.Qt.TextWordWrap
            rects = [QtCore.QRectF(x0 + ic + 36, top + k * row_h + 4, col_w - ic - 36, row_h - 8) for k in range(len(lines))]
            size = self._fit_size(list(zip(lines, rects)), sz["body"], 15, flags)
            for k, (name, line) in enumerate(zip(page["icons"], lines)):
                y = top + k * row_h
                pic.ICONS[name](p, QtCore.QRectF(x0, y + (row_h - ic) / 2, ic, ic))
                self._font(p, size); p.setPen(QtGui.QColor(TEXT))
                p.drawText(rects[k], flags, line)
        else:
            ill_h = (nav_top - top) * (0.46 if page.get("demo") else 0.38)
            ill = QtCore.QRectF(margin, top, w - 2 * margin, ill_h)
            if page.get("demo"):
                self._paint_demo(p, ill)
            elif icon in pic.ICONS:
                aspect = {"session": 3.6, "task": 3.3, "breaks": 2.3, "ready": 3.6}.get(icon, 1.0)
                ih = min(ill.height() * 0.86, ill.width() / aspect)
                box = QtCore.QRectF(ill.center().x() - ih * aspect / 2, ill.center().y() - ih / 2, ih * aspect, ih)
                pic.ICONS[icon](p, box)
            text = QtCore.QRectF(margin, ill.bottom() + 18, w - 2 * margin, nav_top - ill.bottom() - 48)
            flags = QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop | QtCore.Qt.TextWordWrap
            body = "\n\n".join(lines)
            self._font(p, self._fit_size([(body, text)], sz["body"], 15, flags)); p.setPen(QtGui.QColor(TEXT))
            p.drawText(text, flags, body)
        self._paint_nav(p, nav_top)

    def _paint_demo(self, p, rect):
        """The example: the real grid, labels included, with the target outlined and flashing slowly."""
        size = min(rect.width(), rect.height()) / GRID
        x0, y0 = rect.center().x() - size * GRID / 2, rect.top()
        lf = self._font(p, _clamp(size * 0.13, 11, 18))
        for cell in range(GRID * GRID):
            r, c = divmod(cell, GRID)
            center = QtCore.QPointF(x0 + (c + 0.5) * size, y0 + (r + 0.42) * size)
            radius = size * 0.2
            p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(LIT if cell == self.lit else DIM))
            p.drawEllipse(center, radius, radius)
            if cell == self.cue:
                p.setPen(QtGui.QPen(QtGui.QColor(CUE), 3)); p.setBrush(QtCore.Qt.NoBrush)
                p.drawEllipse(center, radius * 1.45, radius * 1.45)
            if cell in COMMANDS:
                p.setPen(QtGui.QColor(LABEL))
                p.drawText(QtCore.QRectF(center.x() - size / 2, center.y() + radius * 1.5, size, lf.height() * 1.3),
                           QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, COMMANDS[cell])

    def _paint_countdown(self, p):
        number, caption, fraction = self.countdown
        w, h, sz = self.width(), self.height(), self._sizes()
        self._font(p, sz["body"] * 1.15); p.setPen(QtGui.QColor(TEXT))
        p.drawText(QtCore.QRectF(0, h * 0.12, w, sz["body"] * 2.5), QtCore.Qt.AlignCenter, caption)
        radius = min(w, h) * 0.22
        center = QtCore.QPointF(w / 2, h * 0.56)
        pic.ring(p, center, radius, fraction)
        self._font(p, radius * 0.9, bold=True); p.setPen(QtGui.QColor(LIT))
        p.drawText(QtCore.QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius),
                   QtCore.Qt.AlignCenter, str(number))

    def _paint_rest(self, p):
        seconds, title, hint = self.rest
        w, h, sz = self.width(), self.height(), self._sizes()
        fm = self._font(p, sz["title"], bold=True); p.setPen(QtGui.QColor(LIT))
        p.drawText(QtCore.QRectF(0, h * 0.1, w, fm.height() * 1.5), QtCore.Qt.AlignCenter, title)
        s = min(w, h) * 0.24
        pic.pause(p, QtCore.QRectF(w / 2 - s / 2, h * 0.27, s, s), color=LABEL)
        self._font(p, sz["title"] * 1.3, bold=True); p.setPen(QtGui.QColor(TEXT))
        p.drawText(QtCore.QRectF(0, h * 0.27 + s + 20, w, sz["title"] * 2), QtCore.Qt.AlignCenter, f"{seconds:.0f} s")
        self._font(p, sz["body"]); p.setPen(QtGui.QColor(LABEL))
        p.drawText(QtCore.QRectF(0, h * 0.27 + s + 30 + sz["title"] * 2, w, sz["body"] * 2.5), QtCore.Qt.AlignCenter, hint)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing); p.setRenderHint(QtGui.QPainter.TextAntialiasing)
        p.fillRect(self.rect(), QtGui.QColor(BG))
        if self.page is not None: self._paint_page(p); p.end(); return
        if self.countdown is not None: self._paint_countdown(p); p.end(); return
        if self.rest is not None: self._paint_rest(p); p.end(); return
        for cell in range(GRID * GRID):                              # session: the stimulus grid
            rect = self.cell_rect(cell)
            radius = rect.width() * 0.17
            center = rect.center() - QtCore.QPointF(0, rect.height() * 0.06)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(LIT if cell == self.lit else DIM))
            p.drawEllipse(center, radius, radius)
            if cell == self.cue:
                p.setPen(QtGui.QPen(QtGui.QColor(CUE), 4)); p.setBrush(QtCore.Qt.NoBrush)
                p.drawEllipse(center, radius * 1.45, radius * 1.45)
            if self.show_labels and cell in COMMANDS:
                p.setPen(QtGui.QColor(LABEL))
                f = p.font(); f.setPointSizeF(max(11.0, rect.height() * 0.075)); p.setFont(f)
                p.drawText(QtCore.QRectF(rect.left(), center.y() + radius * 1.6, rect.width(), rect.height() * 0.2),
                           QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, COMMANDS[cell])
        if self.message:
            self._font(p, self._sizes()["body"]); p.setPen(QtGui.QColor(TEXT))
            p.drawText(QtCore.QRectF(0, self.height() - 66, self.width(), 50), QtCore.Qt.AlignCenter, self.message)
        p.fillRect(QtCore.QRectF(0, self.height() - 24, 24, 24), QtGui.QColor(LIT if self.lit is not None else BG))
        p.end()
        if self.pending:                                            # first paint after each change
            now = self.clock()
            tags, self.pending = self.pending, []
            for tag in tags: self.on_painted(tag, now)

    # ---- input ---------------------------------------------------------------------------------------------------
    def keyPressEvent(self, ev):
        if ev.key() in (QtCore.Qt.Key_F, QtCore.Qt.Key_F11) and not ev.isAutoRepeat():
            self.showNormal() if self.isFullScreen() else self.showFullScreen(); return
        if ev.key() == QtCore.Qt.Key_Escape and self.isFullScreen() and self.page is None and self.countdown is None:
            self.showNormal(); return                                # during instructions Esc means "cancel"
        self.on_key(ev)                                             # the extension decides (mode-dependent)

    def mousePressEvent(self, ev):
        if ev.button() == QtCore.Qt.LeftButton: self.on_click()
        super().mousePressEvent(ev)

    def closeEvent(self, ev):
        self.on_closed()
        super().closeEvent(ev)
