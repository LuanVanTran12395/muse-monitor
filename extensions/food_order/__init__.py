"""Food order (demo) — order food with head and eye gestures on Muse S Athena, in a window of its own.

Design: debate/claude-food-order-extension-proposal.md, reviewed in debate/codex-food-order-extension-review.md.
**Muse Bistro** (the kiosk window, controller.py): sign in, browse three cards at a time, size / toppings / quantity,
cart, simulated checkout — driven by head pointing, dwell, full turns, nod / shake, look-up, double blink and eye
closure. The gestures come from the existing extensions' estimators, reused read-only (_reuse.py): head_motion_plus
(PoseTracker) and eye_interaction (EyeEstimator, relative_alpha). Keyboard and mouse do everything too.

Optional: a paced gesture-capture tool (capture*.py) that labels every repetition and records raw EEG + IMU.
"""
import json
import math
import sys
import time
from pathlib import Path

# The app's loader re-executes this package on reload but keeps its submodules in sys.modules, so
# "from . import controller" would return the OLD code (or code from another folder). Drop them first.
for _stale in [k for k in sys.modules if k.startswith(__name__ + ".")]:
    del sys.modules[_stale]

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

import musemonitor
from musemonitor import config as app_config
from musemonitor.core.quality import contact_quality
from musemonitor.plugins.api import BaseTab, Extension
from musemonitor.plugins.cues import Cues
from musemonitor.storage.session import data_root

from . import capture, protocol
from .capture_window import CaptureWindow
from .controller import Controller
from .demo import facing_caption

STALL_S = 2.0          # no EEG chunk for this long while connected = the headset went silent (see p300_bci)
POSTURES = ("Ngồi ghế có tựa", "Ngồi thẳng, không tựa", "Đứng")


def captures_root():
    """<app data folder>/food_order/capture — git-ignored like the app's recordings."""
    return data_root() / "food_order" / "capture"


