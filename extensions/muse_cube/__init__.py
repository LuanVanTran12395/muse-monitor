"""Muse Cube — a Rubik's cube game in a window of its own, played with the head on Muse S Athena (or keys / mouse).

Design: debate/claude-rubik-game-proposal.md (round 2, approved). The model knows logical faces only; the view maps
screen faces to them, so turning the whole cube never breaks the history, undo or the hint (cube.py). The window draws
the cube in two styles from the reference pictures, Glass (default) and Classic (board.py).

R1: the game, keyboard and mouse — needs no other extension. R2: head control (controller.py) through adapter.py, the
only place other extensions are loaded (head_motion_plus, food_order/gestures.py, read-only); a missing estimator
switches off only its gesture. Eye shortcuts come in R3.
"""
import time
import sys

# The app's loader re-executes this package on reload but keeps its submodules in sys.modules (see food_order).
for _stale in [k for k in sys.modules if k.startswith(__name__ + ".")]:
    del sys.modules[_stale]

from PySide6 import QtWidgets

from musemonitor.plugins.api import BaseTab, Extension
from musemonitor.plugins.cues import Cues

from .adapter import Adapter
from .board import CubeWindow
from .controller import CubeController
from .game import DEPTHS
from .signals import SignalsBox


class MuseCubeTab(BaseTab):
    title = "Muse Cube"

    def __init__(self, ctx, ext):
        super().__init__(ctx)
        self.ext = ext
        v = QtWidgets.QVBoxLayout(self)
        box = QtWidgets.QGroupBox("Muse Cube — Rubik's cube"); bv = QtWidgets.QVBoxLayout(box)
        bv.addWidget(ctx.plots.muted_label(
            "Opens the cube window. Keys: U D L R F B turn the face showing there (Shift = counter-clockwise) · M E S "
            "middle slices (3×3) · Tab next layer · arrows turn the whole cube (the view only) · Backspace undo · H way "
            "back (hint; not the shortest solution, and a game with hints is not ranked) · Space new game · G Glass / "
            "Classic · P the 2D panel (three rings / cross) · N language · F11 full screen. "
            "Mouse: click a face (again: next layer), then ↺ / ↻; in the 2D panel click a ring or its buttons; drag "
            "to look around.\n"
            "Head (Muse S Athena, after a 15 s calibration): point left / centre / right = front / top / right face · "
            "nod = next layer · tilt right / left = turn it ↻ / ↺ · full turn and back = turn the cube · look up and "
            "hold = flip the cube · shake = undo · nod = new game once solved. In the window: K calibrate · T tilt "
            "test · Home recenter."))
        row = QtWidgets.QHBoxLayout()
        self.open_btn = QtWidgets.QPushButton("🧊 Open Muse Cube")
        self.tut_btn = QtWidgets.QPushButton("Tutorial")
        self.tut_btn.setToolTip("8 short steps before the real game: pick a face, choose a layer, turn, undo, turn "
                                "the cube, solve 1 move, solve 2 moves. Runs by itself the first time; F1 in the window.")
        self.size_box = QtWidgets.QComboBox()
        for n in (2, 3): self.size_box.addItem(f"{n}×{n}", n)
        self.depth_box = QtWidgets.QComboBox()
        self.style_box = QtWidgets.QComboBox()
        for key, name in (("glass", "Glass"), ("classic", "Classic")): self.style_box.addItem(name, key)
        self.lang_box = QtWidgets.QComboBox()
        for code, name in (("vi", "Tiếng Việt"), ("en", "English")): self.lang_box.addItem(name, code)
        row.addWidget(self.open_btn); row.addWidget(self.tut_btn)
        for label, wdg in (("Size:", self.size_box), ("Scramble:", self.depth_box), ("Style:", self.style_box),
                           ("Language:", self.lang_box)):
            row.addWidget(QtWidgets.QLabel(label)); row.addWidget(wdg)
        row.addStretch(); bv.addLayout(row)
        hrow = QtWidgets.QHBoxLayout()
        self.calib_btn = QtWidgets.QPushButton("Calibrate head")
        self.test_btn = QtWidgets.QPushButton("Tilt test (~2 min)")
        self.test_btn.setToolTip("32 prompts of 4 s: tilt right ×10, tilt left ×10, and pointing / nodding / centring "
                                 "×12 during which any tilt is false. Pass: ≥ 8/10 on each side and no false tilt. It "
                                 "decides whether tilting stays the way to turn a face (design §5).")
        self.tilt_check = QtWidgets.QCheckBox("Tilt turns the selected face")
        self.eyejaw_check = QtWidgets.QCheckBox("Blink ×2 ↻ · jaw clench ↺")
        self.eyejaw_check.setToolTip("With a layer selected and the head still: two quick blinks turn it clockwise "
                                     "(food_order's double-blink rule, TP9/TP10), a jaw clench counter-clockwise (30–45 Hz "
                                     "EMG, artifact_log's band, on TP9/TP10). Both are calibrated (two steps after the head "
                                     "steps). A stray one is a move a shake undoes. Not tried on a person yet.")
        self.sound = QtWidgets.QCheckBox("Sound cues")
        self.cam_check = QtWidgets.QCheckBox("📷 Camera recenter (shows a 3D head, never your face)")
        self.cam_check.setToolTip("head_motion_plus's camera reference: when you look straight at the screen and hold "
                                  "still for 1 s, the head pointer is recentered (gyro drift). Only the 'facing' result "
                                  "is used — no camera image is shown or saved; the window shows a 3D head model that "
                                  "follows the IMU. Off by default; asks every time.")
        for wdg in (self.calib_btn, self.test_btn, self.tilt_check, self.eyejaw_check, self.cam_check, self.sound):
            hrow.addWidget(wdg)
        hrow.addStretch(); bv.addLayout(hrow)
        self.status = QtWidgets.QLabel("—"); self.status.setWordWrap(True); bv.addWidget(self.status)
        v.addWidget(box)
        self.signals = SignalsBox(ctx, ext)
        v.addWidget(self.signals); v.addStretch()
        self.open_btn.clicked.connect(lambda: ext.open())
        self.tut_btn.clicked.connect(lambda: ext.open(tutorial=True))
        self.calib_btn.clicked.connect(lambda: (ext.open(), ext.controller.start_calibration(), ext.refresh()))
        self.test_btn.clicked.connect(lambda: (ext.open(), ext.controller.start_tilt_test(), ext.refresh()))
        self.tilt_check.toggled.connect(lambda on: (ext.app.set_setting("cube_tilt", on), ext.refresh()))
        self.eyejaw_check.toggled.connect(lambda on: (ext.app.set_setting("cube_eyejaw", on), ext.refresh()))
        self.cam_check.toggled.connect(self._camera_toggled)
        self.sound.toggled.connect(lambda on: (ext.app.set_setting("sound", on), setattr(ext.cues, "enabled", on)))

    def _camera_toggled(self, on):
        c = self.ext.controller
        if not on:
            c.camera_stop(); self.ext.refresh(); return
        if not self.ext.ask_camera(self):
            self.cam_check.blockSignals(True); self.cam_check.setChecked(False); self.cam_check.blockSignals(False)
            return
        ok, msg = c.camera_start()
        if not ok:
            self.cam_check.blockSignals(True); self.cam_check.setChecked(False); self.cam_check.blockSignals(False)
            self.ext.app.show_status(f"Camera unavailable: {msg}")
        self.ext.refresh()

    def sync(self, n, depth, style, lang):
        for wdg in (self.size_box, self.depth_box, self.style_box, self.lang_box): wdg.blockSignals(True)
        self.size_box.setCurrentIndex(self.size_box.findData(n))
        self.depth_box.clear()
        for d in DEPTHS[n]: self.depth_box.addItem(f"{d} moves", d)
        self.depth_box.setCurrentIndex(max(0, self.depth_box.findData(depth)))
        self.style_box.setCurrentIndex(self.style_box.findData(style))
        self.lang_box.setCurrentIndex(self.lang_box.findData(lang))
        for wdg in (self.size_box, self.depth_box, self.style_box, self.lang_box): wdg.blockSignals(False)


