"""Head control for Muse Cube (R2): calibration, gestures → window commands, the tilt test.

Mapping (design §4, pointing adjusted — see the README): the three faces in view are pointed with yaw zones like the
food_order cards — left = FRONT, centre = TOP, right = RIGHT (as they sit on the screen). Pitch is left free for the
look-up hold, so pointing up never competes with it.

    point (yaw zones, 0.2 s settle)      select F / U / R (its outer layer)
    nod                                  next layer behind it: outer → middle (3×3) → opposite → outer
    tilt right / left (roll, held)       turn the selected layer clockwise / counter-clockwise (seen from that face)
    double blink (EEG)                   turn the selected layer clockwise         } only with a layer selected,
    jaw clench (EEG, 30–45 Hz)           turn the selected layer counter-clockwise } and a still head
    full turn right / left and back      turn the whole cube (view only): right face / left face to the front
    look up and hold                     turn the whole cube (view only): bottom to the front (as the ↑ key)
    shake                                undo
    nod, once solved                     new game

From the start of a tilt until the head is level again, pointing, nod, shake and full-turn events are ignored: the
face turned is the one selected when the tilt began, and a tilt's wobble is not taken for another gesture.
Calibration (about 15 s, 25 s with the eye / jaw steps): still 4 s (also eyes open and the jaw at rest), turn left
1.5 s, look up 1.5 s (head_motion_plus axes), tilt right 1.5 s (tilt direction and size), look straight 1.5 s →
recenter; then, with blink / jaw turns on, blink twice quickly ×3 (6 s) and clench the jaw ×2 (3 s). Esc skips; the
keyboard always works.

Camera (optional, after consent): head_motion_plus's CameraController + FacingGate recenter the head pointer when
the player looks straight at the screen and holds still for 1 s (at most every 5 s). Only the facing RESULT is used:
the preview signal is never connected, so no camera image is shown or kept — the window shows head_motion_plus's 3D
head model (HeadCanvas) following the IMU pose instead.

A double blink or a clench without a selected layer turns nothing (the window says "select a layer first"). Each one
is a move that a shake undoes — cheap errors, so no confirmation (design §2 rule: the cost of an error decides).
"""
import json
import time
from collections import deque

import numpy as np
from PySide6 import QtCore

from .jaw import Jaw
from .tilt import Tilt, TiltTest

STEPS = [("neutral", 4.0), ("left", 1.5), ("up", 1.5), ("tilt", 1.5), ("centre", 1.5)]
EEG_STEPS = [("blink", 6.0), ("jaw", 3.0)]
PREP_S, RESULT_S = 1.5, 1.0
SLOT_FACE = {0: "F", 1: "U", 2: "R"}
LIVE_S = 1.0