class FoodOrderTab(BaseTab):
    title = "Food order (demo)"

    def __init__(self, ctx, ext):
        super().__init__(ctx)
        self.ext = ext
        v = QtWidgets.QVBoxLayout(self)
        kiosk = QtWidgets.QGroupBox("Muse Bistro — order with head and eyes"); kv = QtWidgets.QVBoxLayout(kiosk)
        kv.addWidget(ctx.plots.muted_label(
            "Opens the ordering window: a quick head calibration, sign-in, then: point by turning the head slightly "
            "(read as long as you like — pointing never selects) · choose: NOD · page: full turn and back · "
            "categories: look up and hold · back / undo / cancel: shake · item details: double blink · quick cart: "
            "eyes closed until the ting. Keyboard: ← → / 1–3, Enter (= nod), PgUp/PgDn, ↑, N, C, D (details), "
            "V (quick cart), R (recenter), K (calibrate). Orders are simulated."))
        krow = QtWidgets.QHBoxLayout()
        self.kiosk_btn = QtWidgets.QPushButton("🍕 Open Muse Bistro")
        self.recal_btn = QtWidgets.QPushButton("Calibrate again")
        self.dwell_sel = QtWidgets.QCheckBox("Hold still selects (experimental)")
        self.dwell_sel.setToolTip("Off by default: it selects whenever someone lingers to read a card (Midas touch).")
        self.dwell = QtWidgets.QDoubleSpinBox(); self.dwell.setRange(0.8, 5.0); self.dwell.setSingleStep(0.1)
        self.dwell.setSuffix(" s")
        self.blink_sel = QtWidgets.QCheckBox("Double blink: item details")
        self.blink_sel.setToolTip("Blink twice quickly (your spacing, from the calibration) with the head still: the "
                                  "pointed item opens enlarged with its details; nod chooses it. A mistaken detection "
                                  "only shows the details, which close when you shake or nod. On the 2026-10-19 "
                                  "captures, from TP9/TP10: 5 of 9 found, 0.33 false per minute.")
        self.eyes_cart = QtWidgets.QCheckBox("Eyes closed ~3 s: quick cart")
        self.eyes_cart.setToolTip("Close the eyes until the 'ting': the cart opens over the menu; nod orders, shake "
                                  "closes, it also closes by itself after 6 s (a closing deflection, then a quiet, "
                                  "blink-free signal, plus alpha). On the 2026-10-19 captures, from TP9/TP10: 4 of 4 "
                                  "found, 0.07 false per minute.")
        self.eye_src = QtWidgets.QComboBox()
        for code, name in (("tp", "Eyes: TP9/TP10"), ("af", "Eyes: AF7/AF8"), ("diff", "Eyes: AF − TP")):
            self.eye_src.addItem(name, code)
        self.eye_src.setToolTip("Which electrodes the eye shortcuts read. TP9/TP10 (default) did best on the "
                                "2026-10-19 captures: double blink 5/9 at 0.33 false/min, closure 4/4 at 0.07 false/min; "
                                "AF7/AF8 3/9 at 0.60 and 1/4 at 2.40. Muse references every channel to Fpz on the "
                                "forehead, so blinks also reach TP9/TP10; there gaze shifts disturb less and the "
                                "eyes-closed alpha is stronger. Changing it needs 'Calibrate again'.")
        for wdg in (self.kiosk_btn, self.recal_btn, self.dwell_sel, self.dwell, self.blink_sel, self.eyes_cart, self.eye_src):
            krow.addWidget(wdg)
        krow.addStretch(); kv.addLayout(krow)
        crow = QtWidgets.QHBoxLayout()
        self.cam_check = QtWidgets.QCheckBox("📷 Camera: auto-recenter + demo layout")
        self.cam_check.setToolTip("head_motion_plus's camera reference, reused: when you look straight at the screen "
                                  "and hold still for 1 s, the head pointer is recentered (corrects gyro drift). The "
                                  "kiosk then shows the camera, the 3D head and the eyes in a right column — handy for "
                                  "a demo video. Off by default; asks for permission every time; frames stay in memory.")
        self.rec_btn = QtWidgets.QPushButton("🎬 Record demo video")
        self.rec_btn.setToolTip("A screen video of the kiosk window only (UI, camera, head, eyes) → "
                                "data/food_order/demo/*.mp4 (local, git-ignored, no sound). NOT the app's EEG recording "
                                "(● Start recording above). In the kiosk: F9 or a click on the red label stops it.")
        self.video_btn = QtWidgets.QPushButton("Open videos folder")
        self.lang_box = QtWidgets.QComboBox()
        for code, name in (("vi", "Tiếng Việt"), ("en", "English")): self.lang_box.addItem(name, code)
        self.lang_box.setToolTip("Kiosk language. Each customer's choice is remembered for their account; it can "
                                 "also be switched in the window (L, the VI | EN switch, or looking up on the sign-in screen).")
        crow.addWidget(QtWidgets.QLabel("Language:")); crow.addWidget(self.lang_box)
        for wdg in (self.cam_check, self.rec_btn, self.video_btn): crow.addWidget(wdg)
        crow.addStretch(); kv.addLayout(crow)
        self.kiosk_status = QtWidgets.QLabel("—"); self.kiosk_status.setWordWrap(True); kv.addWidget(self.kiosk_status)
        self.cam_check.toggled.connect(self._camera_toggled)
        self.lang_box.currentIndexChanged.connect(lambda _i: ext.controller.set_lang(self.lang_box.currentData()))
        self.rec_btn.clicked.connect(self._record_clicked)
        self.video_btn.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(
            str(data_root() / "food_order" / "demo"))))
        v.addWidget(kiosk)
        self.kiosk_btn.clicked.connect(lambda: ext.controller.open())
        self.recal_btn.clicked.connect(lambda: (ext.controller.open(calibrate=False), ext.controller.start_calibration()))
        self.dwell.valueChanged.connect(ext.set_dwell)
        self.blink_sel.toggled.connect(lambda on: ext.app.set_setting("eye_details", on))
        self.dwell_sel.toggled.connect(lambda on: (ext.app.set_setting("dwell_select", on), self.dwell.setEnabled(on)))
        self.eyes_cart.toggled.connect(lambda on: ext.app.set_setting("eye_cart", on))
        self.eye_src.currentIndexChanged.connect(lambda _i: ext.controller.set_eye_source(self.eye_src.currentData()))
        v.addWidget(ctx.plots.muted_label(
            "Optional — labelled gesture capture (records raw EEG + IMU with a GO cue per repetition, 1–3 minutes)."))
        top = QtWidgets.QHBoxLayout()
        grid = QtWidgets.QGridLayout(); self.status = {}
        for i, key in enumerate(("Stream", "Contact", "Capture")):
            lab = QtWidgets.QLabel(f"<b>{key}:</b>"); val = QtWidgets.QLabel("—"); val.setWordWrap(True)
            grid.addWidget(lab, i, 0, QtCore.Qt.AlignTop); grid.addWidget(val, i, 1); self.status[key] = val
        grid.setColumnStretch(1, 1); grid.setRowStretch(3, 1)
        top.addLayout(grid, 3)
        box = QtWidgets.QGroupBox("Gesture capture (optional)"); form = QtWidgets.QFormLayout(box)
        self.posture = QtWidgets.QComboBox(); self.posture.addItems(POSTURES)
        self.notes = QtWidgets.QLineEdit(); self.notes.setPlaceholderText("glasses, hair, room, anything unusual")
        self.length = QtWidgets.QComboBox()
        for key, pr in protocol.PRESETS.items():
            st = protocol.build(0, pr["calib"], pr["test"], pr["negatives"])
            self.length.addItem(f"~{protocol.duration_s(st) / 60:.0f} min · {sum(x.kind == 'trial' for x in st)} "
                                f"repetitions ({pr['calib']} calibration + {pr['test']} test per gesture)", key)
        self.length.setCurrentIndex(self.length.findData(protocol.DEFAULT_PRESET))
        self.length.setToolTip("A capture stays within 1–3 minutes. For more data, run several short captures "
                               "(each is its own folder; F2 pools them).")
        self.sound = QtWidgets.QCheckBox("GO tone, eyes-open tone, stop tone"); self.sound.setChecked(True)
        self.duration = QtWidgets.QLabel("")
        for label, w in (("Posture", self.posture), ("Notes", self.notes),
                         ("Length", self.length),
                         ("Sound", self.sound), ("Planned", self.duration)):
            form.addRow(label, w)
        top.addWidget(box, 2)
        v.addLayout(top)
        row = QtWidgets.QHBoxLayout()
        self.window_btn = QtWidgets.QPushButton("Open capture window")
        self.start_btn = QtWidgets.QPushButton("▶ Start capture (sign-in screen)")
        self.stop_btn = QtWidgets.QPushButton("■ Stop"); self.stop_btn.setEnabled(False)
        self.folder_btn = QtWidgets.QPushButton("Open folder"); self.folder_btn.setEnabled(False)
        for b in (self.window_btn, self.start_btn, self.stop_btn, self.folder_btn): row.addWidget(b)
        row.addStretch(); v.addLayout(row)
        v.addStretch(1)
        self.window_btn.clicked.connect(ext.show_window)
        self.start_btn.clicked.connect(ext.open_login)
        self.stop_btn.clicked.connect(lambda: ext.stop("stopped"))
        self.folder_btn.clicked.connect(ext.open_folder)
        self.length.currentIndexChanged.connect(self._planned)
        self._planned()

    def preset(self):
        return protocol.PRESETS[self.length.currentData()]

    def _camera_toggled(self, on):
        c = self.ext.controller
        if not on:
            c.camera_stop(); return
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Question); box.setWindowTitle("Use camera?")
        box.setText("Allow Muse Bistro to use the computer camera?")
        box.setInformativeText("The camera recenters the head pointer when you look straight at the screen and "
                               "shows your image in the kiosk (demo layout). Frames are analysed in memory and never "
                               "saved — unless you press “Record demo video”, which writes the kiosk window, camera "
                               "image included, to a local file.")
        allow = box.addButton("Allow camera", QtWidgets.QMessageBox.AcceptRole)
        box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not allow:
            self.cam_check.blockSignals(True); self.cam_check.setChecked(False); self.cam_check.blockSignals(False); return
        ok, msg = c.camera_start(str(self.ext.app.setting("camera_id", "") or "") or None)
        self.ext.app.show_status(msg, 8000)
        if not ok:
            self.cam_check.blockSignals(True); self.cam_check.setChecked(False); self.cam_check.blockSignals(False)

    def _record_clicked(self):
        c = self.ext.controller
        if c.recorder.active:
            path = c.record_stop()
            self.ext.app.show_status(f"Demo video saved: {path}", 12000)
            self._sync_rec_btn(); return
        else:
            ok, msg = c.record_start()
            self.ext.app.show_status(msg, 8000)
        self._sync_rec_btn()

    def _sync_rec_btn(self):
        """The button always says what it will do; never "Stop recording" — that is the app's EEG recording button."""
        r = self.ext.controller.recorder
        sec = int(r.seconds())
        self.rec_btn.setText(f"■ Stop demo video · {sec // 60}:{sec % 60:02d}" if r.active else "🎬 Record demo video")

    def _planned(self):
        pr = self.preset()
        steps = protocol.build(0, pr["calib"], pr["test"], pr["negatives"])
        self.duration.setText(f"{protocol.duration_s(steps) / 60:.1f} min, no pauses · repeat short captures for "
                              f"more data")

    def set_running(self, running):
        for w in (self.posture, self.notes, self.length, self.sound): w.setEnabled(not running)
        self.stop_btn.setEnabled(running)

    def update_texts(self):
        ext = self.ext
        self.kiosk_status.setText(ext.kiosk_status())
        self._sync_rec_btn()                                   # also when stopped in the kiosk (F9, click, close)
        lang = ext.controller.order.lang                       # follow a switch made in the window
        if self.lang_box.currentData() != lang:
            self.lang_box.blockSignals(True); self.lang_box.setCurrentIndex(self.lang_box.findData(lang)); self.lang_box.blockSignals(False)
        for k, val in ext.status_texts().items(): self.status[k].setText(val)
        blockers = ext.blockers() if ext.writer is None else []
        self.start_btn.setEnabled(ext.writer is None and not blockers)
        self.start_btn.setToolTip("\n".join(blockers) or "Open the capture window on its sign-in screen: the "
                                  "participant's ID (e.g. M01) is entered there, like signing in to order")

    def clear(self):
        pass


