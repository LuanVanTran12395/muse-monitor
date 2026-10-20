"""The Muse Cube window: a perspective cube drawn with QPainter, in two styles from the reference pictures.

    Glass    clear cubies with a light rim; the stickers of the hidden faces show through, fainter — the back of the
             cube can be read without turning it (default: fewer commands for a head / eye user)
    Classic  grey cubies, hidden faces culled

Layers: a face is selected (pointing, click), then the layer behind it is chosen (nod, click again, Tab): outer →
middle (3×3) → opposite → outer… The selected layer is lit with a thick outline and the rest of the cube is dimmed.

Right: the 2D panel (flat.py), "Three ring clusters" or "Cross", following the same state, selection, hint and
animations; its ring buttons (and the rings themselves, Shift = counter-clockwise) turn layers. P shows / hides it.

Top left: ● UNSOLVED / ● SOLVED. Top right: the Glass | Classic switch. Bottom: a thin dock (size, moves, clock, keys).
Every command goes through ``command(name, *args)`` in SCREEN terms; the head controller (controller.py) calls the same
entry point and passes its state with ``set_extra`` (head live, tilt progress, calibration / tilt-test overlay).
Animations show the committed state un-turning (the model is updated at once, so it is always right). A move that
arrives during an animation waits for it (a queue of at most QUEUE_MAX), so every move is seen for its full 250 ms.
While a calibration / tilt-test overlay is open the game is locked: no key, click or move reaches the cube.
Hit boxes are recorded at paint time, as in the food_order kiosk.
"""
import math
import time
from collections import deque

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from .cube import COLOURS, FACE_OF, NORMAL, View, parts, rot90
from .flat import NET_AT, Rings, net_cell
from . import pictos
from .game import Game
from .text import t
from .tutorial import SOLVE_DEPTH, STEPS, Tutorial

PALETTE = {"white": (236, 236, 236), "yellow": (236, 224, 142), "red": (223, 98, 88), "blue": (80, 111, 216),
           "orange": (236, 181, 99), "green": (124, 196, 138)}
ACCENT = QtGui.QColor(143, 163, 255)
HINT = QtGui.QColor(255, 196, 92)
OK_GREEN = QtGui.QColor(125, 211, 160)
MUTED = QtGui.QColor(154, 163, 181)
BASE_YAW, BASE_PITCH = -28.0, 24.0
TURN_S, VIEW_S = 0.25, 0.32
QUEUE_MAX = 3                                  # moves waiting behind an animation; more are dropped
ANIMATED = ("turn", "undo", "view")
LIGHT = np.array([-0.45, 0.75, 0.55]) / np.linalg.norm([-0.45, 0.75, 0.55])
KEY_FACE = {QtCore.Qt.Key_U: "U", QtCore.Qt.Key_D: "D", QtCore.Qt.Key_L: "L", QtCore.Qt.Key_R: "R",
            QtCore.Qt.Key_F: "F", QtCore.Qt.Key_B: "B"}
KEY_SLICE = {QtCore.Qt.Key_M: "L", QtCore.Qt.Key_E: "D", QtCore.Qt.Key_S: "F"}     # 3×3 middle slices (as L, D, F)
KEY_VIEW = {QtCore.Qt.Key_Right: ("y", 1), QtCore.Qt.Key_Left: ("y", -1),
            QtCore.Qt.Key_Up: ("x", -1), QtCore.Qt.Key_Down: ("x", 1)}


def rot(axis, deg):
    """Float rotation matrix about a unit axis (counter-clockwise looking from + along it)."""
    a = np.asarray(axis, float); a /= np.linalg.norm(a)
    th = math.radians(deg); c, s = math.cos(th), math.sin(th)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return c * np.eye(3) + s * k + (1 - c) * np.outer(a, a)


