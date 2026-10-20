"""Food order extension, stage F0 (labelled gesture capture). Offscreen, fake clock, synthetic EEG / IMU."""
import csv
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PySide6 import QtCore, QtGui

from extensions.food_order import capture, protocol

REPO = Path(__file__).resolve().parents[1]


# ---- protocol (pure) -----------------------------------------------------------------------------------------
def test_protocol_labels_every_repetition_and_keeps_calibration_apart_from_test():
    a, b = protocol.build(7), protocol.build(7)
    assert [s.to_dict() for s in a] == [s.to_dict() for s in b]                   # same seed → same sequence
    trials = [s for s in a if s.kind == "trial"]
    for g in protocol.GESTURES:
        cal = [s for s in trials if s.name == g and s.set == "calib"]
        tst = [s for s in trials if s.name == g and s.set == "test"]
        assert [s.rep for s in cal] == list(range(protocol.CALIB_REPS))
        assert sorted(s.rep for s in tst) == list(range(protocol.TEST_REPS))
    cal_idx = [s.index for s in trials if s.set == "calib"]; test_idx = [s.index for s in trials if s.set == "test"]
    assert max(cal_idx) < min(test_idx)                                         # calibration first, in blocks
    test_names = [s.name for s in trials if s.set == "test"]
    assert all(x != y for x, y in zip(test_names, test_names[1:]))              # interleaved, no immediate repeat
    negs = [s.name for s in a if s.kind == "negative"]
    assert len(negs) == protocol.N_NEGATIVES and set(negs) <= set(protocol.NEGATIVES)
    pauses = [s for s in a if s.kind == "pause"]
    assert [x.name for x in pauses] == ["calib_done"] and a[0].kind == "baseline" and a[1].name == "sweep"
    assert max(cal_idx) < pauses[0].index < min(test_idx)                      # between calibration and test
    assert protocol.build(8) != a
    for pr in protocol.PRESETS.values():                                         # user request: 1–3 minutes
        assert 60 <= protocol.duration_s(protocol.build(1, pr["calib"], pr["test"], pr["negatives"])) <= 180


def test_writer_files_and_load(tmp_path):
    f1 = capture.new_folder(tmp_path, "M01", stamp="20260101_000000")
    f2 = capture.new_folder(tmp_path, "M01", stamp="20260101_000000")
    assert f1.name == "20260101_000000_M01" and f2.name.endswith("_M01_2")
    with pytest.raises(ValueError): capture.new_folder(tmp_path, "../x")
    w = capture.CaptureWriter(f1, dict(subject_id="M01"), ["TP9", "AF7"], ["acc_x", "gyro_x"])
    w.samples("eeg", np.ones((2, 3)), np.array([1.0, 2.0, 3.0]), 10.0)
    w.samples("imu", np.zeros((2, 2)), np.array([1.0, 2.0]), 10.0)
    w.label(dict(step=0, kind="trial", name="nod", set="calib", rep=0, go_mono=1.5, bad=True))
    w.contact(11.0, [("Good", 3.0, 0.5), ("Fair", 9.0, 2.0)])
    w.close("completed")
    s = capture.load(f1)
    assert s["config"]["completed"] and s["config"]["rows"] == dict(eeg=3, imu=2, labels=1, contact=1)
    assert s["labels"][0]["name"] == "nod" and s["labels"][0]["bad"] == "1"
    assert s["eeg_header"][:3] == ["index", "ts_raw_unix", "recv_mono"]


# ---- the extension in the app --------------------------------------------------------------------------------
class Sim:
    """Fake monotonic clock; EEG in 12-sample packets at 256 Hz and IMU in 3-sample packets at 52 Hz."""
    def __init__(self, w, ext):
        self.w, self.ext, self.now, self.silent = w, ext, 1000.0, False
        ext.mono = lambda: self.now
        ext.unix = lambda: self.now + 1.79e9
        self.n_eeg = self.n_imu = 0
        self.rng = np.random.default_rng(0)

    def run(self, seconds, capture_running=True):
        end = self.now + seconds
        while self.now < end:
            self.now += 0.02
            while not self.silent and (self.n_eeg + 12) / 256 <= self.now - 1000.0:
                x = self.rng.normal(0, 5, (4, 12)); ts = 1.79e9 + 1000.0 + (self.n_eeg + np.arange(12)) / 256
                self.n_eeg += 12; self.w.on_data(x, ts)
            while not self.silent and (self.n_imu + 3) / 52 <= self.now - 1000.0:
                x = self.rng.normal(0, 1, (6, 3)); ts = 1.79e9 + 1000.0 + (self.n_imu + np.arange(3)) / 52
                self.n_imu += 3; self.w.on_imu(x, ts)
            if capture_running and self.ext.writer is not None: self.ext._tick()