class FoodOrder(Extension):
    id = "food_order"
    name = "Food order (demo)"
    version = "0.1.0"
    requires_api = 3
    category = "Other"
    description = "Order food with head and eye gestures (demo). F0: labelled gesture capture for tuning."

    mono = staticmethod(time.monotonic)      # replaceable in tests
    unix = staticmethod(time.time)

    @classmethod
    def supports(cls, spec):
        return spec.eeg.n >= 2 and spec.imu.n >= 6

    # ---- lifecycle -----------------------------------------------------------------------------------------------
    def activate(self, app):
        self.fs = float(app.spec.eeg.fs)
        self.channels = list(app.spec.eeg.names)
        self.imu_names = list(app.spec.imu.names)
        self.writer = self.window = self.last_folder = None
        self.steps, self.step_i, self.phase, self.phase_end = [], -1, "idle", None
        self.label = self.pending = None
        self.pause_requested = False
        self.esc_at = None
        self.last_subject = None
        self.last_eeg_mono = self.last_contact = None
        self.contact_every_s = 2.0
        self.eyes_tone_at = None
        self.cues = Cues(enabled=str(app.setting("sound", True)).lower() in ("true", "1"))
        self.imu_fs = float(app.spec.imu.fs)
        self.controller = Controller(self)
        self._timer = QtCore.QTimer(); self._timer.setInterval(40); self._timer.timeout.connect(self._tick)
        self._timer.setTimerType(QtCore.Qt.PreciseTimer)
        self.tab = app.add_tab(FoodOrderTab(app.view, self))
        self.tab.sound.setChecked(self.cues.enabled)
        self.tab.dwell.setValue(float(app.setting("dwell_s", 1.5)))
        self.tab.lang_box.blockSignals(True)
        self.tab.lang_box.setCurrentIndex(self.tab.lang_box.findData(self.controller.order.lang))
        self.tab.lang_box.blockSignals(False)
        self.tab.dwell_sel.setChecked(self.controller.opt("dwell_select")); self.tab.dwell.setEnabled(self.tab.dwell_sel.isChecked())
        self.tab.blink_sel.setChecked(self.controller.opt("eye_details"))
        self.tab.eyes_cart.setChecked(self.controller.opt("eye_cart"))
        self.tab.eye_src.blockSignals(True)
        self.tab.eye_src.setCurrentIndex(self.tab.eye_src.findData(self.controller.eye_source()))
        self.tab.eye_src.blockSignals(False)

    def deactivate(self):
        self.stop("unloaded")
        self.controller.close()
        self._timer.stop()
        if self.window is not None:
            self.window.on_closed = lambda: None; self.window.close(); self.window = None

    def on_connected(self, name):
        self.last_eeg_mono = None

    def on_disconnected(self):
        self.stop("disconnected")
        self.last_eeg_mono = None

    # ---- streams (GUI thread) ------------------------------------------------------------------------------------
    def on_eeg_samples(self, x, ts_raw):
        now = self.mono()
        self.last_eeg_mono = now
        if self.writer is not None: self.writer.samples("eeg", np.asarray(x, float), np.asarray(ts_raw, float), now)
        self.controller.on_eeg(x, ts_raw)

    def on_imu_samples(self, x, ts_raw):
        if self.writer is not None:
            self.writer.samples("imu", np.asarray(x, float), np.asarray(ts_raw, float), self.mono())
        self.controller.on_imu(x, ts_raw)

    # ---- kiosk ----------------------------------------------------------------------------------------------------
    def set_dwell(self, seconds):
        self.app.set_setting("dwell_s", float(seconds))
        if self.controller.head is not None: self.controller.head.cfg["dwell_s"] = float(seconds)

    def kiosk_status(self):
        c = self.controller
        if c.head is None:
            return f"Gestures unavailable ({c.reuse_error}) — keyboard and mouse only."
        h, e = c.head, c.eyes
        yaw, pitch = h.last
        parts = [f"head {'calibrated' if h.calibrated else 'default axes'} · yaw {yaw:+.0f}° pitch {pitch:+.0f}°",
                 f"double blink {'ready' if e.blink_ready else 'not calibrated'}",
                 f"eye closure {'ready' if e.closure_ready else 'not calibrated'}"]
        if c.window is not None: parts.append(f"window open · {c.order.screen}" + (" · calibrating" if c.calib else ""))
        if c.camera is None: parts.append(f"camera unavailable ({c.camera_why})")
        elif c.camera.running: parts.append(f"camera on ({c.camera.device_name}) — {facing_caption(c.cam_res)}")
        if c.recorder.active: parts.append(f"● recording {c.recorder.seconds():.0f} s → {c.last_video.name}")
        elif c.last_video: parts.append(f"last video: {c.last_video.name}")
        return " · ".join(parts)

    # ---- readiness ------------------------------------------------------------------------------------------------
    def eeg_silence(self):
        return None if self.last_eeg_mono is None else self.mono() - self.last_eeg_mono

    def eeg_stalled(self):
        s = self.eeg_silence()
        return s is not None and s > STALL_S

    def contact(self):
        """Contact per channel over the last 2 s — "No signal" when no EEG arrived for STALL_S (old samples
        would otherwise look Good)."""
        st, need = self.app.store, int(app_config.QUALITY_SEC * self.fs)
        if self.eeg_stalled(): return {n: "No signal" for n in self.channels}
        if st.eeg.n < need: return None
        return {n: q[0] for n, q in zip(self.channels, contact_quality(st.eeg.get(need), self.fs))}

    def blockers(self, lang="en"):
        """Why a capture cannot start now (empty = ready). lang="vi" for the participant's sign-in screen."""
        vi = lang == "vi"
        out = []
        if not self.app.is_streaming:
            out.append("chưa kết nối tai nghe." if vi else "Connect the headset and wait for the stream.")
        elif self.eeg_silence() is None or self.eeg_stalled():
            out.append("tai nghe không gửi EEG — hãy ngắt và kết nối lại." if vi else
                       "No EEG is arriving — the headset stopped sending. Disconnect and reconnect it.")
        q = self.contact() or {}
        dead = [c for c in ("TP9", "AF7", "AF8", "TP10") if q.get(c) == "No signal"]   # "Bad" still records usable
        if dead:                                                                     # blinks (TP often reads Bad)
            out.append(f"điện cực {', '.join(dead)} không có tín hiệu." if vi else
                       "No signal on " + ", ".join(dead) + " (all four are recorded).")
        return out

    # ---- capture --------------------------------------------------------------------------------------------------
    def show_window(self):
        if self.window is None: self.window = CaptureWindow(self._key, self._window_closed, self._click)
        self.window.show(); self.window.raise_(); self.window.activateWindow()
        return self.window

    def open_login(self):
        """Start button: the window opens on a sign-in screen; the capture starts when an ID is entered."""
        if self.writer is not None: return False
        self.show_window().show_login(str(self.app.setting("subject", "") or ""), self._login, "")
        return True

    def _login(self, subject):
        """Sign-in screen → Enter. Returns the message to show under the field ("" = signed in and started)."""
        subject = capture.to_subject(subject)
        if not capture.valid_subject(subject):
            return "Mã gồm chữ không dấu, số, - hoặc _ (tối đa 32), ví dụ M01."
        b = self.blockers("vi")
        if b: return "Chưa thể bắt đầu: " + b[0]
        return "" if self.start(subject) else "Không bắt đầu được."

    def start(self, subject):
        if self.writer is not None or not capture.valid_subject(subject): return False
        b = self.blockers()
        if b: self.app.show_status("Cannot start: " + b[0], 8000); return False
        self.app.set_setting("subject", subject); self.app.set_setting("sound", self.tab.sound.isChecked())
        self.cues.enabled = self.tab.sound.isChecked()
        seed = int.from_bytes(np.random.default_rng().bytes(4), "little")
        pr = self.tab.preset()
        self.steps = protocol.build(seed, pr["calib"], pr["test"], pr["negatives"])
        folder = capture.new_folder(captures_root(), subject)
        config = dict(
            subject_id=subject, posture=self.tab.posture.currentText(), notes=self.tab.notes.text(),
            protocol=dict(seed=seed, preset=self.tab.length.currentData(), calib_reps=pr["calib"],
                          test_reps=pr["test"], negatives_n=pr["negatives"],
                          prompt_s=protocol.PROMPT_S, rest_s=protocol.REST_S, eyes_closed_tone_s=protocol.EYES_CLOSED_S,
                          gestures={k: dict(label=v[0], instruction=v[1], window_s=v[2]) for k, v in protocol.GESTURES.items()},
                          negatives={k: dict(label=v[0], instruction=v[1]) for k, v in protocol.NEGATIVES.items()},
                          segments={k: dict(label=v[0], instruction=v[1], seconds=v[2]) for k, v in protocol.SEGMENTS.items()},
                          steps=[s.to_dict() for s in self.steps]),
            device=dict(name=getattr(self.app.main_window, "device_name", "")), eeg_fs=self.fs,
            imu_fs=float(self.app.spec.imu.fs), channels=self.channels, imu_names=self.imu_names,
            contact_at_start=self.contact() or {}, started_unix=self.unix(), started_mono=self.mono(),
            versions=dict(app=musemonitor.__version__, extension=self.version, qt=QtCore.qVersion()),
            notes_on_times="Label times are when the GO cue was shown / its tone played, not movement onset. "
                           "recv_mono and *_mono share one clock; ts_raw_unix and *_unix the wall clock.")
        self.writer = capture.CaptureWriter(folder, config, self.channels, self.imu_names)
        self.last_subject = subject
        self.writer.log(f"start: subject {subject}, seed {seed}, {len(self.steps)} steps")
        self.last_folder = folder
        self.last_contact = None; self._log_contact()
        self.pending = self.label = None
        self.pause_requested = False
        self.tab.set_running(True); self.tab.folder_btn.setEnabled(True)
        self.show_window()
        self.step_i = -1
        self._next_step()
        self._timer.start()
        return True

    def _next_step(self):
        """Advance to the next step — or first hold in a pause the experimenter asked for (P). Space resumes by
        calling this again, so no step is skipped."""
        nxt = self.step_i + 1
        if self.pause_requested:
            self.pause_requested = False
            if nxt < len(self.steps) and self.steps[nxt].kind != "pause":
                self.label = None
                self._enter("pause", None); self.writer.log("pause (requested)")
                if self.window is not None: self.window.focus_steps()
                return
        self.step_i = nxt
        if self.step_i >= len(self.steps): self.stop("completed"); return
        st = self.steps[self.step_i]
        self.label = dict(step=st.index, kind=st.kind, name=st.name, set=st.set, rep=st.rep, bad=False)
        if st.kind == "pause":
            self._enter("pause", None); self.writer.log(f"pause (protocol: {st.name})")
            if self.window is not None: self.window.focus_steps()
            return
        self._enter("prep", st.prompt_s)

    def _enter(self, phase, seconds):
        now = self.mono()
        self.phase, self.phase_end = phase, (None if seconds is None else now + seconds)
        st = self.steps[self.step_i] if 0 <= self.step_i < len(self.steps) else None
        if phase == "prep": self.label["prompt_mono"] = now
        elif phase == "go":
            self._flush_pending()                                  # a bad mark for the previous step is no longer possible
            self.label.update(go_mono=now, go_unix=self.unix())
            self._beep("go", f"GO step {st.index} {st.name}")
            self.eyes_tone_at = now + protocol.EYES_CLOSED_S if st.name == "eyes_closed" else None
        elif phase == "rest":
            self.label.update(end_mono=now, end_unix=self.unix())
        self._show()

    def _tick(self):
        if self.writer is None: self._timer.stop(); return
        now = self.mono()
        self._log_contact(now)
        if self.eeg_stalled(): self.stop("eeg_stalled"); return
        if self.eyes_tone_at is not None and now >= self.eyes_tone_at:
            self.eyes_tone_at = None; self._beep("done", f"open eyes, step {self.label['step']}")
        if self.phase_end is not None and now >= self.phase_end:
            st = self.steps[self.step_i]
            if self.phase == "prep": self._enter("go", st.action_s)
            elif self.phase == "go":
                if st.rest_s > 0: self._enter("rest", st.rest_s)
                else: self.label.update(end_mono=now, end_unix=self.unix()); self._finish_step()
            elif self.phase == "rest": self._finish_step()
        self._show()

    def _finish_step(self):
        self.pending, self.label = self.label, None            # written at the next GO: Backspace can still mark it
        self._next_step()

    def _flush_pending(self, writer=None):
        writer = writer or self.writer
        if self.pending is not None and writer is not None: writer.label(self.pending)
        self.pending = None

    def _show(self):
        if self.window is None or self.writer is None: return     # stopped: the end screen stays
        st = self.steps[self.step_i] if 0 <= self.step_i < len(self.steps) else None
        now = self.mono()
        left = None if self.phase_end is None else max(0.0, self.phase_end - now)
        trials = [s for s in self.steps if s.kind != "pause"]
        k = sum(1 for s in trials if s.index < (st.index if st else 0)) + (1 if st and st.kind != "pause" else 0)
        rest_total = protocol.duration_s(self.steps[self.step_i:]) if st else 0
        if self.phase == "pause" or st is None or st.kind == "pause":
            if st is not None and st.kind == "pause" and st.name == "calib_done":
                title = "Xong phần hiệu chỉnh"
                text = ("Nghỉ một chút. Tiếp theo là phần kiểm tra: các cử chỉ xuất hiện theo thứ tự ngẫu nhiên. "
                        "Bấm Space, Enter hoặc click vào cửa sổ để bắt đầu.")
            else:
                title = "Tạm nghỉ"
                text = "Thả lỏng, chớp mắt, xoay nhẹ cổ (không chạm tai nghe). Bấm Space, Enter hoặc click để tiếp tục."
            self.window.show_state(phase="pause", title=title, glyph="pause", set="", kind="pause",
                                   text=text,
                                   extra="", k=k, n=len(trials), fraction=0.0, seconds=None, left_total=rest_total,
                                   bad=False, paused=False, warning="")
            return
        if st.kind == "trial": title, text = protocol.GESTURES[st.name][:2]
        elif st.kind == "segment": title, text = protocol.SEGMENTS[st.name][:2]
        elif st.kind == "baseline": title, text = protocol.BASELINE
        else: title, text = protocol.NEGATIVES[st.name]
        extra = protocol.READ_ALOUD if st.name == "talk" else ""
        dur = {"prep": st.prompt_s, "go": st.action_s, "rest": st.rest_s}.get(self.phase) or 1.0
        fraction = 0.0 if self.phase != "go" else 1 - (left or 0) / dur
        bad = bool((self.label or {}).get("bad")) or (self.phase == "prep" and bool((self.pending or {}).get("bad")))
        self.window.show_state(phase=self.phase, title=title, text=text if self.phase != "rest" else
                               "Về giữa, nhìn vào màn hình, nghỉ.", extra=extra, glyph=st.name, set=st.set,
                               kind=st.kind, k=k, n=len(trials), fraction=fraction, seconds=left,
                               left_total=rest_total, bad=bad, paused=self.pause_requested, warning="")

    def _continue(self):
        """Space / Enter / click: leave a pause; after a capture: run another one for the same ID."""
        if self.writer is not None and self.phase == "pause":
            self.writer.log("continue after pause"); self._next_step(); self._show(); return True
        if self.writer is None and self.window is not None and self.window.state["phase"] in ("done", "stopped"):
            if self.last_subject is None: return False
            msg = self._login(self.last_subject)
            if msg: self.window.show_state(warning=msg)
            return not msg
        return False

    def _click(self):
        self._continue()

    def _key(self, ev):
        """Backspace: the current repetition (or the one just finished, until the next GO) was done wrong. P: pause
        after this step. Space / Enter: continue after a pause, or another capture at the end. Esc twice: stop;
        Esc at the end: close the window."""
        if ev.isAutoRepeat(): return
        k = ev.key()
        if k in (QtCore.Qt.Key_Space, QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and self._continue(): return
        if self.writer is None:
            if k == QtCore.Qt.Key_Escape and self.window is not None and self.window.state["phase"] in ("done", "stopped"):
                self.window.close()
            return
        now = self.mono()
        if k == QtCore.Qt.Key_Backspace:
            target = self.label if self.phase in ("go", "rest") else self.pending
            if target is not None and target.get("kind") == "trial":
                target.update(bad=True, bad_mono=now)
                self.writer.log(f"bad mark: step {target['step']} {target['name']}")
        elif k == QtCore.Qt.Key_P:
            self.pause_requested = not self.pause_requested
            self.writer.log("pause requested" if self.pause_requested else "pause request cancelled")
        elif k == QtCore.Qt.Key_Escape:
            if self.esc_at is not None and now - self.esc_at < 2.0: self.stop("stopped"); return
            self.esc_at = now
            if self.window: self.window.show_state(warning="Bấm Esc lần nữa để dừng")
            return
        self._show()

    def _window_closed(self):
        self.window = None
        self.stop("window_closed")

    def _log_contact(self, now=None):
        if self.writer is None: return
        now = self.mono() if now is None else now
        if self.last_contact is not None and now - self.last_contact < self.contact_every_s: return
        st, need = self.app.store, int(app_config.QUALITY_SEC * self.fs)
        if st.eeg.n < need: return
        self.last_contact = now
        if self.eeg_stalled(): q = [("No signal", float("nan"), float("nan")) for _ in self.channels]
        else: q = [(lvl, float(s), float(m)) for lvl, s, m in contact_quality(st.eeg.get(need), self.fs)]
        self.writer.contact(now, q)

    def _beep(self, tone, what):
        if not self.cues.enabled: return
        t = self.mono(); self.cues.play(tone)
        if self.writer is not None: self.writer.log(f"sound {tone} ({what}) at mono {t:.4f}")

    def stop(self, reason):
        writer, self.writer = self.writer, None
        self._timer.stop()
        if writer is None: return
        self._flush_pending(writer)
        if self.label is not None and "go_mono" in self.label:      # stopped during a step's GO or rest
            self.label.setdefault("end_mono", self.mono()); self.label.setdefault("end_unix", self.unix())
            if self.phase == "go": self.label["note"] = "interrupted"
            writer.label(self.label)
        self.label = self.pending = None
        if self.cues.enabled: self.cues.play("done" if reason == "completed" else "retry")
        done = sum(1 for s in self.steps[:max(0, self.step_i)] if s.kind == "trial")
        writer.close(reason, dict(steps_reached=self.step_i, trials_done=done))
        self.phase, self.phase_end = "idle", None
        self.tab.set_running(False)
        if self.window is not None:
            word = "done" if reason == "completed" else "stopped"
            self.window.show_state(phase=word, kind="done", set="", left_total=None,
                                   title="Xong — cảm ơn bạn!" if reason == "completed" else "Đã dừng",
                                   text=("Dữ liệu đã được lưu." if reason == "completed" else
                                         f"Lý do: {reason}. Dữ liệu đến lúc dừng đã được lưu."),
                                   extra="", glyph="ready" if reason == "completed" else "pause", fraction=0.0,
                                   seconds=None, bad=False,
                                   warning="Tai nghe ngừng gửi EEG — kết nối lại" if reason == "eeg_stalled" else "")
        msg = ("Capture stopped: no EEG for over 2 s — reconnect the headset" if reason == "eeg_stalled"
               else f"Capture ended: {reason}")
        self.app.show_status(f"{msg} · {writer.folder.name}", 12000)

    def open_folder(self):
        if self.last_folder is not None:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.last_folder)))

    def status_texts(self):
        silence = self.eeg_silence()
        stream = ("not connected" if not self.app.is_streaming else
                  f"⚠ connected but NO EEG for {silence:.0f} s — reconnect the headset" if self.eeg_stalled() else
                  "waiting for EEG…" if silence is None else "streaming")
        q = self.contact()
        if self.writer is not None and 0 <= self.step_i < len(self.steps):
            st = self.steps[self.step_i]
            cap = (f"running · step {st.index + 1}/{len(self.steps)} ({st.kind} {st.name} {st.set}) · "
                   f"{self.writer.folder.name}")
        else:
            cap = "idle" + (f" · last: {self.last_folder.name}" if self.last_folder else "")
        return {"Stream": stream, "Contact": ", ".join(f"{c} {v}" for c, v in q.items()) if q else "—",
                "Capture": cap}
