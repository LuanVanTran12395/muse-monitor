"""Participant instructions shown on the stimulus window before a session (no Qt here: text only).

Pages are built from the session configuration (duration, trials, rest, mode) so what the participant reads matches
what will happen. Shown before the session folder exists: reading time is not part of the recording.
"""
from .schedule import COMMANDS

LANGUAGES = {"vi": "Tiếng Việt", "en": "English"}
NEXT_KEYS_HINT = {"vi": "Space / → / bấm chuột: tiếp   ·   ←: quay lại", "en": "Space / → / click: next   ·   ←: back"}
NAV = {"vi": dict(next="tiếp", back="quay lại", click="bấm chuột", esc="huỷ", start="bắt đầu"),
       "en": dict(next="next", back="back", click="click", esc="cancel", start="start")}
REST_TITLE = {"vi": "Nghỉ", "en": "Break"}
REST_HINT = {"vi": "Chớp mắt, xoay nhẹ cổ, thư giãn", "en": "Blink, stretch your neck, relax"}
NEXT_BLOCK_TEXT = {"vi": "Khối tiếp theo bắt đầu sau", "en": "The next block starts in"}
COUNTDOWN_TEXT = {"vi": "Nhìn vào giữa màn hình — phiên bắt đầu sau", "en": "Look at the centre — starting in"}
CANCELLED_TEXT = {"vi": "Đã huỷ — chưa ghi dữ liệu", "en": "Cancelled — nothing recorded"}
# shown on the stimulus window during the session
CUE_TEXT = {"vi": "Nhìn vào: {name} — đếm số lần nó sáng", "en": "Look at: {name} — count its flashes"}
RESPOND_TEXT = {"vi": "Nhấn Space mỗi khi ô mục tiêu sáng", "en": "Press Space when your target flashes"}
REST_TEXT = {"vi": "Nghỉ — khối tiếp theo bắt đầu sau {s:.0f} giây", "en": "Rest — the next block starts in {s:.0f} s"}
ENDED_TEXT = {"vi": "Phiên đã kết thúc ({reason})", "en": "Session ended ({reason})"}
GET_READY_TEXT = {"vi": "Chuẩn bị…", "en": "Get ready…"}
QUESTION_TEXT = {"vi": "Ô mục tiêu đã sáng bao nhiêu lần?", "en": "How many times did the target flash?"}
QUESTION_HINT = {"vi": "Gõ số · ⌫ xoá · Enter xác nhận", "en": "Type the number · ⌫ delete · Enter confirm"}


def pages(plan, lang="vi"):
    """[{title, lines, demo}] — demo=True: the page shows the grid with the target outlined and flashing slowly."""
    cfg = plan.config
    minutes = max(1, round(plan.duration_s / 60))
    n_trials = len(plan.trials)
    example = COMMANDS[1]
    respond = cfg.mode == "response_assisted"
    if lang == "en":
        task = ("Count its flashes silently and press Space each time it flashes." if respond
                else "Count its flashes silently. Do not press any key while the cells flash.")
        return [
            dict(title="P300 experiment", icon="session", lines=[
                f"About {minutes} min · {n_trials} trials in {cfg.blocks} block{'s' if cfg.blocks > 1 else ''}.",
                "Nothing is recorded until the countdown at the end of these pages."]),
            dict(title="Your task", icon="task", lines=[
                "Before each trial one cell is outlined in yellow: that is your TARGET.",
                "Then the cells flash one after another, quickly and in random order.",
                f"Keep looking at the target. {task}"]
                + (["After each trial, type how many times the target flashed (it changes from trial to trial) "
                    "and press Enter."] if cfg.ask_s > 0 else [])),
            dict(title="Example", icon="demo", demo=True, lines=[
                f"Here the target is “{example}”. Look at it and count each time it turns white.",
                "The other cells flash too — ignore them."]),
            dict(title="Please", icon="notes", icons=["still", "blink", "gaze", "count"], lines=[
                "Sit still, relax your jaw and shoulders, keep your face and forehead loose.",
                "Try not to blink while the cells are flashing; blink during the short pauses between trials.",
                "Keep your eyes on the target cell, not on the edges of the screen.",
                "Do not guess or anticipate — just count."]),
            dict(title="Breaks", icon="breaks", lines=[
                (f"There is a {cfg.rest_s:.0f} s break between blocks: blink, stretch your neck, relax."
                 if cfg.blocks > 1 and cfg.rest_s > 0 else "The session runs without a long break."),
                "If you feel uncomfortable or tired, tell the experimenter — the session can be stopped at any time."]),
            dict(title="Ready?", icon="ready", lines=[
                "When you are ready, press Space (or click).",
                "A short countdown follows, then the first target is shown."]),
        ]
    task = ("Đếm thầm số lần ô đó sáng và nhấn Space mỗi khi nó sáng." if respond
            else "Đếm thầm số lần ô đó sáng. Không nhấn phím nào khi các ô đang sáng.")
    return [
        dict(title="Thí nghiệm P300", icon="session", lines=[
            f"Khoảng {minutes} phút · {n_trials} lượt, chia {cfg.blocks} khối.",
            "Chưa có dữ liệu nào được ghi cho tới khi đếm ngược ở cuối phần hướng dẫn."]),
        dict(title="Nhiệm vụ của bạn", icon="task", lines=[
            "Trước mỗi lượt, một ô được khoanh viền vàng: đó là ô MỤC TIÊU.",
            "Sau đó các ô lần lượt sáng lên, nhanh và theo thứ tự ngẫu nhiên.",
            f"Hãy nhìn vào ô mục tiêu. {task}"]
            + (["Cuối mỗi lượt, gõ số lần ô mục tiêu đã sáng (con số thay đổi theo từng lượt) rồi nhấn Enter."]
               if cfg.ask_s > 0 else [])),
        dict(title="Ví dụ", icon="demo", demo=True, lines=[
            f"Ở đây ô mục tiêu là “{example}”. Nhìn vào nó và đếm mỗi lần nó chuyển sang màu trắng.",
            "Các ô khác cũng sáng — hãy bỏ qua chúng."]),
        dict(title="Lưu ý", icon="notes", icons=["still", "blink", "gaze", "count"], lines=[
            "Ngồi yên, thả lỏng hàm, vai và cơ mặt; không nhíu trán.",
            "Cố gắng không chớp mắt khi các ô đang nhấp nháy; hãy chớp mắt trong khoảng nghỉ ngắn giữa các lượt.",
            "Giữ mắt nhìn vào ô mục tiêu, không nhìn ra mép màn hình.",
            "Đừng đoán trước — chỉ cần đếm."]),
        dict(title="Nghỉ giữa chừng", icon="breaks", lines=[
            (f"Giữa các khối có {cfg.rest_s:.0f} giây nghỉ: chớp mắt, xoay nhẹ cổ, thư giãn."
             if cfg.blocks > 1 and cfg.rest_s > 0 else "Phiên chạy liền, không có giờ nghỉ dài."),
            "Nếu thấy khó chịu hoặc mệt, hãy báo người thực hiện — có thể dừng bất cứ lúc nào."]),
        dict(title="Sẵn sàng?", icon="ready", lines=[
            "Khi đã sẵn sàng, nhấn Space (hoặc bấm chuột).",
            "Sau một lần đếm ngược ngắn, ô mục tiêu đầu tiên sẽ hiện ra."]),
    ]