@pytest.fixture
def app_with_food(qapp, spec, settings, monkeypatch, tmp_path):
    from musemonitor.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path / "data"))
    ext_dir = tmp_path / "exts"
    shutil.copytree(REPO / "extensions" / "food_order", ext_dir / "food_order", ignore=shutil.ignore_patterns("__pycache__"))
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(ext_dir)]); w.resize(1200, 800); w.show()
    rec = next(r for r in w.extensions.records if r.id == "food_order")
    assert rec.status == "active", rec.error
    ext = rec.instance
    import sys
    proto = sys.modules[type(ext).__module__ + ".protocol"]                  # short segments: fast tests
    for k, v in dict(BASELINE_S=3.0, NEGATIVE_S=2.0).items(): monkeypatch.setattr(proto, k, v)
    ext.tab.length.setCurrentIndex(ext.tab.length.findData("3min")); ext.tab.sound.setChecked(True)
    yield w, ext
    if ext.window is not None: ext.window.on_closed = lambda: None
    w.connected = False; w.close()


def key(k):
    return QtGui.QKeyEvent(QtCore.QEvent.KeyPress, k, QtCore.Qt.NoModifier, "")


def connected(w):
    w.connected = w.streaming = True; w.device_name = "MuseS-TEST"


def rows(path):
    with open(path, newline="", encoding="utf-8") as f: return list(csv.DictReader(f))


def test_capture_runs_the_protocol_with_marks_pauses_and_labelled_times(app_with_food):
    w, ext = app_with_food
    connected(w)
    sim = Sim(w, ext); sim.run(3, capture_running=False)
    assert ext.blockers() == [], ext.blockers()
    assert ext.open_login() and ext.window.state["phase"] == "login" and ext.window.edit.isVisible()
    ext.window.edit.setText("T01"); ext.window.edit.returnPressed.emit()         # sign in → the capture starts
    assert ext.writer is not None and not ext.window.edit.isVisible(), ext.window.login_msg
    assert ext.app.setting("subject") == "T01"
    folder = ext.writer.folder
    assert folder.name.endswith("_T01") and ext.window.isVisible()
    marked = {}
    requested_pause = False
    for _ in range(4000):
        if ext.writer is None: break
        if ext.phase == "pause": ext._key(key(QtCore.Qt.Key_Space)); continue
        st = ext.steps[ext.step_i]
        if st.kind == "trial" and st.set == "test" and ext.phase == "go" and "go" not in marked:
            ext._key(key(QtCore.Qt.Key_Backspace)); marked["go"] = st.index        # wrong during its own GO
        elif (st.kind == "trial" and ext.phase == "prep" and "prep" not in marked and ext.pending
              and ext.pending.get("kind") == "trial" and ext.pending["set"] == "calib"):
            ext._key(key(QtCore.Qt.Key_Backspace)); marked["prep"] = ext.pending["step"]   # the one just finished
        if not requested_pause and st.set == "test" and ext.phase == "go":
            ext._key(key(QtCore.Qt.Key_P)); requested_pause = st.index
        sim.run(0.1)
    assert ext.writer is None
    cfg = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    assert cfg["completed"] and cfg["subject_id"] == "T01" and cfg["protocol"]["preset"] == "3min"
    labels = rows(folder / "labels.csv")
    steps = [s for s in ext.steps if s.kind != "pause"]
    assert [int(r["step"]) for r in labels] == [s.index for s in steps]           # every step once, none skipped
    gos = [float(r["go_mono"]) for r in labels]
    assert all(b > a for a, b in zip(gos, gos[1:])) and all(float(r["end_mono"]) > float(r["go_mono"]) for r in labels)
    bad = {int(r["step"]) for r in labels if r["bad"] == "1"}
    assert bad == {marked["go"], marked["prep"]}
    log = (folder / "log.txt").read_text(encoding="utf-8")
    assert "pause (requested)" in log and "pause (protocol: calib_done)" in log and "continue after pause" in log
    assert log.count("sound go") == len(steps) and "open eyes" in log            # GO tone per step, eyes-open tone
    eeg, imu = rows(folder / "eeg.csv"), rows(folder / "imu.csv")
    assert len(eeg) == cfg["rows"]["eeg"] > 1000 and len(imu) == cfg["rows"]["imu"] > 100
    assert float(eeg[0]["recv_mono"]) >= cfg["started_mono"] - 0.1
    assert len(rows(folder / "contact.csv")) >= 5


def test_capture_stops_when_the_eeg_goes_silent(app_with_food):
    w, ext = app_with_food
    connected(w); sim = Sim(w, ext); sim.run(3, capture_running=False)
    assert ext.start("T01")
    folder = ext.writer.folder
    sim.run(4)
    sim.silent = True; sim.run(2.5)
    assert ext.writer is None
    cfg = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    assert cfg["stop_reason"] == "eeg_stalled" and not cfg["completed"]
    assert "Tai nghe ngừng gửi EEG" in ext.window.state["warning"]
    assert any("No EEG" in b for b in ext.blockers()) and ext.start("T01") is False
    ext.open_login(); ext.window.edit.setText("T01"); ext.window.edit.returnPressed.emit()
    assert ext.writer is None and "không gửi EEG" in ext.window.login_msg       # the sign-in screen says why
    assert set(ext.contact().values()) == {"No signal"}