def rounded_square(r=0.24, seg=4):
    """Unit rounded square outline in [-1, 1]², corner radius r."""
    pts = []
    for cx, cy, a0 in ((1 - r, 1 - r, 0), (-1 + r, 1 - r, 90), (-1 + r, -1 + r, 180), (1 - r, -1 + r, 270)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return np.array(pts)


BODY_SHAPE, STICKER_SHAPE = rounded_square(0.22), rounded_square(0.2)
PLANE = {(1, 0, 0): ((0, 0, -1), (0, 1, 0)), (-1, 0, 0): ((0, 0, 1), (0, 1, 0)),
         (0, 1, 0): ((1, 0, 0), (0, 0, -1)), (0, -1, 0): ((1, 0, 0), (0, 0, 1)),
         (0, 0, 1): ((1, 0, 0), (0, 1, 0)), (0, 0, -1): ((-1, 0, 0), (0, 1, 0))}


def shade(rgb, k, alpha=255):
    return QtGui.QColor(*(max(0, min(255, int(c * k))) for c in rgb), alpha)


class _Caption(QtWidgets.QWidget):
    """A strip over the bottom of head_motion_plus's 3D head: covers its own English line (clipped at the game's width)
    with the game's caption — the camera state, localized."""

    def __init__(self, parent):
        super().__init__(parent)
        self.text, self.colour = "", MUTED
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(11, 15, 24))
        f = QtGui.QFont("Menlo"); f.setStyleHint(QtGui.QFont.Monospace); f.setPointSizeF(max(8.5, self.height() * 0.36))
        p.setFont(f); p.setPen(self.colour)
        p.drawText(self.rect().adjusted(4, 0, -4, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignHCenter, self.text)
        p.end()


class CubeWindow(QtWidgets.QWidget):
    def __init__(self, n=2, depth=3, style="glass", lang="vi", on_change=None, on_closed=None, seed=None,
                 panel=True, panel_mode="rings", tutorial=False):
        super().__init__()
        self.setWindowTitle("Muse Cube")
        self.panel, self.panel_mode = bool(panel), panel_mode if panel_mode in ("rings", "cross") else "rings"
        self.setMinimumSize(800, 640)
        want = (1560 if self.panel else 1100, 920)
        screen = QtGui.QGuiApplication.primaryScreen()               # never larger than the screen
        if screen is not None:
            avail = screen.availableGeometry()
            want = (min(want[0], max(800, avail.width() - 40)), min(want[1], max(640, avail.height() - 40)))
        self.resize(*want)
        self.cube_w = 1100
        self.area = (0.0, 1100.0)                  # (left, width) of the cube area, right of the left column
        self.setFocusPolicy(QtCore.Qt.StrongFocus); self.setMouseTracking(False)
        self.game = Game(n, depth, seed)
        self.real = (n, depth)                     # the real game, after the tutorial
        self.tutorial = None
        self.style, self.lang = style if style in ("glass", "classic") else "glass", lang
        self.on_change, self.on_closed = on_change or (lambda *a: None), on_closed or (lambda: None)
        self.selected = None                       # screen face chosen (pointing / mouse), then ↻ / ↺
        self.depth = 0                             # the layer behind it: 0 outer … n − 1 opposite
        self.anim = None
        self.queue = deque()
        self.yaw, self.pitch = 0.0, 0.0            # mouse orbit on top of the base angle (a look, not a command)
        self.hits, self.stickers = [], []
        self._press = None
        self.extra = {}                            # from the head controller (empty: keyboard / mouse only)
        self.head_canvas = None                    # head_motion_plus's 3D head (never a camera image)
        self._cover = None                         # the localized caption over its bottom line
        self.scramble_armed_until = 0.0            # mid-game, the scramble button needs a second click
        self.on_key = None                         # controller's keys first (K, T, Home, Esc)
        self.timer = QtCore.QTimer(self); self.timer.setInterval(16); self.timer.timeout.connect(self._tick)
        self.clock = QtCore.QTimer(self); self.clock.setInterval(250); self.clock.timeout.connect(self.update)
        self.clock.start()
        if tutorial: self.start_tutorial()
        self._describe()

    # ---- commands (screen terms) ---------------------------------------------------------------------------------
    def locked(self):
        """A calibration / tilt-test overlay is open: the cube must not change."""
        return bool(self.extra.get("overlay"))

    def command(self, name, *args):
        if self.locked() and name in ANIMATED + ("new", "hint", "select", "layer"): return False
        if name in ANIMATED and self.anim is not None:
            if len(self.queue) >= QUEUE_MAX: return False
            self.queue.append((name, args)); return True
        if name == "new":
            if self.tutorial is not None:                       # the tutorial sets its own cubes; the real game
                if args: self.real = (args[0], args[1] if len(args) > 1 else self.real[1])     # starts after it
                return False
            self.queue.clear(); self._finish_anim()
        return self._run(name, *args)

    # ---- tutorial ------------------------------------------------------------------------------------------------
    def start_tutorial(self):
        self.queue.clear(); self._finish_anim()
        self.tutorial = Tutorial(time.monotonic)
        self.game.new(self.real[0], 0)                          # practice cube: unscrambled, never finishes
        self.selected, self.depth = None, 0
        self.update()

    def _tutorial_step(self, name):
        tut = self.tutorial
        if tut is None or not tut.on_command(name, self): return
        if tut.step in SOLVE_DEPTH:
            self.queue.clear(); self._finish_anim()
            self.game.new(self.real[0], SOLVE_DEPTH[tut.step])
            self.selected, self.depth = None, 0

    def finish_tutorial(self):
        """Into the real game (also when the tutorial is skipped)."""
        if self.tutorial is None: return
        self.tutorial = None
        self.queue.clear(); self._finish_anim()
        self.game.new(*self.real)
        self.selected, self.depth = None, 0
        self.on_change("tutorial_done", True)
        self._describe(); self.update()

    def _run(self, name, *args):
        g = self.game
        if name == "turn":
            face, turns = args[:2]
            m = g.turn(face, turns, args[2] if len(args) > 2 else 0)
            if m: self._animate(m)
        elif name == "undo":
            m = g.undo()
            if m: self._animate(m, undo=True)
        elif name == "view":
            axis, q = args
            g.turn_view(axis, q); self.selected = None
            self.anim = dict(kind="view", axis=axis, q=q, t0=time.monotonic(), dur=VIEW_S); self.timer.start()
        elif name == "hint":
            g.show_hint()
        elif name == "new":
            g.new(*args); self.selected = None; self.depth = 0
        elif name == "style":
            self.style = args[0] if args else ("classic" if self.style == "glass" else "glass")
            self.on_change("style", self.style)
        elif name == "confirm":                    # nod / Enter: into the game after the tutorial, or a new game
            if self.tutorial is not None and self.tutorial.finished: self.finish_tutorial(); return True
            if self.tutorial is None and g.solved: g.new(); self.selected = None; self.depth = 0
            else: return False
        elif name == "tutorial_skip":
            self.finish_tutorial(); return True
        elif name == "panel":
            self.panel = bool(args[0]) if args else not self.panel
            self.on_change("panel", self.panel)
        elif name == "panel_mode":
            self.panel_mode = args[0]
            self.on_change("panel_mode", self.panel_mode)
        elif name == "lang":
            self.lang = args[0] if args else ("en" if self.lang == "vi" else "vi")
            self.on_change("lang", self.lang)
        elif name == "select":
            if args[0] != self.selected: self.depth = 0
            self.selected = args[0]
            if len(args) > 1: self.depth = args[1] % g.n
        elif name == "layer":
            if not self.selected: return False
            self.depth = (self.depth + (args[0] if args else 1)) % g.n
        else:
            return False
        self._tutorial_step(name)
        self._describe(); self.update()
        return True

    def set_head_canvas(self, widget):
        """The 3D head model, top left under the status (clear of the turn buttons at the bottom); a camera, when on,
        only recenters it."""
        self.head_canvas = widget
        widget.setParent(self); widget.show(); widget.lower()
        self._place_canvas()

    COL_W = 200                                    # the left column (3D head, EOG / EMG), × unit

    def _place_canvas(self):
        if self.head_canvas is None: return
        u = self._unit()
        cw = self.cube_w if self.panel_shown() else self.width()
        self.head_canvas.setVisible(cw >= 640)
        self.head_canvas.setGeometry(int(8 * u), int(62 * u), int(self.COL_W * u), int(190 * u))
        # our own caption over HeadCanvas's last line (English, clipped at this width): the camera state, localized
        if self._cover is None:
            self._cover = _Caption(self)
        g = self.head_canvas.geometry()
        self._cover.setGeometry(g.x(), g.bottom() - int(26 * u), g.width(), int(28 * u))
        self._cover.setVisible(self.head_canvas.isVisible()); self._cover.raise_()

    def left_column(self):
        """Width the cube area keeps free on the left (0 when nothing is shown there)."""
        u = self._unit()
        head = self.head_canvas is not None and self.head_canvas.isVisible()
        return (8 + self.COL_W + 12) * u if (head or self.extra.get("signals")) else 0.0

    def _canvas_right(self):
        c = self.head_canvas
        return c.geometry().right() if c is not None and c.isVisible() else 0

    def resizeEvent(self, e):
        super().resizeEvent(e); self._place_canvas()

    def set_extra(self, extra):
        self.extra = extra or {}
        self.update()

    def _animate(self, move, undo=False):
        face, turns, depth = parts(move)
        q = (-turns if undo else turns) % 4
        self.anim = dict(kind="turn", face=face, depth=depth, signed={1: 1, 2: 2, 3: -1}[q],   # 3 quarters = one back
                         t0=time.monotonic(), dur=TURN_S * (1.4 if q == 2 else 1))
        self.timer.start()

    def _finish_anim(self):
        self.anim = None; self.timer.stop()

    def _tick(self):
        if self.anim and time.monotonic() - self.anim["t0"] >= self.anim["dur"]:
            self._finish_anim()
            while self.queue and self.anim is None:              # the next waiting move, if any
                name, args = self.queue.popleft()
                if not self.locked(): self._run(name, *args)
        self.update()

    def settle(self):
        """Finish the animation and run every waiting move at once (tests; closing)."""
        while self.anim is not None or self.queue:
            self._finish_anim()
            if self.queue:
                name, args = self.queue.popleft()
                self._run(name, *args)

    def _progress(self):
        if not self.anim: return 1.0
        x = min(1.0, (time.monotonic() - self.anim["t0"]) / self.anim["dur"])
        return 1 - (1 - x) ** 3                    # ease out

    # ---- input ---------------------------------------------------------------------------------------------------
    def keyPressEvent(self, e):
        k, shift = e.key(), bool(e.modifiers() & QtCore.Qt.ShiftModifier)
        if self.on_key is not None and self.on_key(k): e.accept(); return
        if self.locked():                                   # overlay open: only the controller's keys (Esc…)
            e.accept(); return
        if k in KEY_FACE:
            self.command("select", KEY_FACE[k], 0); self.command("turn", KEY_FACE[k], -1 if shift else 1)
        elif k in KEY_SLICE and self.game.n == 3:
            self.command("select", KEY_SLICE[k], 1); self.command("turn", KEY_SLICE[k], -1 if shift else 1, 1)
        elif k == QtCore.Qt.Key_Tab: self.command("layer", 1)
        elif k in KEY_VIEW: self.command("view", *KEY_VIEW[k])
        elif k == QtCore.Qt.Key_Backspace: self.command("undo")
        elif k == QtCore.Qt.Key_H: self.command("hint")
        elif k == QtCore.Qt.Key_Space: self.scramble_clicked()          # mid-game: press twice, as the button
        elif k == QtCore.Qt.Key_G: self.command("style")
        elif k == QtCore.Qt.Key_N: self.command("lang")
        elif k == QtCore.Qt.Key_P: self.command("panel")
        elif k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter): self.command("confirm")
        elif k == QtCore.Qt.Key_F1: self.start_tutorial()
        elif k == QtCore.Qt.Key_Escape and self.tutorial is not None: self.command("tutorial_skip")
        elif k == QtCore.Qt.Key_F11: self.showNormal() if self.isFullScreen() else self.showFullScreen()
        else: super().keyPressEvent(e); return
        e.accept()

    def mousePressEvent(self, e):
        self._press = None if self.locked() else (e.position(), self.yaw, self.pitch, False)

    def mouseMoveEvent(self, e):
        if not self._press: return
        p0, y0, p_0, _ = self._press
        d = e.position() - p0
        if abs(d.x()) + abs(d.y()) > 6:
            self._press = (p0, y0, p_0, True)
            self.yaw = max(-35.0, min(35.0, y0 + d.x() * 0.3))
            self.pitch = max(-15.0, min(30.0, p_0 - d.y() * 0.3))
            self.update()

    def mouseReleaseEvent(self, e):
        press, self._press = self._press, None
        if press is None or press[3]: return       # overlay open, or it was a drag (orbit)
        act = self.hit_at(e.position())
        if act is None: return
        shift = bool(e.modifiers() & QtCore.Qt.ShiftModifier)
        if act[0] == "style": self.command("style", act[1])
        elif act[0] == "panel_mode": self.command("panel_mode", act[1])
        elif act[0] == "scramble": self.scramble_clicked()
        elif act[0] == "tutorial_skip": self.command("tutorial_skip")
        elif act[0] == "tutorial_done": self.command("confirm")
        elif act[0] == "ring_turn": self.command("turn", act[1], act[2], act[3])
        elif act[0] == "ring": self.command("turn", act[1], -1 if shift else 1, act[2])
        elif act[0] == "sticker":                  # a click picks the face; again on it: the next layer
            self.command("layer", 1) if act[1] == self.selected else self.command("select", act[1])
        elif act[0] == "layer": self.command("layer", 1)
        elif act[0] == "turn_sel" and self.selected: self.command("turn", self.selected, act[1], self.depth)

    def mouseDoubleClickEvent(self, e):
        if self.hit_at(e.position()) is None: self.yaw = self.pitch = 0.0; self.update()

    def hit_at(self, pos):
        for poly, act in reversed(self.hits):
            if poly.containsPoint(QtCore.QPointF(pos), QtCore.Qt.OddEvenFill): return act
        return None

    def closeEvent(self, e):
        self.timer.stop(); self.clock.stop(); self.on_closed(); super().closeEvent(e)

    # ---- drawing -------------------------------------------------------------------------------------------------
    def _unit(self):
        """Layout scale: 1.0 at 1280×800 (a common laptop screen), between 0.6 and 1.1."""
        return max(0.6, min(1.1, self.width() / 1280, self.height() / 800))

    def _font(self, p, size, bold=False, mono=False):
        f = QtGui.QFont("Menlo" if mono else self.font().family())
        if mono: f.setStyleHint(QtGui.QFont.Monospace); f.setLetterSpacing(QtGui.QFont.PercentageSpacing, 112)
        f.setPointSizeF(size * max(0.85, self._unit())); f.setBold(bold); p.setFont(f)      # text never below 0.85

    def paintEvent(self, _e):
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        bg = QtGui.QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QtGui.QColor(14, 20, 34)); bg.setColorAt(1, QtGui.QColor(4, 6, 10))
        p.fillRect(self.rect(), bg)
        self.hits = []
        panel_w = self.panel_width() if self.panel_shown() else 0
        if self.head_canvas is not None and (w - panel_w) != self.cube_w: self.cube_w = w - panel_w; self._place_canvas()
        self.cube_w = cw = w - panel_w
        x0 = self.left_column()                    # the cube, its messages and buttons stay right of the left column
        self.area = (x0, cw - x0)
        n_hits = len(self.hits)
        p.save(); p.translate(x0, 0)
        self._cube(p, cw - x0, h); self._messages(p, cw - x0, h); self._flash(p, cw - x0, h)
        p.restore()
        for poly, _ in self.hits[n_hits:]: poly.translate(x0, 0)          # hit boxes back to window coordinates
        for poly, _ in self.stickers: poly.translate(x0, 0)
        if panel_w: self._panel(p, QtCore.QRectF(cw, 84 * self._unit(), panel_w - 18 * self._unit(), h - 150 * self._unit()))
        self._status(p); self._switch(p, w); self._dock(p, w, h)
        if self.tutorial is not None: self._tutorial_card(p, cw)
        else: self._scramble_button(p, cw, h)
        if self.head_canvas is not None and self.head_canvas.isVisible(): self._canvas_caption(p)
        if self.extra.get("signals"): self._signal_strip(p, cw)
        if self.extra.get("overlay"):
            self._overlay(p, w, h, self.extra["overlay"])
            self.hits.append((QtGui.QPolygonF(QtCore.QRectF(self.rect())), ("block",)))   # nothing below is clickable
        p.end()

    def _view_matrix(self):
        g, e = self.game, self._progress()
        R = g.view.R.astype(float)
        if self.anim and self.anim["kind"] == "view":
            R = rot(View.TURNS[self.anim["axis"]], -self.anim["q"] * 90 * (1 - e)) @ R
        return rot((1, 0, 0), BASE_PITCH + self.pitch) @ rot((0, 1, 0), BASE_YAW + self.yaw) @ R

    def _cube(self, p, w, h):
        g, n, e = self.game, self.game.n, self._progress()
        M = self._view_matrix()
        D = n * 4.2
        u = self._unit()
        top = (216 if self.tutorial is not None else 64) * u           # the tutorial card / the status
        bottom = h - self.bottom_reserve()                              # the dock and what is shown under the cube
        S = min(w * 0.9, (bottom - top) * 1.45)
        f = 0.43 * S * D / (n * 0.95)
        cx, cy = w / 2, (top + bottom) / 2 + 0.02 * (bottom - top)
        cam = np.array([0.0, 0.0, D])

        def proj(q):
            k = f / (D - q[:, 2])
            return np.stack((cx + q[:, 0] * k, cy - q[:, 1] * k), axis=1)

        # soft shadow
        sy = cy + f * (n * 0.62) / D + n * 0.0
        rad = QtGui.QRadialGradient(cx, sy, f * n * 0.55 / D)
        rad.setColorAt(0, QtGui.QColor(0, 0, 0, 120)); rad.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
        p.save(); p.translate(cx, sy); p.scale(1.0, 0.22); p.translate(-cx, -sy)
        p.setPen(QtCore.Qt.NoPen); p.setBrush(rad); p.drawEllipse(QtCore.QPointF(cx, sy), f * n * 0.55 / D, f * n * 0.55 / D)
        p.restore()

        moving = set()
        A = np.eye(3)
        if self.anim and self.anim["kind"] == "turn":
            face = self.anim["face"]
            A = rot(NORMAL[face], 90 * self.anim["signed"] * (1 - e))
            moving = {id(c) for c in g.cube.layer(face, self.anim["depth"])}
        lit = {id(c) for c in g.cube.layer(g.view.logical(self.selected), self.depth)} if self.selected else set()
        hinted = {id(c) for c in g.cube.layer(g.view.logical(g.hint[0]), g.hint[3])} if g.hint else set()
        glass = self.style == "glass"
        hs = 0.47                                       # half size of a cubie (spacing 1, gap 0.06)
        items = []
        for c in g.cube.cubies:
            Mc = M @ A if id(c) in moving else M
            centre = c["pos"] * 0.5
            for nrm, (u, v) in PLANE.items():
                nv, uv, vv = np.array(nrm, float), np.array(u, float), np.array(v, float)
                fc = centre + nv * hs
                fcc = Mc @ fc
                ncam = Mc @ nv
                facing = float(np.dot(ncam, cam - fcc)) > 0
                lam = max(0.0, float(np.dot(ncam, LIGHT)))
                colour = c["stickers"].get(nrm)
                if not glass and not facing: continue
                body = fc[None, :] + (BODY_SHAPE[:, :1] * uv + BODY_SHAPE[:, 1:] * vv) * hs
                items.append((float(np.linalg.norm(cam - fcc)), 0, "body", proj((Mc @ body.T).T), facing, lam, None, None, id(c)))
                if colour is not None:
                    sc = fc + nv * 0.012
                    st = sc[None, :] + (STICKER_SHAPE[:, :1] * uv + STICKER_SHAPE[:, 1:] * vv) * hs * 0.84
                    logical = FACE_OF[nrm]                      # the logical face this sticker is on
                    items.append((float(np.linalg.norm(cam - Mc @ sc)), 1, "sticker", proj((Mc @ st.T).T), facing, lam,
                                  colour, logical, id(c)))
        items.sort(key=lambda it: (-it[0], it[1]))
        self.stickers = []
        dim = bool(lit)                                  # a layer is selected: the rest steps back
        for dist, _, kind, pts, facing, lam, colour, logical, cid in items:
            poly = QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in pts])
            on = cid in lit
            if kind == "body":
                if glass:
                    edge = QtGui.QColor(ACCENT) if on else QtGui.QColor(255, 255, 255, (150 if facing else 55) // (2 if dim else 1))
                    if on: edge.setAlpha(235 if facing else 120)
                    p.setPen(QtGui.QPen(edge, (2.6 if on else 1.4) * self._unit()))
                    p.setBrush(QtGui.QColor(143, 163, 255, 46) if on and facing else QtGui.QColor(225, 232, 245, 26 if facing else 12))
                else:
                    p.setPen(QtGui.QPen(ACCENT if on and facing else QtGui.QColor(40, 44, 52), 2.4 * self._unit() if on and facing else 1.0))
                    p.setBrush(shade((110, 116, 126), (0.62 + 0.5 * lam) * (0.55 if dim and not on else 1.0)))
                p.drawPolygon(poly)
                continue
            rgb = PALETTE[colour]
            alpha = 245 if facing else 150               # glass: the hidden faces show through, fainter
            k = (0.82 + 0.26 * lam) if facing else 0.9
            if dim and not on: k, alpha = k * 0.5, int(alpha * (0.75 if facing else 0.45))
            r = poly.boundingRect()
            grad = QtGui.QLinearGradient(r.topLeft(), r.bottomRight())
            grad.setColorAt(0, shade(rgb, k * 1.06, alpha)); grad.setColorAt(1, shade(rgb, k * 0.94, alpha))
            p.setPen(QtCore.Qt.NoPen); p.setBrush(grad); p.drawPolygon(poly)
            if facing and (on or cid in hinted):
                p.setPen(QtGui.QPen(ACCENT if on else HINT, 3.6 * self._unit())); p.setBrush(QtCore.Qt.NoBrush)
                p.drawPolygon(poly)
            if facing:
                self.hits.append((poly, ("sticker", g.view.screen(logical))))
                self.stickers.append((poly, g.view.screen(logical)))
        self._hint_arrow(p, M, proj, cam)

    def _hint_arrow(self, p, M, proj, cam):
        """The way-back step as a curved arrow on the face it is seen from (when that face is in view)."""
        g = self.game
        if not g.hint: return
        face, turns = g.hint[0], g.hint[1]
        logical = g.view.logical(face)
        nrm = np.array(NORMAL[logical], float)
        u_ax, v_ax = (np.array(a, float) for a in PLANE[NORMAL[logical]])
        if np.dot(np.cross(u_ax, v_ax), nrm) < 0: v_ax = -v_ax         # θ increasing = counter-clockwise from outside
        centre = nrm * (g.n / 2 + 0.06)
        if float(np.dot(M @ nrm, cam - M @ centre)) <= 0: return       # the face is turned away
        rad = g.n * 0.3
        if turns == 3: angles = np.linspace(math.radians(-130), math.radians(130), 28)          # counter-clockwise
        else: angles = np.linspace(math.radians(130), math.radians(-130), 28)                   # clockwise (and 2×)
        pts3 = np.array([centre + rad * (math.cos(a) * u_ax + math.sin(a) * v_ax) for a in angles])
        pts = proj((M @ pts3.T).T)
        u = self._unit()
        path = QtGui.QPainterPath(QtCore.QPointF(*pts[0]))
        for x, y in pts[1:]: path.lineTo(x, y)
        p.setBrush(QtCore.Qt.NoBrush)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 160), 9 * u, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)); p.drawPath(path)
        p.setPen(QtGui.QPen(HINT, 5 * u, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)); p.drawPath(path)
        tip, prev = pts[-1], pts[-3]
        ang = math.atan2(tip[1] - prev[1], tip[0] - prev[0]); k = 16 * u
        head = [QtCore.QPointF(*tip), QtCore.QPointF(tip[0] - k * math.cos(ang - 0.5), tip[1] - k * math.sin(ang - 0.5)),
                QtCore.QPointF(tip[0] - k * math.cos(ang + 0.5), tip[1] - k * math.sin(ang + 0.5))]
        p.setPen(QtCore.Qt.NoPen); p.setBrush(HINT); p.drawPolygon(QtGui.QPolygonF(head))
        if turns == 2:
            self._font(p, 14, bold=True); p.setPen(HINT)
            c2 = proj((M @ centre[:, None]).T)[0]
            p.drawText(QtCore.QRectF(c2[0] - 20 * u, c2[1] - 14 * u, 40 * u, 28 * u), QtCore.Qt.AlignCenter, "×2")

    def _status(self, p):
        u = self._unit()
        ok = self.game.solved
        col = OK_GREEN if ok else MUTED
        p.setPen(QtCore.Qt.NoPen); p.setBrush(col); p.drawEllipse(QtCore.QPointF(20 * u, 24 * u), 8 * u, 8 * u)
        self._font(p, 17, mono=True); p.setPen(col)
        p.drawText(QtCore.QRectF(38 * u, 6 * u, 400 * u, 36 * u), QtCore.Qt.AlignVCenter, t("solved" if ok else "unsolved", self.lang))
        head = self.extra.get("head")
        self._font(p, 11, mono=True); p.setPen(ACCENT if head else MUTED)
        p.drawText(QtCore.QRectF(38 * u, 38 * u, 520 * u, 22 * u), QtCore.Qt.AlignVCenter,
                   t("mode.head" if head else "mode.keys", self.lang))

    def _switch(self, p, w):
        u = self._unit()
        self._font(p, 17, bold=True)
        fm, pad = p.fontMetrics(), 8 * u
        widths = [fm.horizontalAdvance(t(k, self.lang)) + 40 * u for k in ("glass", "classic")]
        box = QtCore.QRectF(w - 18 * u - sum(widths) - 2 * pad, 0, sum(widths) + 2 * pad, 70 * u)
        p.setPen(QtGui.QPen(QtGui.QColor(42, 49, 66), 1.2)); p.setBrush(QtGui.QColor(22, 27, 38))
        p.drawRoundedRect(box, 16 * u, 16 * u)
        x = box.x() + pad
        for key, sw in zip(("glass", "classic"), widths):
            seg = QtCore.QRectF(x, box.y() + pad, sw, 54 * u); x += sw
            if self.style == key:
                p.setPen(QtCore.Qt.NoPen); p.setBrush(ACCENT); p.drawRoundedRect(seg, 11 * u, 11 * u)
                p.setPen(QtGui.QColor(11, 16, 32))
            else:
                p.setPen(QtGui.QColor(232, 234, 240))
            p.drawText(seg, QtCore.Qt.AlignCenter, t(key, self.lang))
            self.hits.append((QtGui.QPolygonF(seg), ("style", key)))

    def _dock(self, p, w, h):
        u, g = self._unit(), self.game
        y = h - 46 * u
        p.setPen(QtGui.QPen(QtGui.QColor(36, 42, 56), 1)); p.drawLine(QtCore.QPointF(0, y), QtCore.QPointF(w, y))
        self._font(p, 12, mono=True); p.setPen(MUTED)
        secs = int(g.elapsed())
        size = t("size.practice", self.lang, n=g.n) if g.practice else t("size", self.lang, n=g.n, d=g.depth)
        info = f"{size}   {t('moves', self.lang, n=g.moves)}   {secs // 60}:{secs % 60:02d}"
        if g.hinted: info += f"   · {t('hinted', self.lang)}"
        p.drawText(QtCore.QRectF(18 * u, y, w / 2, 46 * u), QtCore.Qt.AlignVCenter, info)
        if self.extra.get("head"):
            methods = self.extra.get("methods") or []         # by priority: select → turn → UNDO → layer → view → rest
            chips = [("↔", "chip.point")] + ([("↺↻", "chip.tilt")] if "tilt" in methods else []) + (
                     [("◉◉", "chip.blink")] if "blink" in methods else []) + (
                     [("≋", "chip.jaw")] if "jaw" in methods else []) + [
                     ("⇆", "chip.shake"), ("✓", "chip.nod_new" if g.solved else "chip.nod_layer"),
                     ("↩↪", "chip.full"), ("⤒", "chip.lookup"), ("H", "chip.hint"), ("Home", "chip.recenter")]
        else:
            chips = [("U D L R F B", "chip.turn"), ("⇧", "chip.prime"), ("⌫", "chip.undo"), ("Tab", "chip.layer"),
                     ("← → ↑ ↓", "chip.view")] + ([("M E S", "chip.slice")] if g.n == 3 else []) + [
                     ("H", "chip.hint"), ("Space", "chip.new"), ("G", "chip.style"), ("P", "chip.panel"), ("N", "chip.lang")]
        x = 18 * u + p.fontMetrics().horizontalAdvance(info) + 36 * u
        self.dock_hidden = 0
        self._font(p, 11)
        fm = p.fontMetrics()
        more_w = fm.horizontalAdvance("+99") + 16 * u
        for k, (cap, key) in enumerate(chips):      # most important first; what does not fit is counted in "+n"
            label = t(key, self.lang)
            wl, wc = fm.horizontalAdvance(label), fm.horizontalAdvance(cap) + 12 * u
            last = k == len(chips) - 1
            if x + wc + 5 * u + wl > w - 18 * u - (0 if last else more_w):
                r = QtCore.QRectF(x, y + 12 * u, more_w - 4 * u, 22 * u)
                p.setPen(QtGui.QPen(QtGui.QColor(60, 68, 88), 1)); p.setBrush(QtGui.QColor(24, 29, 41))
                p.drawRoundedRect(r, 5 * u, 5 * u); p.setPen(MUTED)
                p.drawText(r, QtCore.Qt.AlignCenter, f"+{len(chips) - k}")
                self.dock_hidden = len(chips) - k
                break
            r = QtCore.QRectF(x, y + 12 * u, wc, 22 * u)
            p.setPen(QtGui.QPen(QtGui.QColor(60, 68, 88), 1)); p.setBrush(QtGui.QColor(24, 29, 41))
            p.drawRoundedRect(r, 5 * u, 5 * u); p.setPen(QtGui.QColor(220, 224, 234)); p.drawText(r, QtCore.Qt.AlignCenter, cap)
            x += wc + 5 * u
            p.setPen(MUTED); p.drawText(QtCore.QRectF(x, y, wl, 46 * u), QtCore.Qt.AlignVCenter, label)
            x += wl + 16 * u

    def _pill(self, p, text, colour, cy, sub=None):
        u = self._unit()
        self._font(p, 15, bold=True)
        fm = p.fontMetrics(); wt = fm.horizontalAdvance(text) + 40 * u
        r = QtCore.QRectF((self.area[1] - wt) / 2, cy, wt, 44 * u)
        p.setPen(QtGui.QPen(colour, 1.4)); p.setBrush(QtGui.QColor(16, 21, 32, 230)); p.drawRoundedRect(r, 22 * u, 22 * u)
        p.setPen(colour); p.drawText(r, QtCore.Qt.AlignCenter, text)
        if sub:
            self._font(p, 11); p.setPen(MUTED)
            p.drawText(QtCore.QRectF(0, r.bottom() + 2 * u, self.area[1], 22 * u), QtCore.Qt.AlignHCenter, sub)
        return r

    def _messages(self, p, w, h):
        u, g = self._unit(), self.game
        y = h - 46 * u - 92 * u
        if g.solved:
            secs = int(g.elapsed())
            key = "done.hinted" if g.hinted else "done"
            self._pill(p, t(key, self.lang, time=f"{secs // 60}:{secs % 60:02d}", n=g.moves) + "  ·  " + t("again", self.lang),
                       OK_GREEN, y)
        elif g.hint:
            face, turns, left, depth = g.hint
            arrow = "↻" if turns == 1 else "↺" if turns == 3 else "↻↻"
            seen = t("hint.from", self.lang, face=t("face." + face, self.lang))
            self._pill(p, t("hint", self.lang, move=f"{self.layer_name(face, depth)}  {arrow} {seen}", left=left), HINT, y,
                       t("hint.note", self.lang))
        elif self.selected and self.extra.get("head") and self.extra.get("tilt_on"):
            self._layer_badge(p, w, y - 74 * u)
            self._font(p, 12); p.setPen(QtGui.QColor(200, 206, 222))
            p.drawText(QtCore.QRectF(0, y - 28 * u, w, 66 * u), QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, self.turn_hint())
            prog = self.extra.get("tilt", 0.0)              # the hold, filling towards the side being tilted
            bar = QtCore.QRectF(w / 2 - 160 * u, y + 42 * u, 320 * u, 10 * u)
            p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(36, 42, 56)); p.drawRoundedRect(bar, 5 * u, 5 * u)
            if prog:
                fill = QtCore.QRectF(w / 2, bar.y(), 160 * u * abs(prog), bar.height())
                if prog < 0: fill.moveRight(w / 2)
                p.setBrush(ACCENT); p.drawRoundedRect(fill, 5 * u, 5 * u)
            p.setBrush(QtGui.QColor(232, 234, 240)); p.drawRect(QtCore.QRectF(w / 2 - 1, bar.y() - 3 * u, 2, bar.height() + 6 * u))
        elif not self.selected and self.tutorial is None:   # nothing selected yet: how to start
            self._font(p, 13); p.setPen(MUTED)
            p.drawText(QtCore.QRectF(0, y + 6 * u, w, 26 * u), QtCore.Qt.AlignHCenter,
                       t("start.head" if self.extra.get("head") else "start.keys", self.lang))
        elif self.selected:                             # mouse buttons: no head, or tilt off / failed (the fallback)
            if self.extra.get("head"):
                self._font(p, 11); p.setPen(HINT if self.extra.get("tilt_failed") else MUTED)
                p.drawText(QtCore.QRectF(0, y - 120 * u, w, 64 * u), QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom,
                           self.turn_hint())
            self._layer_badge(p, w, y - 52 * u)
            for i, (key, turns) in enumerate((("ccw", -1), ("layer", 0), ("cw", 1))):
                r = QtCore.QRectF(w / 2 - 260 * u + i * 180 * u, y, 160 * u, 46 * u)
                if key == "layer":
                    p.setPen(QtGui.QPen(QtGui.QColor(60, 68, 88), 1.2)); p.setBrush(QtGui.QColor(22, 27, 38))
                    p.drawRoundedRect(r, 14 * u, 14 * u)
                    self._font(p, 14, bold=True); p.setPen(QtGui.QColor(200, 206, 222))
                    p.drawText(r, QtCore.Qt.AlignCenter, t("next_layer", self.lang))
                    self.hits.append((QtGui.QPolygonF(r), ("layer",)))
                    continue
                p.setPen(QtGui.QPen(ACCENT, 1.4)); p.setBrush(QtGui.QColor(22, 27, 38)); p.drawRoundedRect(r, 14 * u, 14 * u)
                self._font(p, 15, bold=True); p.setPen(QtGui.QColor(232, 234, 240)); p.drawText(r, QtCore.Qt.AlignCenter, t(key, self.lang))
                self.hits.append((QtGui.QPolygonF(r), ("turn_sel", turns)))

    # ---- random scramble (play again) ---------------------------------------------------------------------------
    ARM_S = 3.0

    def scramble_clicked(self):
        """Solved, or nothing played yet: a new random scramble at once. Mid-game: the first click arms the button
        ("click again to scramble", 3 s), so a stray click never throws a game away."""
        g, now = self.game, time.monotonic()
        if g.solved or g.moves == 0 or now < self.scramble_armed_until:
            self.scramble_armed_until = 0.0
            return self.command("new")
        self.scramble_armed_until = now + self.ARM_S
        self.update()
        return False

    def bottom_reserve(self):
        """Height kept free under the cube for the dock, the layer badge, the turn lines and buttons, the pills. Fixed
        per mode (head / keys), so the cube does not change size each time a layer is selected or released."""
        return (270 if self.extra.get("head") else 220) * self._unit()

    def _scramble_button(self, p, cw, h):
        """Top right of the cube area (clear of the turn buttons and pills at the bottom)."""
        if self.locked(): return
        u, g = self._unit(), self.game
        armed = time.monotonic() < self.scramble_armed_until
        self._font(p, 13, bold=True)
        label = t("btn.scramble_again" if armed else "btn.scramble", self.lang)
        bw = p.fontMetrics().horizontalAdvance(label) + 36 * u
        r = QtCore.QRectF(cw - bw - 18 * u, 76 * u, bw, 40 * u)
        if g.solved:                                  # invite to play again
            p.setPen(QtCore.Qt.NoPen); p.setBrush(ACCENT); text_col = QtGui.QColor(11, 16, 32)
        else:
            p.setPen(QtGui.QPen(HINT if armed else QtGui.QColor(60, 68, 88), 1.4)); p.setBrush(QtGui.QColor(22, 27, 38))
            text_col = HINT if armed else QtGui.QColor(220, 224, 234)
        p.drawRoundedRect(r, 14 * u, 14 * u)
        p.setPen(text_col)
        p.drawText(r, QtCore.Qt.AlignCenter, label)
        self.hits.append((QtGui.QPolygonF(r), ("scramble",)))

    def _signal_strip(self, p, cw):
        """What the system hears, live (last 3 s): the EOG (blink channel) and the EMG (jaw) with their thresholds —
        the player sees a blink / clench cross the line. Left side, under the 3D head."""
        u, sig = self._unit(), self.extra["signals"]
        top = (self.head_canvas.geometry().bottom() + 30 * u) if (self.head_canvas and self.head_canvas.isVisible()) else 80 * u
        w_box, h_box = self.COL_W * u, 58 * u
        for k, (key, label) in enumerate((("eog", "sig.eog"), ("emg", "sig.emg"))):
            if key not in sig: continue
            ys, thr = sig[key]
            r = QtCore.QRectF(12 * u, top + k * (h_box + 26 * u), w_box, h_box)
            p.setPen(QtGui.QPen(QtGui.QColor(42, 49, 66), 1)); p.setBrush(QtGui.QColor(16, 20, 30, 220))
            p.drawRoundedRect(r, 8 * u, 8 * u)
            self._font(p, 9, bold=True, mono=True); p.setPen(MUTED)
            p.drawText(QtCore.QRectF(r.x(), r.y() - 18 * u, r.width(), 16 * u), QtCore.Qt.AlignVCenter, t(label, self.lang))
            if len(ys) < 2: continue
            lo = min(0.0, min(ys)) if key == "eog" else 0.0
            hi = max(max(ys), (thr or 0) * 1.3, 1e-6)
            def py(v): return r.bottom() - 5 * u - (v - lo) / (hi - lo) * (r.height() - 10 * u)
            if thr:
                over = max(ys) >= thr
                p.setPen(QtGui.QPen(HINT if over else QtGui.QColor(255, 196, 92, 150), 1.2 * u, QtCore.Qt.DashLine))
                p.drawLine(QtCore.QPointF(r.x() + 4 * u, py(thr)), QtCore.QPointF(r.right() - 4 * u, py(thr)))
            path = QtGui.QPainterPath()
            for i, v in enumerate(ys):
                pt = QtCore.QPointF(r.x() + 4 * u + i / (len(ys) - 1) * (r.width() - 8 * u), py(max(lo, min(hi, v))))
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            p.setPen(QtGui.QPen(ACCENT if key == "eog" else OK_GREEN, 1.5 * u)); p.setBrush(QtCore.Qt.NoBrush)
            p.drawPath(path)

    def _canvas_caption(self, p):
        """The 3D head's caption (in the cover widget over its last line): the camera state, in words."""
        cam = self.extra.get("camera")
        if cam is None: text, colour = t("cam.off", self.lang), MUTED
        else:
            text = t("cam." + cam, self.lang)
            text = (cam if text == "cam." + cam else text)
            colour = OK_GREEN if cam == "facing the screen" else HINT
            text = t("cam.on", self.lang, what=text)
        if self._cover is not None and (self._cover.text, self._cover.colour) != (text, colour):
            self._cover.text, self._cover.colour = text, colour; self._cover.update()

    def turn_hint(self):
        """How the selected layer can be turned now (head mode), one line per direction, then the next-layer line:
            ↻ clockwise: tilt right · blink twice      ↺ counter: tilt left · clench      nod: next layer
        With tilt off or failed it says so (the ↺ ↻ buttons are then shown)."""
        methods = self.extra.get("methods") or []
        cw = [t("how.tilt_r", self.lang)] if "tilt" in methods else []
        ccw = [t("how.tilt_l", self.lang)] if "tilt" in methods else []
        if "blink" in methods: cw.append(t("how.blink2", self.lang))
        if "jaw" in methods: ccw.append(t("how.jaw2", self.lang))
        last = t("how.nod", self.lang)                 # with tilt off the ↺ ↻ buttons are on screen: no need to say so
        if "tilt" not in methods and self.extra.get("tilt_failed"): last = t("how.tilt_failed2", self.lang) + " · " + last
        lines = ([t("how.cw", self.lang, how=" · ".join(cw))] if cw else []) + \
                ([t("how.ccw", self.lang, how=" · ".join(ccw))] if ccw else []) + [last]
        return "\n".join(lines)

    def _tutorial_card(self, p, cw):
        """The current step at the top of the cube area: what to do (head or keys / mouse), ✓ after each step."""
        u, tut = self._unit(), self.tutorial
        head = bool(self.extra.get("head"))
        step = tut.step
        mode = "head" if head else "keys"
        body = t(f"tut.{step}.{mode}", self.lang)
        if step == "turn" and head:                     # whatever turns a layer now: tilt / blink / jaw / buttons
            body = t("tut.turn.how", self.lang, how=self.turn_hint().replace("\n", " · "))
        left = max(20 * u, self._canvas_right() + 14 * u)          # clear of the 3D head, top left
        width = min(cw - left - 20 * u, 760 * u)
        card = QtCore.QRectF(max(left, cw / 2 - width / 2), 74 * u, width, 132 * u)
        p.setPen(QtGui.QPen(ACCENT, 1.4)); p.setBrush(QtGui.QColor(20, 25, 38, 240)); p.drawRoundedRect(card, 18 * u, 18 * u)
        self._font(p, 11, bold=True, mono=True); p.setPen(ACCENT)
        p.drawText(QtCore.QRectF(card.x() + 22 * u, card.y() + 12 * u, card.width() / 2, 22 * u), QtCore.Qt.AlignVCenter,
                   t("tut.header", self.lang, i=tut.i + 1, n=len(STEPS)))
        if tut.cheering():
            self._font(p, 11, bold=True); p.setPen(OK_GREEN)
            dots_w = 22 * u + len(STEPS) * 16 * u                # left of the progress dots
            p.drawText(QtCore.QRectF(card.x(), card.y() + 12 * u, card.width() - dots_w, 22 * u),
                       QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight, t("tut.cheer", self.lang))
        self._font(p, 18, bold=True); p.setPen(QtGui.QColor(236, 240, 255))
        p.drawText(QtCore.QRectF(card.x() + 22 * u, card.y() + 36 * u, card.width() - 44 * u, 30 * u), QtCore.Qt.AlignVCenter,
                   t(f"tut.{step}.title", self.lang))
        self._font(p, 13); p.setPen(QtGui.QColor(196, 202, 220))
        p.drawText(QtCore.QRectF(card.x() + 22 * u, card.y() + 68 * u, card.width() - 200 * u, 56 * u),
                   QtCore.Qt.TextWordWrap | QtCore.Qt.AlignTop, body)
        for i in range(len(STEPS)):                              # progress dots
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(OK_GREEN if i < tut.i else ACCENT if i == tut.i else QtGui.QColor(60, 68, 88))
            p.drawEllipse(QtCore.QPointF(card.right() - 22 * u - (len(STEPS) - 1 - i) * 16 * u, card.y() + 23 * u), 4.5 * u, 4.5 * u)
        btn = QtCore.QRectF(card.right() - 168 * u, card.bottom() - 54 * u, 150 * u, 40 * u)
        if tut.finished:
            p.setPen(QtCore.Qt.NoPen); p.setBrush(ACCENT); p.drawRoundedRect(btn, 12 * u, 12 * u)
            self._font(p, 14, bold=True); p.setPen(QtGui.QColor(11, 16, 32)); p.drawText(btn, QtCore.Qt.AlignCenter, t("tut.go", self.lang))
            self.hits.append((QtGui.QPolygonF(btn), ("tutorial_done",)))
        else:
            p.setPen(QtGui.QPen(QtGui.QColor(60, 68, 88), 1.2)); p.setBrush(QtGui.QColor(24, 29, 41)); p.drawRoundedRect(btn, 12 * u, 12 * u)
            self._font(p, 13); p.setPen(MUTED); p.drawText(btn, QtCore.Qt.AlignCenter, t("tut.skip", self.lang))
            self.hits.append((QtGui.QPolygonF(btn), ("tutorial_skip",)))

    # ---- the 2D panel --------------------------------------------------------------------------------------------
    def panel_width(self):
        return min(0.38 * self.width(), 600 * self._unit())

    def panel_shown(self):
        """On, wide enough, and leaving the cube at least 460 units beside the left column."""
        if not self.panel or self.width() < 1100: return False
        return self.width() - self.panel_width() - self.left_column() >= 460 * self._unit()

    def _screen_stickers(self):
        """[(screen pos, screen normal, colour, cubie id, old screen pos, old screen normal)] — old = before the turn
        being animated (for the 2D animation), else None."""
        g = self.game
        R = g.view.R
        anim = self.anim if self.anim and self.anim["kind"] == "turn" else None
        moving, back = set(), None
        if anim:
            moving = {id(c) for c in g.cube.layer(anim["face"], anim["depth"])}
            back = rot90(NORMAL[anim["face"]], anim["signed"])            # committed → before the turn
        out = []
        for c in g.cube.cubies:
            for nrm, col in c["stickers"].items():
                pos, nv = R @ c["pos"], R @ np.array(nrm)
                old = (R @ (back @ c["pos"]), R @ (back @ np.array(nrm))) if id(c) in moving else (None, None)
                out.append((pos, nv, col, id(c), old[0], old[1]))
        return out

    def _panel(self, p, rect):
        u, g = self._unit(), self.game
        p.setPen(QtGui.QPen(QtGui.QColor(42, 49, 66), 1.2)); p.setBrush(QtGui.QColor(24, 28, 38, 235))
        p.drawRoundedRect(rect, 18 * u, 18 * u)
        self._font(p, 11, bold=True, mono=True); p.setPen(MUTED)
        p.drawText(QtCore.QRectF(rect.x() + 24 * u, rect.y() + 18 * u, rect.width() / 2, 40 * u), QtCore.Qt.AlignVCenter,
                   t("panel.title", self.lang))
        # Three rings | Cross
        self._font(p, 12, bold=True)
        fm, pad = p.fontMetrics(), 6 * u
        opts = (("rings", t("panel.rings", self.lang)), ("cross", t("panel.cross", self.lang)))
        widths = [fm.horizontalAdvance(txt) + 32 * u for _, txt in opts]
        box = QtCore.QRectF(rect.right() - 20 * u - sum(widths) - 2 * pad, rect.y() + 14 * u, sum(widths) + 2 * pad, 48 * u)
        p.setPen(QtGui.QPen(QtGui.QColor(42, 49, 66), 1.2)); p.setBrush(QtGui.QColor(30, 35, 47))
        p.drawRoundedRect(box, 12 * u, 12 * u)
        x = box.x() + pad
        for (key, txt), sw in zip(opts, widths):
            seg = QtCore.QRectF(x, box.y() + pad, sw, box.height() - 2 * pad); x += sw
            if self.panel_mode == key:
                p.setPen(QtCore.Qt.NoPen); p.setBrush(ACCENT); p.drawRoundedRect(seg, 9 * u, 9 * u); p.setPen(QtGui.QColor(11, 16, 32))
            else:
                p.setPen(QtGui.QColor(232, 234, 240))
            p.drawText(seg, QtCore.Qt.AlignCenter, txt)
            self.hits.append((QtGui.QPolygonF(seg), ("panel_mode", key)))
        caption_h = 118 * u
        area = QtCore.QRectF(rect.x() + 16 * u, box.bottom() + 10 * u, rect.width() - 32 * u,
                             rect.height() - (box.bottom() - rect.y()) - caption_h - 16 * u)
        lit = (self.selected, self.depth) if self.selected else None
        hint = (g.hint[0], g.hint[3]) if g.hint else None
        if self.panel_mode == "rings": self._rings(p, area, lit, hint)
        else: self._cross(p, area, lit, hint)
        self._font(p, 12); p.setPen(QtGui.QColor(170, 178, 196))
        p.drawText(QtCore.QRectF(rect.x() + 24 * u, rect.bottom() - caption_h, rect.width() - 48 * u, caption_h - 12 * u),
                   QtCore.Qt.TextWordWrap | QtCore.Qt.AlignVCenter,
                   t("panel.rings_note" if self.panel_mode == "rings" else "panel.cross_note", self.lang))

    def _ball(self, p, pt, rgb, r, alpha=255, ring=None):
        grad = QtGui.QRadialGradient(pt.x() - r * 0.35, pt.y() - r * 0.4, r * 1.3)
        grad.setColorAt(0, shade(rgb, 1.25, alpha)); grad.setColorAt(0.55, shade(rgb, 1.0, alpha)); grad.setColorAt(1, shade(rgb, 0.62, alpha))
        p.setPen(QtGui.QPen(ring, 2.6 * self._unit()) if ring is not None else QtCore.Qt.NoPen); p.setBrush(grad)
        p.drawEllipse(pt, r, r)

    def _rings(self, p, area, lit, hint):
        u, g, n = self._unit(), self.game, self.game.n
        size = min(area.width() * 0.94, area.height() * 0.98 / 0.955)      # the drawing is 0.955 × size tall
        L = Rings(n, area.center().x(), area.center().y(), size)
        lit_ring = L.ring_of(*lit) if lit else None
        hint_ring = L.ring_of(*hint) if hint else None
        for axis, coord, name, (face, depth) in L.rings():
            c, r = L.centres[axis], L.radius(axis, coord)
            on, hinted = (axis, coord) == lit_ring, (axis, coord) == hint_ring
            colour = ACCENT if on else HINT if hinted else QtGui.QColor(150, 158, 178, 120)
            p.setPen(QtGui.QPen(colour, (3.2 if on or hinted else 1.3) * u)); p.setBrush(QtCore.Qt.NoBrush)
            p.drawEllipse(QtCore.QPointF(*c), r, r)
            path = QtGui.QPainterPath(); path.addEllipse(QtCore.QPointF(*c), r, r)
            stroke = QtGui.QPainterPathStroker(); stroke.setWidth(10 * u)
            self.hits.append((stroke.createStroke(path).toFillPolygon(), ("ring", face, depth)))
            label_rgb = PALETTE[COLOURS[g.view.logical(name)]] if name in NORMAL else (170, 176, 192)
            for k, pt in enumerate(L.label_points(axis, coord)):
                q = QtCore.QPointF(*pt)
                br = 15 * u                                      # ≥ 30 px across at 1280×800
                p.setPen(QtGui.QPen(QtGui.QColor(*label_rgb), 1.6 * u)); p.setBrush(QtGui.QColor(20, 24, 34))
                p.drawEllipse(q, br, br)
                self._font(p, 10, bold=True, mono=True); p.setPen(QtGui.QColor(232, 234, 240))
                p.drawText(QtCore.QRectF(q.x() - br, q.y() - br, 2 * br, 2 * br), QtCore.Qt.AlignCenter, name + ("′" if k else ""))
                self.hits.append((QtGui.QPolygonF(QtCore.QRectF(q.x() - br, q.y() - br, 2 * br, 2 * br)),
                                  ("ring_turn", face, -1 if k else 1, depth)))
        e = self._progress()
        lit_set = set()
        if lit: lit_set = {id(c) for c in g.cube.layer(g.view.logical(lit[0]), lit[1])}
        r_ball = (11.5 if n == 3 else 15) * u * size / 560
        for pos, nv, col, cid, opos, onv in self._screen_stickers():
            pt = L.point(pos, nv)
            if opos is not None and e < 1:
                p0 = L.point(opos, onv)
                ax = int(np.argmax(np.abs(g.view.R @ np.array(NORMAL[self.anim["face"]]))))   # turning axis, on screen
                if int(np.argmax(np.abs(nv))) != ax:                              # on the turning ring: along the arc
                    c = L.centres[ax]
                    a0, a1 = math.atan2(*(p0 - c)[::-1]), math.atan2(*(pt - c)[::-1])
                    da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
                    rr = float(np.linalg.norm(pt - c)); a = a0 + da * e
                    pt = c + rr * np.array((math.cos(a), math.sin(a)))
                else:
                    pt = p0 + (pt - p0) * e
            self._ball(p, QtCore.QPointF(*pt), PALETTE[col], r_ball, ring=ACCENT if cid in lit_set else None)

    def _cross(self, p, area, lit, hint):
        u, g, n = self._unit(), self.game, self.game.n
        cell = min(area.width() / (4 * n + 3.2), area.height() / (3 * n + 2.4))
        gap = cell * 0.6
        ox = area.center().x() - (4 * n * cell + 3 * gap) / 2
        oy = area.center().y() - (3 * n * cell + 2 * gap) / 2
        lit_set = {id(c) for c in g.cube.layer(g.view.logical(lit[0]), lit[1])} if lit else set()
        hint_set = {id(c) for c in g.cube.layer(g.view.logical(hint[0]), hint[1])} if hint else set()
        self._font(p, 10, bold=True, mono=True)
        for face, (col, row) in NET_AT.items():
            fx, fy = ox + col * (n * cell + gap), oy + row * (n * cell + gap)
            p.setPen(MUTED); p.drawText(QtCore.QRectF(fx, fy - 18 * u, n * cell, 16 * u), QtCore.Qt.AlignCenter, face)
        for pos, nv, colour, cid, _, _ in self._screen_stickers():
            face, c, r = net_cell(n, pos, nv)
            col, row = NET_AT[face]
            x = ox + col * (n * cell + gap) + c * cell
            y = oy + row * (n * cell + gap) + r * cell
            sq = QtCore.QRectF(x + cell * 0.06, y + cell * 0.06, cell * 0.88, cell * 0.88)
            dim = bool(lit_set) and cid not in lit_set
            p.setPen(QtCore.Qt.NoPen); p.setBrush(shade(PALETTE[colour], 0.5 if dim else 1.0))
            p.drawRoundedRect(sq, cell * 0.16, cell * 0.16)
            if cid in lit_set or cid in hint_set:
                p.setPen(QtGui.QPen(ACCENT if cid in lit_set else HINT, 2.6 * u)); p.setBrush(QtCore.Qt.NoBrush)
                p.drawRoundedRect(sq, cell * 0.16, cell * 0.16)
            self.hits.append((QtGui.QPolygonF(sq), ("sticker", face)))

    def layer_name(self, face, depth):
        """'right face' · 'middle layer (right side)' · 'opposite layer (behind the right face)'."""
        name = t("face." + face, self.lang)
        if depth == 0: return name
        if depth == self.game.n - 1: return t("layer.opposite", self.lang, face=name)
        return t("layer.middle", self.lang, face=name)

    def _layer_badge(self, p, w, y):
        """The selected layer, named, with one bar per layer (the chosen one lit)."""
        u, n = self._unit(), self.game.n
        self._font(p, 17, bold=True)
        text = self.layer_name(self.selected, self.depth)
        fm = p.fontMetrics()
        bars_w = n * 22 * u
        wt = fm.horizontalAdvance(text) + bars_w + 56 * u
        r = QtCore.QRectF((w - wt) / 2, y, wt, 40 * u)
        p.setPen(QtGui.QPen(ACCENT, 1.6)); p.setBrush(QtGui.QColor(143, 163, 255, 34)); p.drawRoundedRect(r, 20 * u, 20 * u)
        for i in range(n):
            b = QtCore.QRectF(r.x() + 18 * u + i * 22 * u, r.y() + 11 * u, 14 * u, 18 * u)
            p.setPen(QtCore.Qt.NoPen); p.setBrush(ACCENT if i == self.depth else QtGui.QColor(60, 68, 88))
            p.drawRoundedRect(b, 3 * u, 3 * u)
        p.setPen(QtGui.QColor(232, 236, 255))
        p.drawText(QtCore.QRectF(r.x() + 26 * u + bars_w, r.y(), fm.horizontalAdvance(text) + 20 * u, r.height()),
                   QtCore.Qt.AlignVCenter, text)

    def _flash(self, p, w, h):
        key = self.extra.get("flash")
        if not key: return
        u = self._unit()
        self._font(p, 13, bold=True)
        text = t("flash." + key, self.lang)
        fm = p.fontMetrics(); wt = fm.horizontalAdvance(text) + 28 * u
        r = QtCore.QRectF((w - wt) / 2, 18 * u, wt, 34 * u)
        p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(143, 163, 255, 40)); p.drawRoundedRect(r, 17 * u, 17 * u)
        p.setPen(ACCENT); p.drawText(r, QtCore.Qt.AlignCenter, text)

    def _overlay(self, p, w, h, o):
        """Calibration / tilt test: a card over a dimmed cube. Left: an animated pictogram of the movement (a demo
        while getting ready, the pose to hold during "now"). Right: the step, what exactly to do and what to avoid,
        the phase, the reason when a step must be repeated, and the time bar."""
        u = self._unit()
        p.fillRect(self.rect(), QtGui.QColor(4, 6, 10, 200))
        card = QtCore.QRectF(w / 2 - 430 * u, h / 2 - 220 * u, 860 * u, 440 * u)
        p.setPen(QtGui.QPen(QtGui.QColor(42, 49, 66), 1.2)); p.setBrush(QtGui.QColor(18, 23, 34))
        p.drawRoundedRect(card, 22 * u, 22 * u)
        white = QtGui.QColor(236, 240, 255)
        if o["kind"] == "calib":
            head = t("calib.title", self.lang, i=o["i"] + 1, n=o["n"])
            kind, title = o["step"], t("calib." + o["step"], self.lang)
            how = t("calib." + o["step"] + ".how", self.lang)
            hold = o["phase"] == "go"
            if o["phase"] == "prep": phase, colour = t("calib.ready", self.lang), white
            elif o["phase"] == "go": phase, colour = t("calib.go", self.lang), ACCENT
            elif o["ok"]: phase, colour = t("calib.ok", self.lang), OK_GREEN
            else:
                why = o.get("message") or ""
                why = t("why." + why, self.lang) if not t("why." + why, self.lang).startswith("why.") else why
                phase, colour = t("calib.retry_why", self.lang, why=why) if why else t("calib.retry", self.lang), HINT
        else:
            head = t("test.title", self.lang, i=o["i"] + 1, n=o["n"])
            prompt = o["prompt"]
            hold = False
            if prompt is None:
                kind, title, how, phase, colour = "centre", t("test.ready", self.lang), t("test.rule", self.lang), "", white
            else:
                kind = {"right": "tilt", "left": "left_tilt"}.get(prompt, prompt)
                title, how = t("test." + prompt, self.lang), t("test." + prompt + ".how", self.lang)
                got = o.get("got") or []
                phase = t("test.seen", self.lang, what=", ".join(
                    t("flash.tilt_r" if d > 0 else "flash.tilt_l", self.lang) for d in got)) if got else ""
                colour = ACCENT if prompt in ("right", "left") else white
        pic = QtCore.QRectF(card.x() + 24 * u, card.y() + 50 * u, 300 * u, 300 * u)
        pictos.draw(p, pic, kind, time.monotonic(), hold=hold)
        self._font(p, 10); p.setPen(MUTED)
        p.drawText(QtCore.QRectF(pic.x(), pic.bottom() + 2 * u, pic.width(), 36 * u),
                   QtCore.Qt.AlignHCenter | QtCore.Qt.TextWordWrap, t("picto.mirror", self.lang))
        tx = pic.right() + 28 * u
        tw = card.right() - tx - 28 * u
        self._font(p, 12, mono=True); p.setPen(MUTED)
        p.drawText(QtCore.QRectF(tx, card.y() + 22 * u, tw, 24 * u), QtCore.Qt.AlignVCenter, head)
        self._font(p, 22, bold=True); p.setPen(white)
        p.drawText(QtCore.QRectF(tx, card.y() + 52 * u, tw, 70 * u), QtCore.Qt.TextWordWrap | QtCore.Qt.AlignTop, title)
        self._font(p, 13); p.setPen(QtGui.QColor(196, 202, 220))
        p.drawText(QtCore.QRectF(tx, card.y() + 128 * u, tw, 170 * u), QtCore.Qt.TextWordWrap | QtCore.Qt.AlignTop, how)
        self._font(p, 20, bold=True); p.setPen(colour)
        p.drawText(QtCore.QRectF(tx, card.y() + 300 * u, tw, 50 * u), QtCore.Qt.TextWordWrap | QtCore.Qt.AlignVCenter, phase)
        bar = QtCore.QRectF(tx, card.bottom() - 62 * u, tw, 10 * u)
        p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(36, 42, 56)); p.drawRoundedRect(bar, 5 * u, 5 * u)
        p.setBrush(colour); p.drawRoundedRect(QtCore.QRectF(bar.x(), bar.y(), bar.width() * max(0.0, min(1.0, o["progress"])), bar.height()), 5 * u, 5 * u)
        self._font(p, 11); p.setPen(MUTED)
        p.drawText(QtCore.QRectF(tx, card.bottom() - 42 * u, tw, 24 * u), QtCore.Qt.AlignVCenter, t("overlay.esc", self.lang))
        if not hasattr(self, "_overlay_timer"):                 # keep the pictogram moving between controller pushes
            self._overlay_timer = QtCore.QTimer(self); self._overlay_timer.setInterval(40)
            self._overlay_timer.timeout.connect(lambda: self.update() if self.locked() else self._overlay_timer.stop())
        if not self._overlay_timer.isActive(): self._overlay_timer.start()

    def _describe(self):
        g = self.game
        hint = ""
        if g.hint: hint = t("hint", self.lang, move=self.layer_name(g.hint[0], g.hint[3]), left=g.hint[2])
        if self.selected: hint += " " + self.layer_name(self.selected, self.depth)
        self.setAccessibleDescription(t("a11y", self.lang, state=t("solved" if g.solved else "unsolved", self.lang),
                                        size=t("size", self.lang, n=g.n, d=g.depth),
                                        moves=t("moves", self.lang, n=g.moves), hint=hint))
