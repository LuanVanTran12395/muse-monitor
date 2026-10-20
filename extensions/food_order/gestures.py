"""Head and eye gestures for the kiosk, built on the existing extensions' estimators (loaded read-only by _reuse):

    head   head_motion_plus.PoseTracker → yaw / pitch (pose_angles) → point · dwell select · page · nod · shake · look up
    eyes   eye_interaction.EyeEstimator (filter, blink calibration) + relative_alpha → EyeCommands: double blink,
           eyes closed — forehead electrodes only

No Qt: times are passed in (``now``, monotonic seconds). Calibration follows the two extensions' rules (same
capture lengths and acceptance numbers, cited below) but runs as one short guided sequence in the kiosk.

Default thresholds: angles in degrees, speeds in °/s. The peak speeds measured in the F0 captures of 2026-10-19
(medians: point ≈ 65 °/s yaw, full turn ≈ 110, shake ≈ 150 with roll, nod ≈ 93 pitch, look-up ≈ 75) put the
boundaries; positions (angles) are used where possible, because they do not depend on how fast someone moves.
"""
import math
from collections import deque

import numpy as np
from scipy.signal import find_peaks

DEFAULTS = dict(
    zone_deg=8.0, hysteresis_deg=2.0,          # |yaw| < zone → middle card; ± hysteresis against flicker
    page_deg=25.0, page_return_deg=10.0, page_window_s=2.0,   # full turn beyond page_deg and back = next / previous page
    dwell_s=1.5, dwell_speed=20.0, cooldown_s=1.2,             # hold the head on a card to select it
    shake_swing_deg=8.0, shake_speed=80.0,     # ≥ 2 yaw reversals of ≥ swing within osc_window_s, peak speed ≥ …
    nod_swing_deg=6.0, nod_speed=50.0,         # the same on pitch
    osc_window_s=1.2, lockout_s=0.8,           # after a nod / shake: no pointing, paging or dwell for lockout_s …
    quiet_s=0.3, quiet_speed=20.0,             # … and until the head has been quiet this long (one shake = one "no")
    point_settle_s=0.2,                        # a new card is pointed only after the head stays in its zone this long
    look_up_deg=15.0, look_up_hold_s=0.7, look_up_speed=30.0,
    drift_still_s=2.0, drift_gain=0.05,        # still near the centre: pull yaw back towards 0 (gyro drift)
)


def reversals(values, swing):
    """Number of direction reversals in ``values``, counting only movements of at least ``swing`` (hysteresis)."""
    if len(values) < 3: return 0
    n, state, ext = 0, 0, values[0]             # state: 0 unknown, +1 rising, −1 falling; ext: extreme so far
    for v in values[1:]:
        if state == 0:
            if v - ext >= swing: state, ext = 1, v
            elif ext - v >= swing: state, ext = -1, v
        elif state == 1:
            if v > ext: ext = v
            elif ext - v >= swing: state, ext, n = -1, v, n + 1
        else:
            if v < ext: ext = v
            elif v - ext >= swing: state, ext, n = 1, v, n + 1
    return n