def test_sign_in_checks_the_id_and_escape_twice_stops(app_with_food):
    w, ext = app_with_food
    connected(w); sim = Sim(w, ext); sim.run(3, capture_running=False)
    ext.open_login()
    for bad in ("", "  "):
        ext.window.edit.setText(bad); ext.window.edit.returnPressed.emit()
        assert ext.writer is None and "ví dụ M01" in ext.window.login_msg
    from PySide6 import QtTest
    ext.window.edit.clear(); QtTest.QTest.keyClicks(ext.window.edit, "M 01")        # real typing: a space → _
    assert ext.window.edit.text() == "M_01"
    ext.window.edit.setText("Trần Đức 01"); ext.window._clean("Trần Đức 01")          # what a Vietnamese IME delivers
    assert ext.window.edit.text() == "Tran_Duc_01"
    assert capture.to_subject("../x y") == "x_y" and capture.to_subject("Nguyễn Văn") == "Nguyen_Van"
    assert ext.start("../x") is False
    ext.window.edit.setText("T02"); ext.window.edit.returnPressed.emit()
    assert ext.writer is not None and ext.writer.folder.name.endswith("_T02")
    sim.run(1)
    ext._key(key(QtCore.Qt.Key_Escape)); assert ext.writer is not None              # once: asks again
    ext._key(key(QtCore.Qt.Key_Escape)); assert ext.writer is None
    assert json.loads((ext.last_folder / "config.json").read_text())["stop_reason"] == "stopped"


def test_window_draws_every_step(qapp):
    from extensions.food_order.capture_window import CaptureWindow
    win = CaptureWindow(lambda e: None, lambda: None); win.resize(900, 600); win.show()
    for name in list(protocol.GESTURES) + list(protocol.NEGATIVES) + list(protocol.SEGMENTS) + ["pause", "ready"]:
        for phase in ("prep", "go", "rest", "pause", "done"):
            win.show_state(phase=phase, glyph=name, title=name, text="x " * 40, k=3, n=10, fraction=0.5, seconds=1.2)
            assert not win.grab().isNull()
    win.on_closed = lambda: None; win.close()



def test_space_and_enter_continue_after_a_pause_with_real_key_events(app_with_food):
    from PySide6 import QtTest
    w, ext = app_with_food
    connected(w); sim = Sim(w, ext); sim.run(3, capture_running=False)
    ext.open_login(); win = ext.window
    win.edit.clear(); QtTest.QTest.keyClicks(win.edit, "T03"); QtTest.QTest.keyClick(win.edit, QtCore.Qt.Key_Return)
    assert ext.writer is not None and not win.edit.isVisible()
    for k in (QtCore.Qt.Key_Space, QtCore.Qt.Key_Return):
        QtTest.QTest.keyClick(win, QtCore.Qt.Key_P)
        for _ in range(400):
            if ext.phase == "pause": break
            sim.run(0.1)
        assert ext.phase == "pause" and "Space / Enter" in str(win.state) or ext.phase == "pause"
        QtTest.QTest.keyClick(win, k); sim.run(0.1)
        assert ext.phase != "pause"
    ext.stop("stopped")



def test_calibration_done_screen_continues_by_click_and_the_end_screen_starts_another_capture(app_with_food):
    from PySide6 import QtTest
    w, ext = app_with_food
    connected(w); sim = Sim(w, ext); sim.run(3, capture_running=False)
    assert ext.start("T01")
    first = ext.writer.folder
    for _ in range(2000):
        if ext.phase == "pause": break
        sim.run(0.1)
    st = ext.steps[ext.step_i]
    assert ext.phase == "pause" and st.name == "calib_done" and ext.window.state["title"] == "Xong phần hiệu chỉnh"
    QtTest.QTest.mouseClick(ext.window, QtCore.Qt.LeftButton); sim.run(0.1)        # a click continues
    assert ext.phase != "pause" and ext.steps[ext.step_i].set == "test"
    for _ in range(4000):
        if ext.writer is None: break
        sim.run(0.1)
    assert ext.window.state["phase"] == "done"
    QtTest.QTest.keyClick(ext.window, QtCore.Qt.Key_Space); sim.run(0.1)          # another capture, same ID
    assert ext.writer is not None and ext.writer.folder != first and ext.writer.folder.name.split("_")[2] == "T01"
    ext.stop("stopped")
    QtTest.QTest.keyClick(ext.window, QtCore.Qt.Key_Escape)                        # Esc at the end closes the window
    assert ext.window is None


def test_capture_blocks_on_a_dead_electrode_but_not_on_bad_contact(app_with_food, monkeypatch):
    w, ext = app_with_food
    connected(w)
    sim = Sim(w, ext); sim.run(3, capture_running=False)
    monkeypatch.setattr(ext, "contact", lambda: {"TP9": "Bad", "AF7": "Good", "AF8": "Good", "TP10": "Bad"})
    assert ext.blockers() == []                                     # TP often reads Bad and still carries blinks
    monkeypatch.setattr(ext, "contact", lambda: {"TP9": "Good", "AF7": "No signal", "AF8": "Good", "TP10": "Good"})
    assert any("AF7" in b for b in ext.blockers()) and any("AF7" in b for b in ext.blockers("vi"))