class MuseCube(Extension):
    id = "muse_cube"
    name = "Muse Cube"
    version = "0.1.0"
    requires_api = 3
    category = "Other"
    description = "Rubik's cube game (2×2 / 3×3), Glass and Classic styles; keyboard and mouse (head / eyes: next stage)."

    @classmethod
    def supports(cls, spec):
        return True                                   # the keyboard game needs no device

    mono = staticmethod(time.monotonic)              # replaceable in tests

    def activate(self, app):
        self.window = None
        self.cues = Cues(enabled=str(app.setting("sound", True)).lower() in ("true", "1"))
        self.adapter = Adapter()
        imu_fs = float(app.spec.imu.fs) if getattr(app.spec, "imu", None) is not None and app.spec.imu.n >= 6 else None
        eeg = getattr(app.spec, "eeg", None)
        self.controller = CubeController(self, self.adapter, imu_fs, float(eeg.fs) if eeg is not None else None,
                                         list(eeg.names) if eeg is not None else None)
        self.tab = app.add_tab(MuseCubeTab(app.view, self))
        self.tab.sync(*self.options())
        self.tab.tilt_check.setChecked(self.controller.tilt_on()); self.tab.sound.setChecked(self.cues.enabled)
        self.tab.eyejaw_check.setChecked(str(app.setting("cube_eyejaw", True)).lower() in ("true", "1"))
        self.tab.eyejaw_check.setEnabled(self.controller.eyes is not None or self.controller.jaw is not None)
        self.tab.cam_check.setEnabled(self.controller.camera is not None)
        self.refresh()
        t = self.tab
        t.size_box.currentIndexChanged.connect(lambda _i: self._set("cube_size", t.size_box.currentData()))
        t.depth_box.currentIndexChanged.connect(lambda _i: self._set("cube_depth", t.depth_box.currentData()))
        t.style_box.currentIndexChanged.connect(lambda _i: self._set("cube_style", t.style_box.currentData()))
        t.lang_box.currentIndexChanged.connect(lambda _i: self._set("language", t.lang_box.currentData()))

    def deactivate(self):
        self.controller.attach(None)
        if self.window is not None:
            self.window.on_closed = lambda: None; self.window.close(); self.window = None

    def options(self):
        n = int(self.app.setting("cube_size", 2, type=int))
        n = n if n in DEPTHS else 2
        depth = int(self.app.setting("cube_depth", DEPTHS[n][0], type=int))
        depth = depth if depth in DEPTHS[n] else DEPTHS[n][0]
        style = str(self.app.setting("cube_style", "glass"))
        lang = str(self.app.setting("language", "vi"))
        return n, depth, style if style in ("glass", "classic") else "glass", lang if lang in ("vi", "en") else "vi"

    def _set(self, key, value):
        if value is None: return
        self.app.set_setting(key, value)
        n, depth, style, lang = self.options()
        if key == "cube_size": self.tab.sync(n, depth, style, lang)       # the scramble list depends on the size
        w = self.window
        if w is None: return
        if key in ("cube_size", "cube_depth"): w.command("new", n, depth)
        elif key == "cube_style": w.command("style", style)
        elif key == "language": w.command("lang", lang)

    def _window_changed(self, kind, value):
        """Style / language / 2D panel switched inside the window: remember it and keep the tab in step."""
        key = {"style": "cube_style", "lang": "language", "panel": "cube_panel", "panel_mode": "cube_panel_mode",
               "tutorial_done": "cube_tutorial_done"}[kind]
        self.app.set_setting(key, value)
        self.tab.sync(*self.options())

    def _closed(self):
        self.window = None
        self.controller.attach(None)

    def ask_camera(self, parent):
        """The consent dialog (replaceable in tests)."""
        box = QtWidgets.QMessageBox(parent)
        box.setIcon(QtWidgets.QMessageBox.Question); box.setWindowTitle("Use camera?")
        box.setText("Allow Muse Cube to use the computer camera?")
        box.setInformativeText("It only recenters the head pointer when you look straight at the screen. Frames are "
                               "analysed in memory and never shown or saved — the window shows a 3D head model, not "
                               "your image.")
        allow = box.addButton("Allow camera", QtWidgets.QMessageBox.AcceptRole)
        box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is allow

    def on_eeg_samples(self, x, ts_raw):
        self.controller.on_eeg(x, ts_raw)

    def on_imu_samples(self, x, ts_raw):
        self.controller.on_imu(x, ts_raw)

    def tilt_test_finished(self, result):
        self.refresh()

    def calibration_finished(self):
        self.refresh()
        self.tab.signals.sync(force=True)              # the calibrated thresholds into the EOG / EMG controls

    def refresh(self):
        """The tab's status line: which head capabilities work, calibration, the last tilt test."""
        c, a = self.controller, self.adapter
        if c.head is None:
            text = f"Head control off ({c.reason or 'no IMU'}) — keyboard and mouse only."
        else:
            parts = ["Head: " + ("receiving IMU" if c.head_live() else "no IMU yet (connect the headset)"),
                     "calibrated" if c.head.calibrated else "not calibrated (K in the window)"]
            if not a.ok("tilt"): parts.append(f"tilt off ({a.reason('tilt')})")
            elif c.tilt.calibrated: parts.append(f"tilt threshold {c.tilt.threshold:.0f}°")
            if c.eyes is None: parts.append(f"blink off ({a.reason('eyes') or 'no EEG'})")
            else: parts.append("blink ×2 ready" if c.eyes.blink_ready else "blink ×2 not calibrated")
            if not a.ok("camera"): parts.append(f"camera off ({a.reason('camera')})")
            else: parts.append("camera on (recentering)" if c.camera_running() else "camera off")
            if c.jaw is None: parts.append("jaw off (no TP9/TP10)")
            else: parts.append(f"jaw clench ready (threshold {c.jaw.threshold:.1f} µV)" if c.jaw.ready else "jaw not calibrated")
            text = " · ".join(parts)
        r = c.test_result
        if r:
            text += (f"\nLast tilt test ({r.get('date', '?')}): right {r['right']}/{r['n_each']}, left {r['left']}/{r['n_each']}, "
                     f"false {r['false']}, wrong side {r.get('wrong_side', 0)}, repeats {r.get('repeats', 0)} → "
                     + ("PASSED — tilt turns faces" if r["passed"] else
                        "NOT PASSED — tilt is switched off (keys / mouse turn faces; T or the button retries; "
                        "otherwise the two-way control is redesigned, design §5.3)"))
        elif c.tilt is not None:
            text += "\nNo tilt test yet: tilt is on provisionally — run the tilt test to keep it."
        failed = c.tilt_failed()
        self.tab.tilt_check.setEnabled(c.tilt is not None and not failed)
        self.tab.tilt_check.setToolTip("Switched off by the failed tilt test — pass the test to use tilt." if failed else
                                       "Tilting the head turns the selected face (needs the calibration).")
        self.tab.status.setText(text)

    def open(self, tutorial=False):
        """The window; the tutorial runs first until it was done once (or when asked: tab button, F1)."""
        if self.window is None:
            n, depth, style, lang = self.options()
            first = str(self.app.setting("cube_tutorial_done", False)).lower() not in ("true", "1")
            self.window = CubeWindow(n, depth, style, lang, on_change=self._window_changed, on_closed=self._closed,
                                     panel=str(self.app.setting("cube_panel", True)).lower() in ("true", "1"),
                                     panel_mode=str(self.app.setting("cube_panel_mode", "rings")),
                                     tutorial=tutorial or first)
            self.controller.attach(self.window)
        elif tutorial:
            self.window.start_tutorial()
        self.window.show(); self.window.raise_(); self.window.activateWindow(); self.window.setFocus()
        return self.window
