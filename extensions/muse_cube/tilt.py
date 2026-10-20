"""Head tilt (roll) → turn a face. Qt-free; times are passed in.

A tilt counts when, from a head that was steady (no yaw / pitch movement) for ``steady_s``, the roll goes beyond the
threshold and stays there for ``hold_s`` while the yaw stays put. One tilt = one turn: the roll has to come back near
the centre before the next one. Not while the head gestures are locked (just after a nod / shake), and a tilt is
refused when the yaw moved during it (a shake carries roll too, but with a large yaw swing).

The threshold is NOT settled: 15° by default, or ``ratio`` × the user's calibrated tilt (at least ``min_deg``). The
tilt test (TiltTest) decides whether the tilt control is kept: ≥ 8/10 right on each side and no false tilt.
Synthetic tests only check the algorithm, not that people can use it.
"""
from collections import deque

DEFAULTS = dict(threshold_deg=15.0, min_deg=10.0, ratio=0.6, hold_s=0.4, steady_s=0.3, steady_speed=30.0,
                yaw_window_deg=6.0, release_ratio=0.4, lockout_s=0.8, baseline_gain=0.02)


class Tilt:
    def __init__(self, cfg=None):
        self.cfg = dict(DEFAULTS, **(cfg or {}))
        self.sign = 1.0                          # +1: positive roll = tilt right (set by the calibration)
        self.threshold = self.cfg["threshold_deg"]
        self.calibrated = False
        self.reset()

    def reset(self):
        self.baseline = 0.0
        self.hist = deque()                      # (t, yaw, pitch)
        self.steady_since = None
        self.arm = None                          # (direction, t start, yaw at start)
        self.fired_start = None                  # when the last recognised tilt began (the tilt test scores by it)
        self.need_release = False
        self.lock_until = -1e9
        self.roll = 0.0

    def calibrate(self, rolls):
        """Roll samples (degrees, raw sign) while the user tilted to the RIGHT and held. Returns (ok, message)."""
        rolls = [r for r in rolls if r == r]
        if len(rolls) < 5: return False, "no_data"
        base = sorted(rolls[:3])[1]                          # the head is still level at GO (reaction time)
        peak = max((r - base for r in rolls), key=abs)
        if abs(peak) < 8.0: return False, "too_small"
        self.sign = 1.0 if peak > 0 else -1.0
        self.threshold = max(self.cfg["min_deg"], self.cfg["ratio"] * abs(peak))
        self.calibrated = True
        self.reset()
        return True, ""

    def progress(self, now):
        """0..1 while a tilt is held (for the on-screen ring), signed by direction."""
        if self.arm is None: return 0.0
        d, t0, _ = self.arm
        return d * max(0.0, min(1.0, (now - t0) / self.cfg["hold_s"]))

    def update(self, now, yaw, pitch, roll_raw, locked=False):
        """One pose sample → +1 (tilt right), −1 (tilt left) or 0."""
        c = self.cfg
        roll = self.sign * roll_raw - self.baseline
        self.roll = roll
        self.hist.append((now, yaw, pitch))
        while self.hist and now - self.hist[0][0] > 1.0: self.hist.popleft()
        speed = 0.0
        if len(self.hist) >= 2:
            (t0, y0, p0), (t1, y1, p1) = self.hist[-2], self.hist[-1]
            speed = (abs(y1 - y0) + abs(p1 - p0)) / max(1e-3, t1 - t0)
        thr = self.threshold
        if abs(roll) < thr * 0.5 and speed < c["steady_speed"]:
            self.steady_since = self.steady_since or now
            if abs(roll) < thr * 0.3: self.baseline += c["baseline_gain"] * (self.sign * roll_raw - self.baseline)
        elif abs(roll) < thr * 0.5:
            self.steady_since = None
        if self.need_release:
            if abs(roll) < thr * c["release_ratio"]: self.need_release = False
            return 0
        if locked or now < self.lock_until:
            self.arm = None; return 0
        if self.arm is None:
            steady = self.steady_since is not None and now - self.steady_since >= c["steady_s"]
            if abs(roll) >= thr and steady:
                self.arm = (1 if roll > 0 else -1, now, yaw)
            return 0
        d, t0, y0 = self.arm
        if abs(yaw - y0) > c["yaw_window_deg"] or abs(roll) < thr * 0.8 or (roll > 0) != (d > 0):
            self.arm = None                      # yaw moved (a shake / turn), or it came back too soon
            self.need_release = abs(roll) >= thr * c["release_ratio"]
            return 0
        if now - t0 >= c["hold_s"]:
            self.fired_start = t0
            self.arm = None; self.need_release = True; self.lock_until = now + c["lockout_s"]
            self.steady_since = None
            return d
        return 0


# ---- the tilt test (usability check before keeping the tilt control) ------------------------------------------
TEST_PROMPTS = ["right"] * 10 + ["left"] * 10 + ["point_left", "point_right", "nod", "centre"] * 3
PROMPT_S = 4.0
PASS_HITS = 8


class TiltTest:
    """32 prompts of 4 s in a seeded order: tilt right ×10, tilt left ×10, and ×12 other movements (point left /
    right, nod, back to the centre) during which a tilt is a FALSE tilt.

    A tilt prompt is a hit only when exactly ONE tilt, on the asked side, was seen (a wrong side or a repeat makes it a
    miss: in the game both turn the cube wrongly). Passed: ≥ 8/10 hits on each side, no false tilt and no wrong-side
    tilt (the criterion agreed in the design). Failing switches the tilt control off (controller)."""

    def __init__(self, seed=0, start=0.0):
        import random
        self.prompts = list(TEST_PROMPTS)
        random.Random(seed).shuffle(self.prompts)
        self.start = start
        self.i = 0
        self.got = [[] for _ in self.prompts]        # tilts seen during each prompt
        self.done = False

    def current(self, now):
        i = int((now - self.start) // PROMPT_S)
        if i >= len(self.prompts): self.done = True; return None
        self.i = i
        return self.prompts[i]

    def fraction(self, now):
        return ((now - self.start) % PROMPT_S) / PROMPT_S

    def record(self, started, direction):
        """A tilt counts for the prompt shown when it BEGAN (not when it was recognised, up to ~0.4 s later), so a tilt
        started at the end of a prompt is not scored as false in the next one. Before the first prompt: ignored."""
        if started is None: return
        i = int((started - self.start) // PROMPT_S)
        if 0 <= i < len(self.prompts): self.got[i].append(direction)

    def result(self):
        hits = {"right": 0, "left": 0}
        false = wrong = repeats = 0
        for p, got in zip(self.prompts, self.got):
            if p in hits:
                want = 1 if p == "right" else -1
                if got == [want]: hits[p] += 1
                wrong += sum(1 for d in got if d != want)
                repeats += max(0, sum(1 for d in got if d == want) - 1)
            else:
                false += len(got)
        passed = hits["right"] >= PASS_HITS and hits["left"] >= PASS_HITS and false == 0 and wrong == 0
        return dict(right=hits["right"], left=hits["left"], false=false, wrong_side=wrong, repeats=repeats,
                    passed=passed, n_each=TEST_PROMPTS.count("right"))