class HeadGestures:
    """Pose from head_motion_plus.PoseTracker; events from yaw / pitch."""

    def __init__(self, head_module, fs, cfg=None):
        self.h = head_module
        self.cfg = dict(DEFAULTS, **(cfg or {}))
        self.tracker = head_module.PoseTracker(fs)
        self.fs = float(fs)
        self.calibrated = False
        self.neutral_bias = None
        self.left_vector = None
        self.reset_runtime()

    def reset_runtime(self):
        self.hist = deque()                    # (t, yaw, pitch)
        self.slot = 1
        self.yaw_offset = 0.0
        self.page_arm = None                   # (direction, t)
        self.lock_until = -1e9
        self.dwell_slot, self.dwell_start, self.cool_until = None, None, -1e9
        self.up_since = None
        self.still_since = None
        self.need_quiet, self.quiet_since = False, None
        self.cand_slot, self.cand_since = 1, None
        self.last = (0.0, 0.0)

    # ---- calibration (rules of head_motion_plus: HeadMotionPlusTab._finish_capture) -----------------------------
    def calibrate(self, kind, rows):
        """kind: neutral | left | up; rows: N × 6 IMU samples (acc g, gyro °/s) captured for that step.
        Returns (ok, message). Same numbers as head_motion_plus: still = gyro spread < 3 °/s and acc spread < 0.08 g;
        a turn must integrate to ≥ 12°."""
        rows = np.asarray(rows, dtype=float)
        if rows.ndim != 2 or rows.shape[1] < 6 or len(rows) < 5 or not np.all(np.isfinite(rows)):
            return False, "Dữ liệu IMU không hợp lệ."
        acc, gyro = rows[:, :3], rows[:, 3:6]
        if kind == "neutral":
            bias = gyro.mean(axis=0)
            if (np.max(np.linalg.norm(gyro - bias, axis=1)) > 3.0 or
                    np.max(np.linalg.norm(acc - acc.mean(axis=0), axis=1)) > 0.08 or
                    not 0.85 < np.linalg.norm(acc.mean(axis=0)) < 1.15):
                return False, "Đầu bị động — giữ yên rồi làm lại."
            self.neutral_bias, self.left_vector = bias, None
            return True, ""
        if self.neutral_bias is None: return False, "Cần bước giữ yên trước."
        motion = np.sum(gyro - self.neutral_bias, axis=0) / self.fs
        if np.linalg.norm(motion) < 12.0: return False, "Cử động quá nhỏ hoặc đã quay về giữa sớm — làm lại."
        if kind == "left":
            self.left_vector = motion; return True, ""
        try:
            axes = self.h.axes_from_motions(self.left_vector, motion)
        except ValueError as e:
            return False, str(e)
        self.tracker.set_calibration(axes, self.neutral_bias)
        self.calibrated = True
        self.reset_runtime()
        return True, ""

    def recenter(self):
        ok = self.tracker.recenter()
        if ok: self.yaw_offset = 0.0; self.hist.clear()
        return ok

    # ---- runtime --------------------------------------------------------------------------------------------------
    def feed(self, x, ts, now):
        """IMU chunk (6 × n) → list of events: ("point", slot) · ("select", "dwell") · ("page", ±1) · ("nod",) ·
        ("shake",) · ("look_up",)."""
        self.tracker.add(x, ts)
        yaw, pitch, _ = self.h.pose_angles(self.tracker.q)
        return self.update(yaw - self.yaw_offset, pitch, now)

    def update(self, yaw, pitch, now):
        """The gesture rules on one pose sample (degrees; yaw + = the participant's left, pitch + = up)."""
        self.last = (yaw, pitch)
        c = self.cfg
        self.hist.append((now, yaw, pitch))
        while self.hist and now - self.hist[0][0] > max(c["osc_window_s"], c["page_window_s"]) + 0.2:
            self.hist.popleft()
        speed = self._speed()
        if self.need_quiet:                     # after a nod / shake: wait for a quiet head
            if speed < c["quiet_speed"]:
                self.quiet_since = self.quiet_since or now
                if now - self.quiet_since >= c["quiet_s"]:
                    self.need_quiet = False
                    while len(self.hist) > 1: self.hist.popleft()     # the movements during the lock are not new
            else:
                self.quiet_since = None
        ev = []
        recent = [(t, y, p) for t, y, p in self.hist if now - t <= c["osc_window_s"]]
        ys, ps = [y for _, y, _ in recent], [p for _, _, p in recent]
        locked = now < self.lock_until or self.need_quiet
        # oscillations first: they also cross the paging angle
        if not locked and reversals(ys, c["shake_swing_deg"]) >= 2 and self._peak_speed(recent, 1) >= c["shake_speed"]:
            ev.append(("shake",)); self._lock(now)
        elif not locked and reversals(ps, c["nod_swing_deg"]) >= 2 and self._peak_speed(recent, 2) >= c["nod_speed"]:
            ev.append(("nod",)); self._lock(now)
        locked = now < self.lock_until or self.need_quiet
        if not locked:
            # page: beyond page_deg, then back near the centre within page_window_s, a single excursion
            if abs(yaw) >= c["page_deg"] and self.page_arm is None:
                self.page_arm = (1 if yaw < 0 else -1, now)    # turning right (yaw −) = next page
            if self.page_arm is not None:
                d, t0 = self.page_arm
                if now - t0 > c["page_window_s"]: self.page_arm = None if abs(yaw) < c["page_deg"] else self.page_arm
                elif abs(yaw) <= c["page_return_deg"]:
                    ev.append(("page", d)); self.page_arm = None; self.dwell_start = None
            # look up and hold
            if pitch >= c["look_up_deg"] and speed < c["look_up_speed"]:
                self.up_since = self.up_since or now
                if now - self.up_since >= c["look_up_hold_s"]:
                    ev.append(("look_up",)); self.up_since = None; self._lock(now)
            elif pitch < c["look_up_deg"] - 3:
                self.up_since = None
            # point: zones with hysteresis (participant's left = screen left = slot 0)
            z, hy = c["zone_deg"], c["hysteresis_deg"]
            if self.page_arm is None:
                new = self.slot
                if yaw > z + (hy if self.slot != 0 else -hy): new = 0
                elif yaw < -z - (hy if self.slot != 2 else -hy): new = 2
                elif -z + hy < yaw < z - hy: new = 1
                if new != self.cand_slot: self.cand_slot, self.cand_since = new, now
                if (new != self.slot and self.cand_since is not None and
                        now - self.cand_since >= c["point_settle_s"]):
                    self.slot = new; ev.append(("point", new))
            # dwell
            if (self.page_arm is None and speed < c["dwell_speed"] and abs(yaw) < c["page_deg"] - 5 and
                    pitch < c["look_up_deg"] and now >= self.cool_until):
                if self.dwell_slot != self.slot or self.dwell_start is None:
                    self.dwell_slot, self.dwell_start = self.slot, now
                elif now - self.dwell_start >= c["dwell_s"]:
                    ev.append(("select", "dwell")); self.dwell_start = None; self.cool_until = now + c["cooldown_s"]
            else:
                self.dwell_start = None
        # gyro drift: still near the centre → pull yaw back slowly
        if speed < 5.0 and abs(yaw) < c["zone_deg"]:
            self.still_since = self.still_since or now
            if now - self.still_since >= c["drift_still_s"]: self.yaw_offset += yaw * c["drift_gain"]
        else:
            self.still_since = None
        return ev

    def dwell_fraction(self, now):
        if self.dwell_start is None: return 0.0
        return max(0.0, min(1.0, (now - self.dwell_start) / self.cfg["dwell_s"]))

    def _lock(self, now):
        self.lock_until = now + self.cfg["lockout_s"]
        self.need_quiet, self.quiet_since = True, None
        self.page_arm, self.dwell_start, self.up_since = None, None, None
        last = self.hist[-1] if self.hist else None             # forget the movement that was just recognised
        self.hist.clear()
        if last: self.hist.append(last)

    def _speed(self):
        if len(self.hist) < 2: return 0.0
        (t0, y0, p0), (t1, y1, p1) = self.hist[-2], self.hist[-1]
        dt = max(1e-3, t1 - t0)
        return math.hypot(y1 - y0, p1 - p0) / dt

    @staticmethod
    def _peak_speed(rows, col):
        if len(rows) < 2: return 0.0
        a = np.asarray(rows, dtype=float)
        dt = np.maximum(np.diff(a[:, 0]), 1e-3)
        return float(np.max(np.abs(np.diff(a[:, col])) / dt))