class CubeController:
    def __init__(self, ext, adapter, imu_fs, eeg_fs=None, names=None):
        self.ext = ext
        self.adapter = adapter
        self.window = None
        self.head = self.tilt = None
        self.reason = adapter.reason("head")
        if adapter.ok("head") and imu_fs:
            try:
                self.head = adapter.head_gestures(imu_fs, dict(dwell_s=1e9))     # no dwell: pointing never acts
            except Exception as e:
                self.head, self.reason = None, f"{type(e).__name__}: {e}"
        if self.head is not None and adapter.ok("tilt"): self.tilt = Tilt()
        self.eyes = self.jaw = None                        # EEG turns: double blink ↻, jaw clench ↺
        self.eeg_fs = eeg_fs
        if eeg_fs and names:
            if adapter.ok("eyes"):
                try: self.eyes = adapter.eye_commands(eeg_fs, list(names))
                except Exception: self.eyes = None
            if any(c in names for c in ("TP9", "TP10")): self.jaw = Jaw(eeg_fs, list(names))
        self.jaw_rest = None
        self.eeg_at = None                                 # time of the last EEG chunk (live plots)
        self.marks = {"double_blink": deque(maxlen=20), "clench": deque(maxlen=20)}
        self.cal_blink = None                              # the calibrated blink threshold (manual changes go back)
        self._apply_saved_bands()
        self.camera = self.gate = self.cam_res = self.canvas = None
        self.cam_error = ""
        if adapter.ok("camera") and self.head is not None:
            cam_mod = adapter.head_mod.camera
            self.camera = cam_mod.CameraController()
            self.camera.result.connect(self._cam_result)          # NOT .preview: no camera image anywhere
            self.camera.error.connect(self._cam_err)
            self.gate = cam_mod.FacingGate()
        self.last_imu = None
        self.calib = None
        self.test = None
        self.test_result = self._saved_test()
        self.flash = None                                  # (text, until): last gesture seen
        self.auto_calib = False                            # start the calibration on the next IMU chunk (once)
        self.timer = QtCore.QTimer(); self.timer.setInterval(40); self.timer.timeout.connect(self._tick)

    # ---- state ---------------------------------------------------------------------------------------------------
    def mono(self):
        return self.ext.mono()

    def head_live(self, now=None):
        now = self.mono() if now is None else now
        return self.head is not None and self.last_imu is not None and now - self.last_imu < LIVE_S

    def tilt_failed(self):
        """The last tilt test did not pass: the tilt control stays off until a test passes (design §5)."""
        return bool(self.test_result) and not self.test_result.get("passed", False)

    def tilt_on(self):
        """Tilt turns faces: available, ticked in the tab, and not switched off by a failed tilt test. Before any
        test it is on, provisionally (the tab says so)."""
        return (self.tilt is not None and not self.tilt_failed() and
                str(self.ext.app.setting("cube_tilt", True)).lower() in ("true", "1"))

    # ---- EOG / EMG: thresholds and filters by hand, data for the live plots -----------------------------------------
    BAND_DEFAULT = {"eog": (0.8, 8.0), "emg": (30.0, 45.0)}

    def band(self, kind):
        try:
            lo, hi = (float(v) for v in str(self.ext.app.setting(f"cube_{kind}_band", "")).split(","))
            return lo, hi
        except (TypeError, ValueError):
            return self.BAND_DEFAULT[kind]

    def _apply_saved_bands(self):
        for kind in ("eog", "emg"):
            if self.band(kind) != self.BAND_DEFAULT[kind]:
                try: self.set_band(kind, *self.band(kind), save=False)
                except ValueError: pass

    def set_band(self, kind, lo, hi, save=True):
        """The EOG filter (eye_interaction's 0.8–8 Hz band-pass, replaced on this game's own estimator) or the EMG band
        (30–45 Hz). Thresholds were measured in the old band: adjust them or calibrate again."""
        from scipy.signal import butter
        lo, hi = float(lo), float(hi)
        if kind == "eog":
            if self.eyes is None: return False
            if not 0 < lo < hi < self.eeg_fs / 2: raise ValueError(f"band {lo}–{hi} Hz")
            self.eyes.est.sos = butter(2, (lo, hi), btype="bandpass", fs=self.eeg_fs, output="sos")
            self.eyes.est.zi = None
        else:
            if self.jaw is None: return False
            self.jaw.set_band(lo, hi)
        if save: self.ext.app.set_setting(f"cube_{kind}_band", f"{lo:g},{hi:g}")
        return True

    def threshold(self, kind):
        if kind == "eog": return None if self.eyes is None else self.eyes.blink_thr
        return None if self.jaw is None else self.jaw.threshold

    def calibrated_threshold(self, kind):
        return self.cal_blink if kind == "eog" else (None if self.jaw is None else self.jaw.calibrated)

    def set_threshold(self, kind, value):
        """By hand, after the calibration (or instead of it): blink prominence µV / jaw RMS µV."""
        value = float(value)
        if value <= 0: return False
        if kind == "eog" and self.eyes is not None: self.eyes.blink_thr = value
        elif kind == "emg" and self.jaw is not None: self.jaw.threshold = value; self.jaw.reset()
        else: return False
        return True

    def reset_threshold(self, kind):
        v = self.calibrated_threshold(kind)
        return v is not None and self.set_threshold(kind, v)

    def eog_view(self, seconds=6.0):
        """(times s, filtered µV — blink polarity up, threshold, single-blink times, double-blink times)."""
        e = self.eyes
        if e is None or self.eeg_at is None or not len(e.buf): return None
        fs = float(e.fs)
        y = np.asarray(e.buf[-int(seconds * fs):], dtype=float)
        t = self.eeg_at - (len(y) - 1 - np.arange(len(y))) / fs
        singles = [self.eeg_at - (e.n - a) / fs for a, _ in e.peaks]
        doubles = [self.eeg_at - (e.n - a) / fs for a in self.marks["double_blink"]]
        return t, y, e.blink_thr, singles, doubles

    def emg_view(self, seconds=6.0):
        """(times s, 30–45 Hz RMS µV, threshold, clench times)."""
        j = self.jaw
        if j is None or not j.hist: return None
        h = [(t, v) for t, v in j.hist if t >= j.hist[-1][0] - seconds]
        return np.array([t for t, _ in h]), np.array([v for _, v in h]), j.threshold, list(self.marks["clench"])

    def eeg_turns_on(self):
        return (self.eyes is not None or self.jaw is not None) and \
            str(self.ext.app.setting("cube_eyejaw", True)).lower() in ("true", "1")

    def methods(self, live=True):
        """The ways a selected layer can be turned without keys / mouse right now."""
        out = []
        if live and self.tilt_on() and self.head is not None and self.head.calibrated: out.append("tilt")
        if self.eeg_turns_on():
            if self.eyes is not None and self.eyes.blink_ready: out.append("blink")
            if self.jaw is not None and self.jaw.ready: out.append("jaw")
        return out

    def steps(self):
        return STEPS + ([s for s in EEG_STEPS if (s[0] == "blink" and self.eyes is not None) or
                         (s[0] == "jaw" and self.jaw is not None)] if self.eeg_turns_on() else [])

    def attach(self, window):
        self.window = window
        if window is not None:
            window.on_key = self._key
            self.timer.start()
            if self.head is not None:                      # the 3D head model (not the camera image)
                if self.canvas is None and hasattr(self.adapter.head_mod, "HeadCanvas"):
                    self.canvas = self.adapter.head_mod.HeadCanvas(self.head.tracker)
                    self.canvas.setMinimumSize(0, 0)
                    self.canvas.set_theme({"base": "#0b0f18", "fg": "#e6edf3", "muted": "#8b949e"})
                if self.canvas is not None: window.set_head_canvas(self.canvas)
            # calibrate once, on the first IMU data — now if it is already flowing, or when the headset connects later
            self.auto_calib = self.head is not None and not self.head.calibrated
            if self.auto_calib and self.head_live(): self.auto_calib = False; self.start_calibration()
        else:
            self.timer.stop(); self.calib = self.test = None; self.auto_calib = False
            self.camera_stop(); self.canvas = None                 # the canvas belonged to the closed window

    # ---- calibration ---------------------------------------------------------------------------------------------
    def start_calibration(self):
        if self.head is None: return False
        self.test = None
        self.calib = dict(i=0, phase="prep", until=self.mono() + PREP_S, attempt=1, imu=[], rolls=[], eeg=[], filt=[],
                          message="", ok=None)
        self._beep("go"); self._push()
        return True

    def _calib_tick(self, now):
        c = self.calib
        if now < c["until"]: return
        steps = self.steps()
        key, secs = steps[c["i"]]
        if c["phase"] == "prep":
            if key == "tilt": self.head.recenter(); self.tilt.reset() if self.tilt else None
            c.update(phase="go", until=now + secs, imu=[], rolls=[], eeg=[], filt=[]); self._beep("go")
        elif c["phase"] == "go":
            ok, msg = self._finish(key, c)
            c.update(phase="result", until=now + RESULT_S, ok=ok, message=msg)
            self._beep("done" if ok else "retry")
        else:
            if c["ok"] or c["attempt"] >= 2:
                c.update(i=c["i"] + 1, attempt=1)
                if c["i"] >= len(steps):
                    self.calib = None; self._beep("done"); self._toast("calib.done")
                    done = getattr(self.ext, "calibration_finished", None)
                    if done: done()
                    return
            else:
                c["attempt"] += 1
            c.update(phase="prep", until=now + PREP_S, ok=None)

    def _finish(self, key, c):
        imu = np.concatenate(c["imu"], axis=1).T if c["imu"] else np.empty((0, 6))
        raw = np.concatenate(c["eeg"], axis=1) if c["eeg"] else None
        filt = np.concatenate(c["filt"], axis=1) if c["filt"] else None
        fs = int(self.eeg_fs or 0)
        if key == "neutral":
            if raw is not None and raw.shape[1] > 2 * fs:              # eyes open, jaw at rest (same still period)
                self.jaw_rest = raw[:, fs:]
                if self.eyes is not None and filt is not None: self.eyes.calibrate_open(raw[:, fs:], filt[:, fs:])
            n = int(self.head.fs)
            return self.head.calibrate("neutral", imu[-n:]) if len(imu) >= n // 2 else (False, "no_imu")
        if key == "blink":
            ok, msg = self.eyes.calibrate_blink(filt) if filt is not None else (False, "no_eeg")
            if ok: self.cal_blink = self.eyes.blink_thr
            return ok, msg
        if key == "jaw":
            if raw is None or self.jaw_rest is None: return False, "no_eeg"
            return self.jaw.calibrate(self.jaw_rest, raw)
        if key in ("left", "up"): return self.head.calibrate(key, imu)
        if key == "tilt":
            if self.tilt is None: return True, ""
            if not self.head.calibrated: return False, "need_axes"
            return self.tilt.calibrate(c["rolls"])
        ok = self.head.recenter()                                              # centre
        if self.tilt: self.tilt.reset()
        return (True, "") if ok else (False, "not_still")

    # ---- the tilt test -------------------------------------------------------------------------------------------
    def start_tilt_test(self, seed=None):
        if self.tilt is None or not self.head.calibrated: return False
        self.calib = None
        self.test = TiltTest(seed if seed is not None else int(time.time()), start=self.mono() + PREP_S)
        self._beep("go"); self._push()
        return True

    def _test_tick(self, now):
        t = self.test
        if now < t.start: return
        prev = t.i
        if t.current(now) is None:
            self.test_result = dict(t.result(), date=time.strftime("%Y-%m-%d %H:%M"), threshold=round(self.tilt.threshold, 1))
            self.ext.app.set_setting("cube_tilt_test", json.dumps(self.test_result))
            self.test = None
            self._beep("done" if self.test_result["passed"] else "retry")
            self.ext.tilt_test_finished(self.test_result)
        elif t.i != prev:
            self._beep("go")

    def _saved_test(self):
        try:
            return json.loads(self.ext.app.setting("cube_tilt_test", "") or "null")
        except (TypeError, ValueError):
            return None

    # ---- streams -------------------------------------------------------------------------------------------------
    def on_imu(self, x, ts_raw):
        if self.head is None: return
        now = self.mono()
        self.last_imu = now
        x = np.asarray(x, dtype=float)
        if self.eyes is not None: self.eyes.note_motion(x)
        if self.jaw is not None: self.jaw.note_motion(x, now)
        if self.auto_calib and self.window is not None and not self.calib and not self.test:
            self.auto_calib = False; self.start_calibration()
        c = self.calib
        if c and c["phase"] == "go": c["imu"].append(x[:6].copy())
        events = self.head.feed(x, float(ts_raw[-1]) if len(ts_raw) else float("nan"), now)
        yaw, pitch = self.head.last
        roll = self.adapter.roll(self.head.tracker) if self.tilt is not None else 0.0
        if c and c["phase"] == "go" and self.steps()[c["i"]][0] == "tilt": c["rolls"].append(roll)
        if c or self.window is None: return
        d = 0
        if self.tilt is not None and self.head.calibrated and (self.tilt_on() or self.test is not None):
            locked = now < self.head.lock_until or self.head.need_quiet
            d = self.tilt.update(now, yaw, pitch, roll, locked)
        if self.test is not None:
            if d:                                          # scored at the prompt where the tilt began
                self.test.record(self.tilt.fired_start, d); self._flash("tilt_r" if d > 0 else "tilt_l", now)
            return
        if d: self._tilt(d, now)
        holding = self.tilt is not None and (self.tilt.arm is not None or self.tilt.need_release)
        for e in events:                                   # mid-tilt: keep the face, ignore wobble gestures
            if holding and e[0] in ("nod", "shake", "page", "point"): continue
            self._event(e, now)

    # ---- camera: auto-recenter, no image ------------------------------------------------------------------------
    def camera_running(self):
        return self.camera is not None and self.camera.running

    def camera_start(self, device_id=None):
        """After the caller's consent. Returns (ok, message)."""
        if self.camera is None: return False, self.adapter.reason("camera") or "camera unavailable"
        self.gate.reset(); self.cam_res = None; self.cam_error = ""
        self.camera.start(device_id)
        return True, ""

    def camera_stop(self):
        if self.camera is not None and self.camera.running: self.camera.stop()
        self.cam_res = None

    def _cam_err(self, message):
        self.cam_error = message

    def _cam_result(self, res):
        """FacingGate: facing the screen AND the head still for 1 s (at most every 5 s) → recenter."""
        self.cam_res = res
        if self.head is None or self.calib or self.test: return
        now = self.mono()
        if self.gate.update(bool(res.get("facing", False)), self.head.tracker.is_still(), now) and self.head.recenter():
            if self.tilt: self.tilt.reset()
            if self.canvas is not None: self.canvas.mark_recentered("camera")
            self._flash("recentered_cam", now)

    def on_eeg(self, x, ts_raw=None):
        """Double blink → clockwise, jaw clench → counter-clockwise, on the selected layer."""
        if self.eyes is None and self.jaw is None: return
        now = self.mono()
        x = np.asarray(x, dtype=float)
        c = self.calib
        detect = not c and self.test is None
        ev = []
        if self.eyes is not None:
            filt, eye_ev = self.eyes.feed(x, now, detect=detect)
            ev += eye_ev
            if c and c["phase"] == "go": c["filt"].append(filt)
        if self.jaw is not None: ev += self.jaw.feed(x, now, detect=detect)
        if c and c["phase"] == "go": c["eeg"].append(x.copy())
        self.eeg_at = now
        for e in ev:                                   # double blink: the sample index of the pair's second blink
            if e[0] == "double_blink":                 # (not the moment it was judged, 0.6 s later; not wall time)
                self.marks[e[0]].append(self.eyes.done)
            elif e[0] in self.marks:
                self.marks[e[0]].append(now)
        if not detect or self.window is None or self.window.locked() or not self.eeg_turns_on(): return
        for e in ev:
            if e[0] == "double_blink": self._layer_turn(1, "blink", now)
            elif e[0] == "clench": self._layer_turn(-1, "jaw", now)

    def _layer_turn(self, d, source, now):
        w = self.window
        if not w.selected: self._flash("select_first", now); return
        w.command("turn", w.selected, d, w.depth)
        self._flash(source, now)

    def _tilt(self, d, now):
        w = self.window
        if not w.selected: return
        w.command("turn", w.selected, 1 if d > 0 else -1, w.depth)
        self._flash("tilt_r" if d > 0 else "tilt_l", now)

    def _event(self, e, now):
        w, kind = self.window, e[0]
        if kind == "point": w.command("select", SLOT_FACE[e[1]])
        elif kind == "page": w.command("view", "y", -e[1]); self._flash("page", now)
        elif kind == "look_up": w.command("view", "x", -1); self._flash("look_up", now)
        elif kind == "shake": w.command("undo"); self._flash("shake", now)
        elif kind == "nod":
            if (w.tutorial is not None and w.tutorial.finished) or (w.tutorial is None and w.game.solved):
                w.command("confirm")                       # into the real game / a new game
            elif w.selected: w.command("layer", 1)
            self._flash("nod", now)

    # ---- keys from the window ------------------------------------------------------------------------------------
    def _key(self, k):
        if k == QtCore.Qt.Key_Escape and (self.calib or self.test):
            self.calib = self.test = None; self._push(); return True
        if k == QtCore.Qt.Key_K: return self.start_calibration() or True
        if k == QtCore.Qt.Key_T: return self.start_tilt_test() or True
        if k == QtCore.Qt.Key_Home:
            if self.head is not None and self.head.recenter():
                if self.tilt: self.tilt.reset()
                if self.canvas is not None: self.canvas.mark_recentered("manual")
                self._toast("recentered")
            return True
        return False

    # ---- view ----------------------------------------------------------------------------------------------------
    def _beep(self, tone):
        cues = getattr(self.ext, "cues", None)
        if cues is not None and cues.enabled: cues.play(tone)

    def _flash(self, key, now):
        self.flash = (key, now + 1.4)

    def _toast(self, key):
        self.flash = (key, self.mono() + 2.5); self._push()

    def _tick(self):
        now = self.mono()
        if self.calib: self._calib_tick(now)
        elif self.test: self._test_tick(now)
        if self.canvas is not None and self.canvas.isVisible(): self.canvas.update()
        self._push(now)

    def extra(self, now=None):
        now = self.mono() if now is None else now
        live = self.head_live(now)
        out = dict(head=live, methods=self.methods(live), tilt=self.tilt.progress(now) if (self.tilt and live) else 0.0,
                   tilt_on=self.tilt_on(), tilt_failed=self.tilt_failed(), flash=self.flash[0] if self.flash and now < self.flash[1] else None,
                   head_reason=None if self.head is not None else self.reason, overlay=None,
                   signals=self.signal_strip(now),
                   camera=None if not self.camera_running() else
                   (self.cam_res.get("reason", "") if self.cam_res and self.cam_res.get("face") else
                    ("no face" if self.cam_res else "starting")))
        c = self.calib
        if c:
            steps = self.steps()
            key, secs = steps[c["i"]]
            left = max(0.0, c["until"] - now)
            span = PREP_S if c["phase"] == "prep" else secs if c["phase"] == "go" else RESULT_S
            out["overlay"] = dict(kind="calib", step=key, i=c["i"], n=len(steps), phase=c["phase"],
                                  progress=1 - left / span if span else 1.0, ok=c["ok"], message=c["message"])
        elif self.test:
            t = self.test
            if now < t.start:
                out["overlay"] = dict(kind="test", prompt=None, i=0, n=len(t.prompts), progress=1 - (t.start - now) / PREP_S)
            else:
                p = t.current(now)
                out["overlay"] = dict(kind="test", prompt=p, i=t.i, n=len(t.prompts), progress=t.fraction(now),
                                      got=t.got[t.i] if p else [])
        return out

    def signal_strip(self, now):
        """Small live traces for the game window (last 3 s): EOG and EMG with their thresholds."""
        if self.eeg_at is None or now - self.eeg_at > 2.0 or not self.eeg_turns_on(): return None
        out = {}
        v = self.eog_view(3.0)
        if v is not None:
            out["eog"] = (v[1][::4].tolist(), v[2])
        v = self.emg_view(3.0)
        if v is not None:
            out["emg"] = (v[1].tolist(), v[2])
        return out or None

    def _push(self, now=None):
        if self.window is not None: self.window.set_extra(self.extra(now))
