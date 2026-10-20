"""F0 gesture-capture protocol — pure Python (no Qt, no clock): a seed gives the same sequence every time.

Every gesture is performed ONCE per trial, at a GO tone, so each repetition has its own label (type, set, repetition,
GO time) — debate/codex-food-order-extension-review.md asks for per-gesture labels, a calibration set kept apart
from a test set, and negative (natural-use) sequences:

    baseline (relax), slow head sweep (pointing range and gyro drift)
    calibration set   — gestures in blocks, CALIB_REPS each (thresholds are tuned on these)
    pause             — "calibration done": the participant continues with Space / Enter / a click
    test set, part 1  — gestures interleaved at random (detection is measured on these, never tuned on them)
    negative segments — natural movements that look like gestures (false positives per minute), N_NEGATIVES drawn
    test set, part 2

1–3 minutes per capture; repeat short captures for more data.

A trial: prompt (instruction, "get ready") → GO tone → action window → return to centre and rest.
"""
import random
from dataclasses import asdict, dataclass

# key: (label, instruction, action window s). The participant starts at GO and has the whole window.
GESTURES = {
    "point_left": ("Trỏ trái", "Xoay đầu NHẸ sang trái (như nhìn món bên trái), giữ khoảng 1 giây, rồi về giữa", 2.5),
    "point_right": ("Trỏ phải", "Xoay đầu NHẸ sang phải (như nhìn món bên phải), giữ khoảng 1 giây, rồi về giữa", 2.5),
    "turn_left": ("Quay hẳn trái", "Quay HẲN đầu sang trái rồi về giữa (đổi trang)", 2.0),
    "turn_right": ("Quay hẳn phải", "Quay HẲN đầu sang phải rồi về giữa (đổi trang)", 2.0),
    "nod": ("Gật", "Gật đầu một cái, như nói «có»", 2.0),
    "shake": ("Lắc", "Lắc đầu một cái, như nói «không»", 2.0),
    "look_up": ("Ngẩng giữ", "Ngẩng đầu lên, giữ 1 giây, rồi về giữa", 2.0),
    "double_blink": ("Nháy 2 lần", "Nháy mắt MẠNH 2 lần liền", 2.0),
    "eyes_closed": ("Nhắm mắt", "Nhắm mắt khi nghe bíp, mở mắt khi nghe «ting» (3 giây)", 4.0),
}
EYES_CLOSED_S = 3.0                       # the "ting" (done tone) inside the eyes_closed window

# natural movements that resemble gestures: (label, instruction)
NEGATIVES = {
    "look_around": ("Nhìn quanh", "Nhìn lần lượt các góc màn hình như đang xem món, quay đầu tự nhiên. KHÔNG làm cử chỉ."),
    "talk": ("Nói chuyện", "Đọc to đoạn chữ bên dưới; gật hoặc lắc khi nói nếu thấy tự nhiên."),
    "glance_turn": ("Liếc khi quay", "Vừa xoay đầu chậm qua lại vừa đưa mắt nhìn các góc màn hình."),
    "hands": ("Tay gần mặt", "Đưa tay lên mặt, gãi má, vuốt tóc phía trước. KHÔNG chạm vào tai nghe."),
}                                         # sitting relaxed with natural blinks = the baseline
BASELINE = ("Thư giãn", "Ngồi thư giãn, nhìn vào giữa màn hình, chớp mắt tự nhiên.")

# continuous segments that are not gestures: (label, instruction, seconds)
SEGMENTS = {
    "sweep": ("Quét hướng đầu", "Xoay đầu THẬT CHẬM từ trái sang phải rồi về, liên tục, như lướt qua 3 món "
                                "(trái – giữa – phải).", 10.0),
}
READ_ALOUD = ("Hôm nay tôi muốn một chiếc pizza cỡ vừa với nhiều phô mai, thêm nấm và ô liu, "
              "một ly trà đào ít đá và một phần bánh flan. Cảm ơn bạn.")

# A capture is kept within 1–3 minutes (user request). More data = several short captures, each its own folder,
# pooled in F2. Presets: calibration reps, test reps per gesture, number of natural-movement segments.
PRESETS = {"3min": dict(calib=1, test=2, negatives=2), "2min": dict(calib=1, test=1, negatives=1)}
DEFAULT_PRESET = "3min"
CALIB_REPS, TEST_REPS, N_NEGATIVES = (PRESETS[DEFAULT_PRESET][k] for k in ("calib", "test", "negatives"))
BASELINE_S, NEGATIVE_S = 15.0, 15.0
PROMPT_S, REST_S = 1.0, 1.0


@dataclass
class Step:
    index: int
    kind: str            # baseline | segment | trial | negative | pause
    name: str            # gesture / negative key ("" for a pause)
    set: str             # calib | test | "" (baseline, negatives and pauses belong to no set)
    rep: int             # repetition of this gesture within its set (0-based), -1 when not a trial
    action_s: float      # trial action window / segment length; 0 for a pause (participant-paced)
    prompt_s: float = 0.0
    rest_s: float = 0.0

    def to_dict(self):
        return asdict(self)


def _interleaved(names, reps, rng):
    """Every gesture ``reps`` times in random order, never the same gesture twice in a row: built one item at a time,
    each pick weighted by how many repetitions of that gesture are left (restart on the rare dead end)."""
    for _ in range(1000):
        left = {n: reps for n in names}; seq = []
        while any(left.values()):
            cand = [n for n in names if left[n] and (not seq or n != seq[-1])]
            if not cand: break
            n = rng.choices(cand, weights=[left[c] for c in cand])[0]
            seq.append(n); left[n] -= 1
        if len(seq) == reps * len(names): return seq
    raise RuntimeError("could not interleave the gestures")


def build(seed, calib_reps=CALIB_REPS, test_reps=TEST_REPS, n_negatives=N_NEGATIVES, gestures=tuple(GESTURES),
          negatives=tuple(NEGATIVES)):
    """One participant-paced pause, after the calibration set (not counted in the duration). The natural-movement segments are drawn at random (n_negatives of them), so
    several captures together cover them all."""
    rng = random.Random(seed)
    steps = []

    def add(kind, name, set_, rep, action_s, prompt_s=0.0, rest_s=0.0):
        steps.append(Step(len(steps), kind, name, set_, rep, action_s, prompt_s, rest_s))

    add("baseline", "relax", "", -1, BASELINE_S, PROMPT_S)
    for name, (_, _, secs) in SEGMENTS.items(): add("segment", name, "", -1, secs, PROMPT_S)
    for g in gestures:                                            # calibration: blocks, easier to learn
        for r in range(calib_reps): add("trial", g, "calib", r, GESTURES[g][2], PROMPT_S, REST_S)
    add("pause", "calib_done", "", -1, 0.0)                       # participant-paced: Space / Enter / click
    test = _interleaved(list(gestures), test_reps, rng)
    counts = {g: 0 for g in gestures}
    half = len(test) // 2
    neg = rng.sample(list(negatives), min(n_negatives, len(negatives)))
    for i, g in enumerate(test):
        if i == half:
            for n in neg: add("negative", n, "", -1, NEGATIVE_S, PROMPT_S)
        add("trial", g, "test", counts[g], GESTURES[g][2], PROMPT_S, REST_S); counts[g] += 1
    return steps


def duration_s(steps):
    """Planned time without the participant-paced pauses."""
    return sum(s.prompt_s + s.action_s + s.rest_s for s in steps)