SOURCES = {"tp": ("TP9", "TP10"), "af": ("AF7", "AF8"), "diff": ("AF7−TP9", "AF8−TP10")}


class EyeCommands:
    """Deliberate eye commands on top of eye_interaction's EyeEstimator (its 0.8–8 Hz filter and its blink
    calibration rule) and its relative_alpha.

    Signal ``source`` (default "tp"): which pair of channels feeds the estimator, which reads them in the AF7 / AF8
    slots: "tp" = TP9 / TP10, "af" = AF7 / AF8, "diff" = AF7−TP9 / AF8−TP10. Replaying the 2026-10-19 captures with
    the same rules: TP found 5 / 9 double blinks at 0.33 false / min and 4 / 4 eye closures at 0.07 false / min,
    against AF 3 / 9 at 0.60 and 1 / 4 at 2.40 (diff in between). Muse references every channel to Fpz on the
    forehead, so blinks reach TP9 / TP10 through the reference; behind the ears, gaze shifts disturb them less; and
    TP carries the eyes-closed alpha. The "Bad" contact label there reflects large amplitudes, not a useless signal.

    Measured on the 2026-10-19 captures (food_order F0): deliberate blinks are NOT larger than natural ones (median
    63 vs 52 µV) and their spacing (0.25–0.52 s) overlaps natural pairs, so a command double blink also needs a still
    head, two blinks of similar size and the user's own spacing (from calibration). Closing the eyes gives one large
    deflection, then a quiet forehead (0.5–8 Hz SD ≈ 4.4 µV, all < 6, vs ≈ 11 open) with more alpha (0.21 vs 0.14).

        double blink   two similar blinks at the calibrated spacing, isolated, head still
        eyes closed    a closing deflection, then quiet, blink-free, more forehead alpha, head still, for closed_s
    """

    def __init__(self, eye_module, fs, names, cfg=None, source="tp"):
        self.e = eye_module
        self.fs = int(fs)
        self.names = list(names)
        self.source = source if source in SOURCES else "tp"
        self.front = [names.index(n) for n in ("AF7", "AF8")]       # the slots EyeEstimator reads
        # still_s counts back from the filtered peak, which lags the blink by ~0.17 s (causal 0.8–8 Hz filter)
        self.cfg = dict(pair_min_s=0.15, pair_max_s=0.6, before_s=1.0, after_s=0.6, size_ratio=1.8, still_s=0.6,
                        closed_s=3.0, settle_s=0.6)    # closed_s: the user keeps the eyes closed until the tone;
        # 3 s rather than 2 because a staring, blink-free forehead lasting 2–2.5 s was the main false alarm
        self.cfg.update(cfg or {})
        self.est = eye_module.EyeEstimator(fs, names)
        self.sign, self.blink_thr = 1, None
        self.close_thr, self.quiet_thr = None, None
        self.open_activity = None
        self.close_sign = 1                    # polarity of the closing deflection relative to the blink sign
        self.open_alpha = self.alpha_thr = None
        self.reset_runtime()

    @property
    def blink_ready(self):
        return self.blink_thr is not None

    @property
    def closure_ready(self):
        return self.close_thr is not None

    def reset_runtime(self):
        self.buf = np.zeros(0)                 # sign · mean filtered forehead signal, last 6 s
        self.raw = np.zeros((2, 0))            # raw source pair, last 4 s (alpha)
        self.n = 0
        self.peaks = []                        # (absolute index, prominence) of blinks, last 6 s
        self.done = -1
        self.closing = None
        self.moved_at = -1e9                   # sample index of the last head movement
        self.blink_started = -1e9              # EyeCanvas reads these two
        self.closed_now = False

    def eye_estimate(self):
        return "closed" if self.closed_now else "open"

    def note_motion(self, imu, now=None):
        """eye_interaction's rule: gyro > 35 °/s or |acc| off by 0.25 g = moving."""
        x = np.asarray(imu, dtype=float)
        if x.ndim == 2 and x.shape[0] >= 6 and x.shape[1]:
            if np.max(np.linalg.norm(x[3:6], axis=0)) > 35 or np.max(np.abs(np.linalg.norm(x[:3], axis=0) - 1)) > 0.25:
                self.moved_at = self.n

    # ---- calibration ------------------------------------------------------------------------------------------
    def _alpha(self, raw):
        return self.e.relative_alpha(raw, self.fs) if raw.shape[1] >= 2 * self.fs else None

    def activity(self, x):
        """How much the forehead signal changes sample to sample (µV per sample): saccades and blinks make it large,
        closed eyes — and the slow tail the filter leaves after the lids close — keep it small."""
        x = np.asarray(x, dtype=float)
        return float(np.std(np.diff(x))) if len(x) > 2 else 0.0

    def calibrate_open(self, raw, filtered):
        self.est.calibrate_open(filtered)
        self.open_activity = self.activity(np.asarray(filtered, dtype=float).mean(axis=0))
        self.open_alpha = self._alpha(self.inputs(raw)[self.front])
        return True, ""

    def calibrate_blink(self, filtered):
        """'Blink twice quickly, three times': eye_interaction's threshold rule + this user's spacing."""
        if not self.est.calibrate_blinks(filtered):
            self.blink_thr = None
            return False, "Chưa thấy rõ các cái nháy — làm lại."
        self.sign, self.blink_thr = self.est.blink_sign, float(self.est.blink_threshold)
        x = self.sign * np.asarray(filtered, dtype=float).mean(axis=0)
        pk, _ = find_peaks(x, prominence=self.blink_thr, distance=int(0.12 * self.fs),
                           width=(max(2, int(0.04 * self.fs)), int(0.6 * self.fs)))
        gaps = np.diff(pk) / self.fs
        gaps = gaps[gaps < 0.9]
        if len(gaps):
            self.cfg["pair_min_s"] = float(max(0.15, 0.7 * gaps.min()))
            self.cfg["pair_max_s"] = float(min(0.8, max(0.35, 1.35 * gaps.max())))
        return True, ""

    def calibrate_closed(self, raw, filtered):
        """Eyes closed at the beep, opened at the end tone: the closing deflection, the quiet, the alpha."""
        if self.blink_thr is None: return False, "Cần bước nháy trước."
        x0 = self.sign * np.asarray(filtered, dtype=float).mean(axis=0)
        first0 = x0[: int(1.8 * self.fs)]
        if not len(first0): return False, "Thiếu dữ liệu."
        # the closing deflection can be strongest in the other polarity than the one chosen for blinks
        self.close_sign = 1 if first0.max() - np.median(x0) >= np.median(x0) - first0.min() else -1
        x = self.close_sign * x0; first = x[: int(1.8 * self.fs)]
        i = int(np.argmax(first)); peak = float(first[i] - np.median(x))
        a, b = i + int(self.cfg["settle_s"] * self.fs), len(x) - int(0.3 * self.fs)   # after the filter's rebound
        if peak < self.blink_thr or b - a < self.fs:
            self.close_thr = None; return False, "Chưa thấy lúc nhắm mắt — nhắm hẳn khi nghe bíp."
        closed_act = self.activity(x[a:b])
        closed_alpha = self._alpha(self.inputs(raw)[self.front][:, a:b])
        self.close_thr = max(self.blink_thr, 0.7 * peak)
        if self.open_activity and self.open_activity > 1.2 * closed_act:
            self.quiet_thr = float(np.sqrt(self.open_activity * closed_act))          # between open and closed
        else:
            self.quiet_thr = 1.5 * closed_act
        if closed_alpha is not None and self.open_alpha is not None and closed_alpha > 1.15 * self.open_alpha:
            self.alpha_thr = (closed_alpha + self.open_alpha) / 2
        else:
            self.alpha_thr = None                                      # quiet + no blinks only
        return True, ""

    # ---- runtime ----------------------------------------------------------------------------------------------
    def inputs(self, x):
        """The chunk with the chosen source in the AF7 / AF8 slots (where EyeEstimator reads)."""
        x = np.asarray(x, dtype=float)
        if self.source == "af": return x
        i = {n: self.names.index(n) for n in ("TP9", "AF7", "AF8", "TP10")}
        y = x.copy()
        if self.source == "tp":
            y[i["AF7"]], y[i["AF8"]] = x[i["TP9"]], x[i["TP10"]]
        else:
            y[i["AF7"]], y[i["AF8"]] = x[i["AF7"]] - x[i["TP9"]], x[i["AF8"]] - x[i["TP10"]]
        return y

    def feed(self, x, now, detect=True):
        """EEG chunk → (filtered, events): ("double_blink",) · ("eyes_closed",) · ("blink",)."""
        x = self.inputs(x)
        filtered, _ = self.est.feed(x, detect=False)
        ev = []
        if not filtered.shape[1]: return filtered, ev
        fs, c = self.fs, self.cfg
        self.buf = np.r_[self.buf, self.sign * filtered.mean(axis=0)][-6 * fs:]
        self.raw = np.concatenate((self.raw, x[self.front]), axis=1)[:, -4 * fs:]
        self.n += filtered.shape[1]
        if not detect or self.blink_thr is None: return filtered, ev
        origin = self.n - len(self.buf)
        tail = self.buf[-int(2.0 * fs):]
        t0 = self.n - len(tail)
        pk, pr = find_peaks(tail, prominence=self.blink_thr, width=(max(2, int(0.04 * fs)), int(0.6 * fs)),
                            distance=int(0.12 * fs))
        known = [p for p, _ in self.peaks]
        for i, prom in zip(pk, pr["prominences"]):
            a = t0 + int(i)
            if self.n - a < int(0.12 * fs) or any(abs(a - k) < int(0.1 * fs) for k in known): continue
            self.peaks.append((a, float(prom))); known.append(a)
            self.blink_started = now - (self.n - a) / fs
            ev.append(("blink",))
        if self.close_thr is not None and self.closing is None:     # a closing deflection, in its own polarity
            cp, cpr = find_peaks(self.close_sign * tail, prominence=self.close_thr,
                                 width=(max(2, int(0.04 * fs)), int(0.8 * fs)))
            for i in cp[::-1]:
                a = t0 + int(i)
                age = self.n - a
                if int(0.12 * fs) <= age <= int(0.6 * fs) and a > self.done and self.moved_at < a - c["still_s"] * fs:
                    self.closing = a; break
        self.peaks = [(a, p) for a, p in self.peaks if a >= origin]
        # double blink: similar blinks at the user's spacing, isolated, head still
        ps = [(a, p) for a, p in self.peaks if a > self.done]
        for j in range(1, len(ps)):
            (a, pa), (b, pb) = ps[j - 1], ps[j]
            if not c["pair_min_s"] <= (b - a) / fs <= c["pair_max_s"]: continue
            if max(pa, pb) / max(1e-6, min(pa, pb)) > c["size_ratio"]: continue
            if self.moved_at >= a - c["still_s"] * fs: continue
            before = [k for k, _ in self.peaks if a - c["before_s"] * fs <= k < a]
            after = [k for k, _ in self.peaks if b < k <= b + c["after_s"] * fs]
            age = (self.n - b) / fs                      # judge a pair once, right after it — never later, when an
            if not before and not after and c["after_s"] <= age <= c["after_s"] + 0.3:   # earlier blink scrolled away
                ev.append(("double_blink",)); self.done = b; self.closing = None
                break
        # eyes closed
        self.closed_now = False
        if self.closing is not None:
            since = (self.n - self.closing) / fs
            settle = int(c["settle_s"] * fs)
            later = [k for k, _ in self.peaks if k > self.closing + settle]
            seg = self.buf[max(0, self.closing - origin + settle):]
            moved = self.moved_at > self.closing
            quiet_known = since >= c["settle_s"] + 1.0 and len(seg) >= fs
            if later or moved or (quiet_known and self.activity(seg[-fs:]) > self.quiet_thr):
                self.closing = None
            else:
                self.closed_now = since >= c["settle_s"] + 0.5
                if since >= c["settle_s"] + c["closed_s"]:
                    span = int(min(self.raw.shape[1], (since - c["settle_s"]) * fs))
                    alpha = self._alpha(self.raw[:, -span:]) if self.alpha_thr is not None else None
                    if self.alpha_thr is None or (alpha is not None and alpha >= self.alpha_thr):
                        ev.append(("eyes_closed",))
                    self.closing = None
                    self.done = self.peaks[-1][0] if self.peaks else self.done
        return filtered, ev
