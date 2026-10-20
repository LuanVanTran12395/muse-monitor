"""Muse Cube (R1): the model, the view, the game and the window (offscreen)."""
import importlib.util
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]


def _load():
    if "muse_cube_t" not in sys.modules:
        spec = importlib.util.spec_from_file_location("muse_cube_t", REPO / "extensions" / "muse_cube" / "__init__.py",
                                                      submodule_search_locations=[str(REPO / "extensions" / "muse_cube")])
        mod = importlib.util.module_from_spec(spec); sys.modules["muse_cube_t"] = mod; spec.loader.exec_module(mod)
    return sys.modules["muse_cube_t"]


@pytest.fixture(scope="module")
def mc(qapp):
    _load()
    return sys.modules


def cube_mod(mc): return mc["muse_cube_t.cube"]
def game_mod(mc): return mc["muse_cube_t.game"]


@pytest.mark.parametrize("n, stickers", [(2, 24), (3, 54)])
def test_a_cube_has_six_n_squared_stickers_and_four_turns_are_identity(mc, n, stickers):
    C = cube_mod(mc)
    c = C.Cube(n)
    assert c.sticker_count() == stickers and c.solved()
    for f in C.FACES:
        c.turn(f); assert not c.solved()
        for _ in range(3): c.turn(f)
        assert c.solved()


def test_turn_directions_follow_the_standard_notation(mc):
    C = cube_mod(mc)
    c = C.Cube(3); c.turn("R")                                       # R: the front's right column goes up
    corner = next(k for k in c.cubies if tuple(k["pos"]) == (2, 2, 2))
    assert corner["stickers"][(0, 1, 0)] == "red"
    c = C.Cube(3); c.turn("U")                                       # U: the front's top row goes left
    corner = next(k for k in c.cubies if tuple(k["pos"]) == (-2, 2, 2))
    assert corner["stickers"][(0, 0, 1)] == "blue"
    c = C.Cube(3)
    for _ in range(6):
        for f, t in (("R", 1), ("U", 1), ("R", 3), ("U", 3)): c.turn(f, t)
    assert c.solved()                                                # (R U R′ U′)⁶ = identity


@pytest.mark.parametrize("n", [2, 3])
def test_scramble_then_the_way_back_solves(mc, n):
    C = cube_mod(mc)
    c = C.Cube(n)
    moves = c.scramble(12, seed=7)
    assert len(moves) == 12 and all(C.AXIS[a[0]] != C.AXIS[b[0]] for a, b in zip(moves, moves[1:]))
    assert not c.solved()
    for f, t in c.way_back(): c.turn(f, t)
    assert c.solved()
    assert C.simplify([("R", 1), ("R", 3), ("U", 2), ("U", 2), ("F", 1)]) == [("F", 1)]


def test_the_view_maps_screen_faces_to_logical_ones(mc):
    C = cube_mod(mc)
    v = C.View()
    assert all(v.logical(f) == f for f in C.FACES)
    v.turn("y", 1)                                                   # → : the left face comes to the front
    assert v.logical("F") == "L" and v.logical("R") == "F" and v.screen("L") == "F"
    v.turn("x", -1)                                                  # ↑ : the bottom comes to the front
    assert v.logical("F") == "D"
    assert all(v.screen(v.logical(f)) == f for f in C.FACES)


@pytest.mark.parametrize("n", [2, 3])
def test_view_turns_then_turns_undo_and_hints_reach_solved(mc, n):
    G = game_mod(mc)
    g = G.Game(n, 8, seed=3, clock=iter(range(1000)).__next__)
    g.turn_view("y", 1); g.turn("F")                                 # turns the logical L
    assert g.cube.history[-1] == ("L", 1) and g.view_turns == 1
    g.turn_view("x", -1); assert g.undo() == ("L", 1) and g.undos == 1
    hint = g.show_hint(); assert g.hinted and hint[2] == len(g.cube.way_back())
    g.turn_view("y", 1); assert g.hint[0] == g.view.screen(g.cube.way_back()[0][0])   # renamed for the new view
    steps = 0
    while not g.solved:
        f, t, _, d = g.show_hint(); g.turn(f, t, d); steps += 1
        if steps % 2: g.turn_view("x", 1)
        assert steps < 30
    r = g.result()
    assert r["hinted"] is True and r["moves"] == steps + 1 and r["seconds"] > 0
    assert g.turn("F") is None and g.undo() is None                 # finished: nothing changes


def test_a_game_solved_alone_is_not_marked_hinted(mc):
    G = game_mod(mc)
    g = G.Game(2, 3, seed=1)
    for f, t in g.cube.way_back(): g.turn(g.view.screen(f), t)       # (the way back, but without show_hint)
    assert g.solved and not g.result()["hinted"]


# ---- the window ---------------------------------------------------------------------------------------------
@pytest.fixture
def board(mc):
    from PySide6 import QtWidgets
    B = mc["muse_cube_t.board"]
    changes = []
    w = B.CubeWindow(n=2, depth=5, seed=2, on_change=lambda k, v: changes.append((k, v)))
    w.resize(1226, 1064); w.show(); QtWidgets.QApplication.processEvents()
    w.changes = changes
    yield w
    w.close()


def _centre(poly):
    r = poly.boundingRect(); return r.center()


def test_window_defaults_to_glass_and_draws_both_styles(board, mc):
    from PySide6 import QtWidgets
    assert board.style == "glass"
    img = board.grab().toImage(); assert not img.isNull()
    front = [s for s in board.stickers]
    assert {f for _, f in front} == {"U", "F", "R"}                 # three faces seen from the base angle
    assert len(front) == 3 * 4                                       # 2×2: 4 stickers per visible face
    board.command("style", "classic"); QtWidgets.QApplication.processEvents(); board.grab()
    assert board.style == "classic" and board.changes[-1] == ("style", "classic")


def test_keyboard_solve_with_view_turns_and_real_key_events(board, mc):
    from PySide6 import QtCore
    from PySide6.QtTest import QTest
    keys = {"U": QtCore.Qt.Key_U, "D": QtCore.Qt.Key_D, "L": QtCore.Qt.Key_L, "R": QtCore.Qt.Key_R,
            "F": QtCore.Qt.Key_F, "B": QtCore.Qt.Key_B}
    g = board.game
    def key(*a):
        QTest.keyClick(*a); board.settle()                            # let each animated move finish
    key(board, QtCore.Qt.Key_Right)                       # look at another face first
    assert g.view_turns == 1 and not g.cube.history
    key(board, QtCore.Qt.Key_F); key(board, QtCore.Qt.Key_Backspace)
    assert g.moves == 1 and g.undos == 1 and not g.cube.history
    key(board, QtCore.Qt.Key_H); assert g.hint is not None
    while not g.solved:
        f, t, _, d = g.show_hint()
        assert d == 0                                                 # the way back of a scramble: outer layers
        for _ in range(2 if t == 2 else 1):
            key(board, keys[f], QtCore.Qt.ShiftModifier if t == 3 else QtCore.Qt.NoModifier)
        key(board, QtCore.Qt.Key_Down)
    assert g.solved and g.hinted
    key(board, QtCore.Qt.Key_Space); assert not board.game.solved and board.game.moves == 0
    key(board, QtCore.Qt.Key_G); assert board.style == "classic"
    key(board, QtCore.Qt.Key_N); assert board.lang == "en" and board.changes[-1] == ("lang", "en")


def test_mouse_picks_a_face_then_turns_it_and_the_switch_changes_style(board, mc):
    from PySide6 import QtCore, QtWidgets
    from PySide6.QtTest import QTest
    g = board.game
    right = next(poly for poly, f in board.stickers if f == "R")
    QTest.mouseClick(board, QtCore.Qt.LeftButton, pos=_centre(right).toPoint())
    assert board.selected == "R"
    QtWidgets.QApplication.processEvents(); board.grab()
    cw = next(poly for poly, act in board.hits if act == ("turn_sel", 1))
    QTest.mouseClick(board, QtCore.Qt.LeftButton, pos=_centre(cw).toPoint())
    assert g.cube.history[-1] == ("R", 1)
    classic = next(poly for poly, act in board.hits if act == ("style", "classic"))
    QTest.mouseClick(board, QtCore.Qt.LeftButton, pos=_centre(classic).toPoint())
    assert board.style == "classic"
    QTest.mouseClick(board, QtCore.Qt.LeftButton, pos=QtCore.QPoint(30, 500))   # empty space: nothing
    assert g.cube.history[-1] == ("R", 1) and len(g.cube.history) == 1


# ---- in the app ---------------------------------------------------------------------------------------------
def test_the_extension_opens_the_window_and_remembers_options(qapp, spec, settings, monkeypatch, tmp_path):
    from musemonitor.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path / "data"))
    ext_dir = tmp_path / "exts"
    shutil.copytree(REPO / "extensions" / "muse_cube", ext_dir / "muse_cube", ignore=shutil.ignore_patterns("__pycache__"))
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(ext_dir)]); w.show()
    try:
        ext = next(r for r in w.extensions.records if r.id == "muse_cube").instance
        assert ext.options() == (2, 3, "glass", "vi")
        win = ext.open()
        assert win.tutorial is not None and win.tutorial.step == "select"     # the first time: the tutorial
        ext.tab.depth_box.setCurrentIndex(ext.tab.depth_box.findData(5))
        assert win.real == (2, 5) and win.game.practice                       # the real game waits for it
        win.command("tutorial_skip")
        assert win.tutorial is None and win.game.depth == 5 and ext.app.setting("cube_tutorial_done") in (True, "true")
        assert win.game.n == 2 and win.style == "glass"
        ext.tab.size_box.setCurrentIndex(ext.tab.size_box.findData(3))
        assert win.game.n == 3 and ext.options()[0] == 3
        win.command("style", "classic"); assert ext.options()[2] == "classic"
        assert ext.tab.style_box.currentData() == "classic"
        win.close(); assert ext.window is None
    finally:
        w.close()


def test_frames_during_turn_and_view_animations_render(board, mc):
    import time
    for cmd in (("turn", "R", 1), ("turn", "U", 2), ("undo",), ("view", "y", 1), ("view", "x", -1)):
        board.command(*cmd)
        assert board.anim is not None
        board.anim["t0"] = time.monotonic() - board.anim["dur"] / 2      # half way
        assert not board.grab().toImage().isNull()
        if cmd != ("view", "x", -1): board.settle()
    board._tick(); board.anim["t0"] -= 10; board._tick()
    assert board.anim is None


# ---- R2: adapter, tilt, controller ----------------------------------------------------------------------------
def test_adapter_loads_head_and_tilt_from_the_sibling_extensions(mc):
    A = mc["muse_cube_t.adapter"]
    a = A.Adapter()
    assert a.ok("head") and a.ok("tilt"), a.caps
    g = a.head_gestures(52.0)
    assert hasattr(g, "tracker") and isinstance(a.roll(g.tracker), float)


def test_adapter_switches_off_only_what_is_missing(mc, tmp_path):
    A = mc["muse_cube_t.adapter"]
    shutil.copytree(REPO / "extensions" / "head_motion_plus", tmp_path / "head_motion_plus",
                    ignore=shutil.ignore_patterns("__pycache__"))
    a = A.Adapter(root=tmp_path)                                      # no food_order next to it
    assert not a.ok("head") and "food_order" in a.reason("head") and not a.ok("tilt")
    (tmp_path / "food_order").mkdir()
    (tmp_path / "food_order" / "gestures.py").write_text("class HeadGestures:\n    def feed(self): pass\n")
    a = A.Adapter(root=tmp_path)                                      # changed interface
    assert not a.ok("head") and "calibrate" in a.reason("head")


def _tilt_run(tl, samples, t0=0.0, dt=0.02, locked=False):
    out = []
    for i, (yaw, roll) in enumerate(samples):
        d = tl.update(t0 + i * dt, yaw, 0.0, roll, locked)
        if d: out.append(d)
    return out


def test_tilt_needs_a_steady_head_a_held_roll_and_a_return(mc):
    T = mc["muse_cube_t.tilt"]
    tl = T.Tilt()
    still = [(0.0, 0.0)] * 25                                         # 0.5 s steady
    ramp = [(0.0, r) for r in range(0, 21, 4)]
    hold = [(0.0, 20.0)] * 30                                         # 0.6 s at 20°
    back = [(0.0, r) for r in range(20, -1, -4)] + [(0.0, 0.0)] * 60
    assert _tilt_run(tl, still + ramp + hold + back) == [1]           # one tilt = one turn
    tl = T.Tilt()
    assert _tilt_run(tl, still + [(0.0, -r) for r in range(0, 21, 4)] + [(0.0, -20.0)] * 30) == [-1]
    tl = T.Tilt()
    assert _tilt_run(tl, still + ramp + [(0.0, 20.0)] * 10 + back) == []          # 0.2 s: too short
    tl = T.Tilt()
    shake = [(12.0 * (1 if (i // 8) % 2 else -1), 18.0) for i in range(40)]      # roll with a yaw swing
    assert _tilt_run(tl, still + shake + back) == []
    tl = T.Tilt()
    assert _tilt_run(tl, still + ramp + hold, locked=True) == []                  # just after a nod / shake
    tl = T.Tilt()
    assert _tilt_run(tl, ramp + hold) == []                                       # not from a steady head


def test_tilt_calibration_sets_direction_and_threshold(mc):
    T = mc["muse_cube_t.tilt"]
    tl = T.Tilt()
    assert tl.calibrate([0.0, 0.0, 0.0, -5, -15, -25, -30, -30]) == (True, "")
    assert tl.sign == -1.0 and tl.threshold == pytest.approx(18.0)
    assert tl.calibrate([0.0] * 3 + [3.0] * 10)[0] is False                       # too small: kept as it was
    still = [(0.0, 0.0)] * 25
    assert _tilt_run(tl, still + [(0.0, -r) for r in range(0, 25, 4)] + [(0.0, -24.0)] * 30) == [1]   # right, mirrored


def test_tilt_test_scores_hits_and_false_tilts(mc):
    T = mc["muse_cube_t.tilt"]
    tt = T.TiltTest(seed=1, start=0.0)
    assert len(tt.prompts) == 32 and tt.prompts.count("right") == 10 and tt.prompts.count("left") == 10
    for i, p in enumerate(tt.prompts):
        now = i * T.PROMPT_S + 1.0
        if p == "right" and i % 7: tt.record(now, 1)
        if p == "left": tt.record(now, -1)
    r = tt.result()
    assert r["left"] == 10 and r["false"] == 0 and r["passed"] == (r["right"] >= 8)
    nod = tt.prompts.index("nod"); tt.record(nod * T.PROMPT_S + 1.0, 1)
    assert tt.result()["false"] == 1 and not tt.result()["passed"]
    assert tt.current(len(tt.prompts) * T.PROMPT_S + 1) is None and tt.done


class _App:
    def __init__(self): self.s = {}
    def setting(self, k, d=None, type=None): return self.s.get(k, d)
    def set_setting(self, k, v): self.s[k] = v


class _Ext:
    def __init__(self):
        self.app, self.now, self.cues, self.finished = _App(), 100.0, None, []
    def mono(self): return self.now
    def tilt_test_finished(self, r): self.finished.append(r)


@pytest.fixture
def ctrl(mc, board):
    A, C = mc["muse_cube_t.adapter"], mc["muse_cube_t.controller"]
    ext = _Ext()
    c = C.CubeController(ext, A.Adapter(), 52.0)
    c.head.calibrated = True
    c.attach(board)
    yield c, ext, board
    c.attach(None)


def test_head_events_drive_the_game_in_screen_terms(ctrl):
    c, ext, w = ctrl
    g = w.game
    def ev(e): c._event(e, ext.now); w.settle()
    def tilt(d): c._tilt(d, ext.now); w.settle()
    ev(("point", 2)); assert w.selected == "R"
    tilt(1); assert g.cube.history[-1] == ("R", 1)
    ev(("point", 0)); tilt(-1); assert g.cube.history[-1] == ("F", 3)
    ev(("shake",)); assert g.cube.history == [("R", 1)] and c.flash[0] == "shake"
    ev(("page", 1)); assert g.view.logical("F") == "R"                            # head right: the right face comes forward
    ev(("point", 0)); tilt(1); assert g.cube.history[-1] == ("R", 1)              # logical, after the view turn
    ev(("look_up",)); assert g.view_turns == 2
    c._event(("nod",), ext.now); assert g.moves == 3                               # nothing to confirm while playing


def test_imu_path_ignores_nod_and_shake_while_a_tilt_is_held(ctrl, monkeypatch):
    import numpy as np
    c, ext, w = ctrl
    rolls = iter([0.0] * 20 + [20.0] * 40)
    monkeypatch.setattr(c.adapter, "roll", lambda tracker: next(rolls))
    feed_events = {"now": []}
    monkeypatch.setattr(c.head, "feed", lambda x, ts, now: feed_events["now"])
    c.head.last = (0.0, 0.0); c.head.lock_until = -1e9; c.head.need_quiet = False
    w.command("select", "U")
    x, ts = np.zeros((6, 1)), np.array([0.0])
    for i in range(20): ext.now += 0.02; c.on_imu(x, ts)
    for i in range(10): ext.now += 0.02; c.on_imu(x, ts)                 # tilt armed, held
    assert c.tilt.arm is not None
    feed_events["now"] = [("shake",)]; ext.now += 0.02; c.on_imu(x, ts)
    assert w.game.undos == 0                                             # ignored while holding
    feed_events["now"] = []
    for i in range(20): ext.now += 0.02; c.on_imu(x, ts)
    assert w.game.cube.history[-1] == ("U", 1) and c.head_live()


def test_calibration_runs_its_steps_and_shows_an_overlay(ctrl, monkeypatch):
    c, ext, w = ctrl
    C = sys.modules["muse_cube_t.controller"]
    monkeypatch.setattr(c.head, "calibrate", lambda kind, rows: (True, ""))
    monkeypatch.setattr(c.head, "recenter", lambda: True)
    monkeypatch.setattr(c.tilt, "calibrate", lambda rolls: (True, ""))
    assert c.start_calibration()
    seen = set()
    for _ in range(400):
        ext.now += 0.1; c._tick()
        if c.calib: seen.add((c.calib["i"], c.calib["phase"])); assert w.extra["overlay"]["kind"] == "calib"
        else: break
    assert c.calib is None and {i for i, _ in seen} == set(range(len(C.STEPS)))
    assert w.extra["overlay"] is None and w.extra["flash"] == "calib.done"
    w.grab()


def test_tilt_test_runs_to_a_saved_result(ctrl, monkeypatch):
    import json
    c, ext, w = ctrl
    assert c.start_tilt_test(seed=3)
    ext.now += 2.0; c._tick(); assert w.extra["overlay"]["kind"] == "test"
    w.grab()
    for p_i, p in enumerate(c.test.prompts):
        ext.now = c.test.start + p_i * 4.0 + 1.0; c._tick()
        if p in ("right", "left"): c.test.record(ext.now, 1 if p == "right" else -1)
    ext.now = c.test.start + 32 * 4.0 + 0.5; c._tick()
    assert c.test is None and ext.finished and ext.finished[0]["passed"]
    assert json.loads(ext.app.s["cube_tilt_test"])["right"] == 10


def test_head_mode_window_draws_head_chips_tilt_bar_and_flash(board):
    board.set_extra(dict(head=True, tilt=0.6, tilt_on=True, flash="tilt_r", overlay=None))
    board.command("select", "R")
    assert not board.grab().toImage().isNull()


def _imu_chunks(gyro, seconds, fs=52.0, acc=(0.0, 0.0, 1.0), n=4):
    """Constant gyro (°/s, sensor axes) for ``seconds``, in chunks of n samples (6 × n each)."""
    total = int(seconds * fs)
    for i in range(0, total, n):
        k = min(n, total - i)
        yield np.tile(np.r_[acc, gyro][:, None], (1, k)).astype(float)


def test_the_real_chain_from_imu_to_a_turned_face(ctrl):
    """Synthetic IMU through the real calibration (head_motion_plus axes, tilt direction) and PoseTracker roll.
    Checks the algorithm end to end — not that a person can use it (that is the tilt test)."""
    c, ext, w = ctrl
    head = c.head
    head.calibrated = False
    fs = head.fs

    def feed(gyro, secs, collect=None):
        for x in _imu_chunks(gyro, secs, fs):
            ext.now += x.shape[1] / fs
            if collect is not None: collect.append(x)
            c.on_imu(x, np.full(x.shape[1], ext.now))

    c.calib = dict(i=0, phase="prep", imu=[], rolls=[])                  # as in the real calibration: no game events
    rows = []; feed((0, 0, 0), 1.2, rows)
    assert head.calibrate("neutral", np.concatenate(rows, axis=1).T[-int(fs):])[0]
    rows = []; feed((0, 0, 40), 1.0, rows); feed((0, 0, -40), 1.0)        # turn left 40°, back
    assert head.calibrate("left", np.concatenate(rows, axis=1).T)[0]
    rows = []; feed((-40, 0, 0), 1.0, rows); feed((40, 0, 0), 1.0)        # look up, back
    assert head.calibrate("up", np.concatenate(rows, axis=1).T)[0]
    head.recenter(); c.tilt.reset()
    c.calib = dict(i=3, phase="go", imu=[], rolls=[])                    # the tilt step collects roll
    assert w.game.view_turns == 0 and not w.game.cube.history
    feed((0, 0, 0), 0.2); feed((0, -60, 0), 0.4); feed((0, 0, 0), 0.6)
    ok, msg = c.tilt.calibrate(c.calib["rolls"]); c.calib = None
    assert ok, msg
    feed((0, 60, 0), 0.4); feed((0, 0, 0), 1.0)                           # back level, steady
    w.command("select", "R")
    feed((0, -60, 0), 0.4); feed((0, 0, 0), 0.8)                          # tilt right (as calibrated), hold
    w.settle()
    assert w.game.cube.history == [("R", 1)], (c.tilt.roll, c.tilt.threshold)
    feed((0, 60, 0), 0.4); feed((0, 0, 0), 1.2)
    feed((0, 60, 0), 0.4); feed((0, 0, 0), 0.8)                           # tilt left
    w.settle()
    assert w.game.cube.history[-1] == ("R", 3)


def test_pointing_is_frozen_from_the_start_of_a_tilt_until_level(ctrl, monkeypatch):
    c, ext, w = ctrl
    rolls = iter([0.0] * 20 + [20.0] * 40 + [0.0] * 30)
    monkeypatch.setattr(c.adapter, "roll", lambda tracker: next(rolls))
    events = {"now": []}
    monkeypatch.setattr(c.head, "feed", lambda x, ts, now: events["now"])
    c.head.last = (0.0, 0.0); c.head.lock_until = -1e9; c.head.need_quiet = False
    w.command("select", "R")
    x, ts = np.zeros((6, 1)), np.array([0.0])
    for i in range(25): ext.now += 0.02; c.on_imu(x, ts)               # roll starts at sample 20
    events["now"] = [("point", 0)]                                     # the head drifts to the left zone mid-tilt
    for i in range(35): ext.now += 0.02; c.on_imu(x, ts)               # still tilted (samples 25–59)
    assert w.game.cube.history == [("R", 1)] and w.selected == "R"
    for i in range(25): ext.now += 0.02; c.on_imu(x, ts)               # level again: pointing works
    assert w.selected == "F"


# ---- review fixes: animation queue, overlay lock, the tilt test decides ------------------------------------------
def test_a_move_during_an_animation_waits_for_it(board, mc):
    import time
    B = mc["muse_cube_t.board"]
    g = board.game
    board.command("turn", "R", 1); board.command("turn", "U", 1)      # two quick commands
    assert g.cube.history == [("R", 1)] and len(board.queue) == 1      # the second waits: R is seen in full
    board._tick(); assert g.cube.history == [("R", 1)]                 # still animating
    board.anim["t0"] -= 1.0; board._tick()
    assert g.cube.history == [("R", 1), ("U", 1)] and board.anim is not None and not board.queue
    for _ in range(B.QUEUE_MAX + 2): board.command("turn", "F", 1)
    assert len(board.queue) == B.QUEUE_MAX                             # bounded: extra moves are dropped
    board.settle(); assert len(g.cube.history) == 2 + B.QUEUE_MAX
    board.command("turn", "R", 1); board.command("new")                # a new game drops what was waiting
    assert board.game.moves == 0 and not board.queue and board.anim is None


def test_an_open_overlay_locks_the_game(board, mc):
    from PySide6 import QtCore, QtWidgets
    from PySide6.QtTest import QTest
    g = board.game
    seen = []
    board.on_key = lambda k: (seen.append(k), k == QtCore.Qt.Key_Escape)[1]
    board.set_extra(dict(head=True, overlay=dict(kind="test", prompt="right", i=0, n=32, progress=0.2, got=[])))
    QtWidgets.QApplication.processEvents(); board.grab()
    for k in (QtCore.Qt.Key_R, QtCore.Qt.Key_Right, QtCore.Qt.Key_Backspace, QtCore.Qt.Key_H, QtCore.Qt.Key_Space):
        QTest.keyClick(board, k)
    sticker = board.stickers[0][0]
    QTest.mouseClick(board, QtCore.Qt.LeftButton, pos=sticker.boundingRect().center().toPoint())
    assert not board.command("turn", "F", 1) and not board.command("select", "R")
    assert g.moves == 0 and g.view_turns == 0 and g.hint is None and board.selected is None and board.anim is None
    QTest.keyClick(board, QtCore.Qt.Key_Escape); assert seen[-1] == QtCore.Qt.Key_Escape   # the controller's keys pass
    board.set_extra(dict(head=False, overlay=None))
    QTest.keyClick(board, QtCore.Qt.Key_R); assert g.moves == 1


def test_the_tilt_test_needs_one_right_side_tilt_per_prompt(mc):
    T = mc["muse_cube_t.tilt"]
    def run(extra):
        tt = T.TiltTest(seed=2, start=0.0)
        for i, p in enumerate(tt.prompts):
            now = i * T.PROMPT_S + 1.0
            if p in ("right", "left"): tt.record(now, 1 if p == "right" else -1)
        extra(tt)
        return tt.result()
    assert run(lambda tt: None)["passed"]
    def wrong(tt):
        i = tt.prompts.index("right"); tt.record(i * T.PROMPT_S + 2.0, -1)
    r = run(wrong)
    assert r["wrong_side"] == 1 and r["right"] == 9 and not r["passed"]   # a wrong side fails, and the prompt is a miss
    def repeat(tt):
        for p in ("right", "left"):
            i = tt.prompts.index(p); tt.record(i * T.PROMPT_S + 2.0, 1 if p == "right" else -1)
    r = run(repeat)
    assert r["repeats"] == 2 and r["right"] == 9 and r["left"] == 9 and r["passed"]   # repeats are misses


def test_a_failed_tilt_test_switches_tilt_off_but_the_test_still_hears_it(ctrl, monkeypatch):
    import json
    c, ext, w = ctrl
    assert c.tilt_on() and not c.tilt_failed()                        # no test yet: on, provisionally
    c.test_result = dict(right=5, left=9, false=1, wrong_side=0, repeats=0, passed=False, n_each=10)
    assert c.tilt_failed() and not c.tilt_on()
    rolls = iter([0.0] * 20 + [20.0] * 40)
    monkeypatch.setattr(c.adapter, "roll", lambda tracker: next(rolls))
    monkeypatch.setattr(c.head, "feed", lambda x, ts, now: [])
    c.head.last = (0.0, 0.0); c.head.lock_until = -1e9; c.head.need_quiet = False
    w.command("select", "R")
    x, ts = np.zeros((6, 1)), np.array([0.0])
    for _ in range(50): ext.now += 0.02; c.on_imu(x, ts)
    w.settle(); assert not w.game.cube.history                         # failed: tilting turns nothing
    assert c.extra()["tilt_failed"] and not c.extra()["tilt_on"]
    assert c.start_tilt_test(seed=1)                                   # but a retry can still detect tilts
    rolls2 = iter([0.0] * 30 + [20.0] * 40)
    monkeypatch.setattr(c.adapter, "roll", lambda tracker: next(rolls2))
    ext.now = c.test.start + c.test.prompts.index("right") * 4.0 + 0.1; c.tilt.reset()
    for _ in range(60): ext.now += 0.02; c.on_imu(x, ts)
    assert 1 in c.test.got[c.test.prompts.index("right")]
    c.test = None
    c.test_result = dict(right=9, left=10, false=0, wrong_side=0, repeats=0, passed=True, n_each=10)
    assert c.tilt_on()


def test_the_tab_shows_the_tilt_test_switching_tilt_off(qapp, spec, settings, monkeypatch, tmp_path):
    import json
    from musemonitor.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path / "data"))
    ext_dir = tmp_path / "exts"
    for name in ("muse_cube", "head_motion_plus", "food_order"):
        shutil.copytree(REPO / "extensions" / name, ext_dir / name, ignore=shutil.ignore_patterns("__pycache__"))
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(ext_dir)]); w.show()
    try:
        ext = next(r for r in w.extensions.records if r.id == "muse_cube").instance
        assert ext.adapter.ok("head") and "provisionally" in ext.tab.status.text()
        ext.controller.test_result = dict(right=6, left=10, false=0, wrong_side=1, repeats=0, passed=False, n_each=10)
        ext.refresh()
        assert "switched off" in ext.tab.status.text() and not ext.tab.tilt_check.isEnabled()
    finally:
        w.close()


# ---- layers ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("n", [2, 3])
def test_every_layer_can_be_turned_and_is_stored_canonically(mc, n):
    C = cube_mod(mc)
    for f in C.FACES:
        c = C.Cube(n)
        for d in range(n): c.turn(f, 1, depth=d)
        assert c.solved()                                             # all layers of an axis = a whole-cube turn
    c = C.Cube(n)
    assert c.turn("R", 1, depth=n - 1) == ("L", 3)                    # the opposite layer = that face's own move
    if n == 3:
        assert c.turn("R", 1, depth=1) == ("L", 3, 1)                 # M′
        assert c.turn("U", 2, depth=1) == ("D", 2, 1)                 # E2
        assert c.turn("F", 1, depth=1) == ("F", 1, 1)                 # S
        assert C.move_name("L", 3, 1) == "M′" and C.move_name("D", 2, 1) == "E2"
        assert C.simplify([("L", 1, 1), ("L", 3, 1), ("L", 1), ("F", 2, 1), ("F", 2, 1)]) == [("L", 1)]
    while c.history: c.undo()
    assert c.solved()
    with pytest.raises(ValueError): c.turn("R", 1, depth=n)


def test_layer_moves_after_view_turns_then_the_way_back_solves(mc):
    G = game_mod(mc)
    g = G.Game(3, 5, seed=4)
    g.turn_view("y", 1); assert g.turn("F", 1, 1) == ("L", 1, 1)       # screen front is logical L: middle = M
    g.turn_view("x", -1); g.turn("R", 3, 2)                            # the layer opposite the screen right
    g.turn("U", 1, 1)
    hint = g.show_hint(); assert len(hint) == 4
    while not g.solved:
        f, t, _, d = g.show_hint(); g.turn(f, t, d)
    assert g.solved


def test_click_again_tab_and_the_button_choose_the_layer_and_it_is_lit(mc, qapp):
    from PySide6 import QtCore, QtWidgets
    from PySide6.QtTest import QTest
    B = mc["muse_cube_t.board"]
    w = B.CubeWindow(n=3, depth=3, seed=5); w.resize(1226, 1064); w.show(); QtWidgets.QApplication.processEvents()
    try:
        g = w.game
        right = next(poly for poly, f in w.stickers if f == "R")
        QTest.mouseClick(w, QtCore.Qt.LeftButton, pos=right.boundingRect().center().toPoint())
        assert (w.selected, w.depth) == ("R", 0)
        w.grab(); right = next(poly for poly, f in w.stickers if f == "R")
        QTest.mouseClick(w, QtCore.Qt.LeftButton, pos=right.boundingRect().center().toPoint())
        assert w.depth == 1                                            # same face again: the next layer
        QTest.keyClick(w, QtCore.Qt.Key_Tab); assert w.depth == 2
        QTest.keyClick(w, QtCore.Qt.Key_Tab); assert w.depth == 0      # wraps
        w.grab()
        nxt = next(poly for poly, act in w.hits if act == ("layer",))
        QTest.mouseClick(w, QtCore.Qt.LeftButton, pos=nxt.boundingRect().center().toPoint()); assert w.depth == 1
        w.grab()
        cw = next(poly for poly, act in w.hits if act == ("turn_sel", 1))
        QTest.mouseClick(w, QtCore.Qt.LeftButton, pos=cw.boundingRect().center().toPoint())
        w.settle()
        assert g.cube.history[-1] == ("L", 3, 1)                       # the right face's middle layer, clockwise = M′
        assert len(g.cube.layer("R", 1)) == 8                          # the lit layer: 8 cubies (no core)
        QTest.keyClick(w, QtCore.Qt.Key_M); w.settle(); assert g.cube.history[-1] == ("L", 1, 1)
        QTest.keyClick(w, QtCore.Qt.Key_E, QtCore.Qt.ShiftModifier); w.settle(); assert g.cube.history[-1] == ("D", 3, 1)
        QTest.keyClick(w, QtCore.Qt.Key_G)          # a plain key: Qt keeps the last modifiers app-wide (Shift would leak)
        for style in ("glass", "classic"):
            w.command("style", style); assert not w.grab().toImage().isNull()
    finally:
        w.close()


def test_nod_chooses_the_next_layer_and_tilt_turns_it(ctrl):
    c, ext, w = ctrl
    g = w.game
    c._event(("point", 2), ext.now)
    c._event(("nod",), ext.now); assert w.depth == 1                   # 2×2: depth 1 = the opposite (left) layer
    c._tilt(1, ext.now); w.settle()
    assert g.cube.history[-1] == ("L", 3) and g.moves == 1
    c._event(("nod",), ext.now); assert w.depth == 0
    c._event(("point", 1), ext.now); assert (w.selected, w.depth) == ("U", 0)


# ---- review round 3: mouse fallback in head mode, calibration on the first IMU, scoring by tilt start ------------
def test_head_mode_keeps_the_mouse_buttons_when_tilt_is_off_or_failed(board):
    from PySide6 import QtCore, QtWidgets
    from PySide6.QtTest import QTest
    board.command("select", "R")
    board.set_extra(dict(head=True, tilt=0.0, tilt_on=True, tilt_failed=False, overlay=None)); board.grab()
    assert not any(act[0] == "turn_sel" for _, act in board.hits)       # tilt works: the tilt bar, no buttons
    for failed in (True, False):                                        # failed test, or ticked off
        board.set_extra(dict(head=True, tilt=0.0, tilt_on=False, tilt_failed=failed, overlay=None))
        QtWidgets.QApplication.processEvents(); board.grab()
        assert {act for _, act in board.hits if act[0] in ("turn_sel", "layer")} == {("turn_sel", -1), ("turn_sel", 1), ("layer",)}
    cw = next(poly for poly, act in board.hits if act == ("turn_sel", 1))
    QTest.mouseClick(board, QtCore.Qt.LeftButton, pos=cw.boundingRect().center().toPoint()); board.settle()
    assert board.game.cube.history == [("R", 1)]


def test_calibration_starts_on_the_first_imu_when_the_window_opened_first(mc, board):
    A, C = mc["muse_cube_t.adapter"], mc["muse_cube_t.controller"]
    ext = _Ext()
    c = C.CubeController(ext, A.Adapter(), 52.0)
    try:
        c.attach(board)                                                  # no IMU yet
        assert c.calib is None and c.auto_calib
        x = np.tile(np.array([0, 0, 1.0, 0, 0, 0])[:, None], (1, 4))
        ext.now += 0.1; c.on_imu(x, np.full(4, ext.now))                 # the headset connects
        assert c.calib is not None and c.calib["i"] == 0 and not c.auto_calib
        c._key(QtCore_key("Key_Escape")); assert c.calib is None         # skipped by the user …
        for _ in range(10): ext.now += 0.1; c.on_imu(x, np.full(4, ext.now))
        assert c.calib is None                                           # … not restarted by later IMU
    finally:
        c.attach(None)


def QtCore_key(name):
    from PySide6 import QtCore
    return getattr(QtCore.Qt, name)


def test_a_tilt_is_scored_at_the_prompt_where_it_began(mc):
    T = mc["muse_cube_t.tilt"]
    tt = T.TiltTest(seed=4, start=10.0)
    i = next(k for k, p in enumerate(tt.prompts[:-1]) if p == "right")
    began = 10.0 + i * T.PROMPT_S + 3.8                                  # starts 0.2 s before the boundary …
    tt.record(began, 1)                                                  # … recognised 0.4 s later, in the next prompt
    assert tt.got[i] == [1] and all(not g for k, g in enumerate(tt.got) if k != i)
    tt.record(9.5, 1); tt.record(None, 1)                                # before the test / unknown start: ignored
    assert sum(len(g) for g in tt.got) == 1


def test_the_controller_scores_by_the_start_of_the_tilt(ctrl, monkeypatch):
    c, ext, w = ctrl
    assert c.start_tilt_test(seed=6)
    t = c.test
    i = next(k for k, p in enumerate(t.prompts[:-1]) if p == "left")      # one with a next prompt
    monkeypatch.setattr(c.head, "feed", lambda x, ts, now: [])
    c.head.last = (0.0, 0.0); c.head.lock_until = -1e9; c.head.need_quiet = False
    c.tilt.reset()
    boundary = t.start + (i + 1) * 4.0
    ext.now = boundary - 1.0
    x, ts = np.zeros((6, 1)), np.array([0.0])
    roll = {"v": 0.0}
    monkeypatch.setattr(c.adapter, "roll", lambda tracker: roll["v"])
    while ext.now < boundary - 0.15: ext.now += 0.02; c.on_imu(x, ts)    # steady
    roll["v"] = -20.0
    while ext.now < boundary + 0.5: ext.now += 0.02; c.on_imu(x, ts)     # recognised after the boundary
    assert t.got[i] == [-1] and not t.got[i + 1]


# ---- the 2D panel -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("n", [2, 3])
def test_ring_layout_puts_every_sticker_on_its_two_rings(mc, n):
    C, F = cube_mod(mc), mc["muse_cube_t.flat"]
    c = C.Cube(n); c.scramble(6, seed=1)
    L = F.Rings(n, 300.0, 300.0, 600.0)
    pts, cells = set(), set()
    for k in c.cubies:
        for nrm in k["stickers"]:
            nv = np.array(nrm); pt = L.point(k["pos"], nv)
            a = int(np.argmax(np.abs(nv)))
            for b in (x for x in (0, 1, 2) if x != a):            # on the rings of the two other axes
                assert np.linalg.norm(pt - L.centres[b]) == pytest.approx(L.radius(b, int(k["pos"][b])), abs=1e-6)
            pts.add(tuple(np.round(pt, 3))); cells.add(F.net_cell(n, k["pos"], nrm))
    assert len(pts) == 6 * n * n and len(cells) == 6 * n * n       # every sticker its own place, in both views
    assert len(L.rings()) == 3 * n
    assert {name for *_, name, _ in L.rings()} == (set("UEDRMLFSB") if n == 3 else set("UDRLFB"))


def test_turning_a_layer_moves_its_side_stickers_along_its_ring(mc):
    C, F = cube_mod(mc), mc["muse_cube_t.flat"]
    c = C.Cube(3); L = F.Rings(3, 0.0, 0.0, 600.0)
    c.turn("U", 1)
    ring = L.ring_of("U", 0)
    for k in c.layer("U"):
        for nrm in k["stickers"]:
            if nrm[1] == 0:                                        # side stickers of the U layer
                assert np.linalg.norm(L.point(k["pos"], np.array(nrm)) - L.centres[ring[0]]) == \
                    pytest.approx(L.radius(*ring), abs=1e-6)


def test_the_panel_follows_the_game_and_its_rings_turn_layers(mc, qapp):
    import time
    from PySide6 import QtCore, QtWidgets
    from PySide6.QtTest import QTest
    B = mc["muse_cube_t.board"]
    changes = []
    w = B.CubeWindow(n=3, depth=3, seed=2, on_change=lambda k, v: changes.append((k, v)))
    w.resize(1560, 920); w.show(); QtWidgets.QApplication.processEvents()
    try:
        g = w.game
        assert w.panel_shown(); w.grab()
        def hit(act):
            return next(poly for poly, a in w.hits if a == act).boundingRect().center().toPoint()
        QTest.mouseClick(w, QtCore.Qt.LeftButton, pos=hit(("ring_turn", "R", 1, 0))); w.settle()
        assert g.cube.history[-1] == ("R", 1)
        w.grab(); QTest.mouseClick(w, QtCore.Qt.LeftButton, pos=hit(("ring_turn", "L", -1, 1))); w.settle()
        assert g.cube.history[-1] == ("L", 3, 1)                   # the M′ button
        w.grab()
        ring = next(poly for poly, a in w.hits if a == ("ring", "U", 0))
        on_ring = next(QtCore.QPointF(x, y) for x, y in ((pt.x(), pt.y()) for pt in ring)
                       if w.hit_at(QtCore.QPointF(x, y)) == ("ring", "U", 0))
        QTest.mouseClick(w, QtCore.Qt.LeftButton, QtCore.Qt.ShiftModifier, on_ring.toPoint()); w.settle()
        QTest.keyClick(w, QtCore.Qt.Key_G); QTest.keyClick(w, QtCore.Qt.Key_G)      # clear the remembered Shift
        assert g.cube.history[-1] == ("U", 3)                      # the ring itself, Shift = counter-clockwise
        w.command("select", "F", 1); w.command("turn", "R", 1)
        w.anim["t0"] = time.monotonic() - 0.1; assert not w.grab().toImage().isNull()   # mid-turn, rings
        w.settle()
        QTest.mouseClick(w, QtCore.Qt.LeftButton, pos=hit(("panel_mode", "cross")))
        assert w.panel_mode == "cross" and changes[-1] == ("panel_mode", "cross")
        w.grab()
        up = next(poly for poly, a in w.hits if a == ("sticker", "U") and poly.boundingRect().x() > w.cube_w)
        QTest.mouseClick(w, QtCore.Qt.LeftButton, pos=up.boundingRect().center().toPoint())
        assert w.selected == "U"                                   # a click in the net selects its face
        QTest.keyClick(w, QtCore.Qt.Key_P); assert not w.panel_shown() and changes[-1] == ("panel", False)
        w.grab(); assert w.cube_w == w.width()
        QTest.keyClick(w, QtCore.Qt.Key_P); w.resize(1000, 800); assert not w.panel_shown()   # too narrow: hidden
    finally:
        w.close()


# ---- the tutorial ---------------------------------------------------------------------------------------------------
def _tut_window(mc, n=2):
    from PySide6 import QtWidgets
    B = mc["muse_cube_t.board"]
    changes = []
    w = B.CubeWindow(n=n, depth=3, seed=1, tutorial=True, on_change=lambda k, v: changes.append((k, v)))
    w.resize(1560, 920); w.show(); QtWidgets.QApplication.processEvents()
    w.changes = changes
    return w


def _solve_with_keys(w, key):
    from PySide6 import QtCore
    keys = {f: getattr(QtCore.Qt, "Key_" + f) for f in "UDLRFB"}
    while not w.game.solved and w.tutorial and w.tutorial.step in ("solve1", "solve2"):
        step = w.tutorial.step
        f, t, _, d = w.game.show_hint()
        for _ in range(2 if t == 2 else 1):
            key(keys[f], QtCore.Qt.ShiftModifier if t == 3 else QtCore.Qt.NoModifier)
        if w.tutorial.step != step: break


def test_the_tutorial_with_keys_and_mouse_leads_into_the_real_game(mc, qapp):
    from PySide6 import QtCore
    from PySide6.QtTest import QTest
    w = _tut_window(mc)
    try:
        def key(k, mod=QtCore.Qt.NoModifier):
            QTest.keyClick(w, k, mod); w.settle()
        def click(act):
            w.grab(); poly = next(pl for pl, a in w.hits if a == act)
            QTest.mouseClick(w, QtCore.Qt.LeftButton, pos=poly.boundingRect().center().toPoint()); w.settle()
        assert w.tutorial.step == "select" and w.game.practice and w.game.cube.solved()
        w.grab(); left = next(pl for pl, f in w.stickers if f == "F")
        QTest.mouseClick(w, QtCore.Qt.LeftButton, pos=left.boundingRect().center().toPoint())
        assert w.tutorial.step == "select"                                   # the front face is not the one asked
        w.grab(); right = next(pl for pl, f in w.stickers if f == "R")
        QTest.mouseClick(w, QtCore.Qt.LeftButton, pos=right.boundingRect().center().toPoint())
        assert w.tutorial.step == "layer" and w.tutorial.cheering()
        key(QtCore.Qt.Key_Tab); assert w.tutorial.step == "turn"
        click(("turn_sel", 1)); assert w.tutorial.step == "undo"
        assert not w.game.solved                                             # practice: a turned cube, never "finished"
        key(QtCore.Qt.Key_Backspace); assert w.tutorial.step == "view"
        key(QtCore.Qt.Key_Space); assert w.game.practice                     # no new game during the tutorial
        key(QtCore.Qt.Key_Right); assert w.tutorial.step == "solve1"
        assert len(w.game.scramble) == 1 and not w.game.solved
        _solve_with_keys(w, key); assert w.tutorial.step == "solve2" and len(w.game.scramble) == 2
        _solve_with_keys(w, key); assert w.tutorial.step == "done"
        w.grab(); assert any(a == ("tutorial_done",) for _, a in w.hits)
        key(QtCore.Qt.Key_Return)
        assert w.tutorial is None and w.game.depth == 3 and not w.game.practice and w.game.moves == 0
        assert ("tutorial_done", True) in w.changes
        key(QtCore.Qt.Key_F1); assert w.tutorial is not None and w.tutorial.step == "select"   # replay
        key(QtCore.Qt.Key_Escape); assert w.tutorial is None                                   # skip
    finally:
        w.close()


def test_the_tutorial_with_head_gestures(mc, qapp):
    A, C = mc["muse_cube_t.adapter"], mc["muse_cube_t.controller"]
    w = _tut_window(mc)
    ext = _Ext()
    c = C.CubeController(ext, A.Adapter(), 52.0)
    c.head.calibrated = True
    c.attach(w)
    try:
        w.set_extra(dict(head=True, tilt=0.0, tilt_on=True, overlay=None)); w.grab()   # head mode texts
        def ev(e): c._event(e, ext.now); w.settle()
        ev(("point", 2)); assert w.tutorial.step == "layer"
        ev(("nod",)); assert w.tutorial.step == "turn"
        c._tilt(1, ext.now); w.settle(); assert w.tutorial.step == "undo"
        ev(("shake",)); assert w.tutorial.step == "view"
        ev(("page", 1)); assert w.tutorial.step == "solve1"
        for _ in range(2):
            while not w.game.solved and w.tutorial.step.startswith("solve"):
                step = w.tutorial.step
                f, t, _, d = w.game.show_hint()
                w.command("select", f, d); w.settle()
                for _ in range(2 if t == 2 else 1): c._tilt(1 if t != 3 else -1, ext.now); w.settle()
                if w.tutorial.step != step: break
        assert w.tutorial.step == "done"
        ev(("nod",)); assert w.tutorial is None and w.game.depth == 3
    finally:
        c.attach(None); w.close()


# ---- blink ×2 ↻ / jaw clench ↺ --------------------------------------------------------------------------------------
NAMES = ["TP9", "AF7", "AF8", "TP10"]


def _emg(rng, seconds, bursts=(), fs=256):
    """4 × n µV: noise and slow drift; bursts=[(t0, t1)]: broadband muscle activity (a clench)."""
    n = int(seconds * fs); t = np.arange(n) / fs
    x = rng.normal(0, 5, (4, n)) + 30 * np.sin(2 * np.pi * t)
    for a, b in bursts:
        m = (t >= a) & (t < b); x[:, m] += rng.normal(0, 40, (4, int(m.sum())))
    return x


def _jaw_run(j, x, t0, fs=256, chunk=12):
    out = []
    for i in range(0, x.shape[1], chunk):
        out += j.feed(x[:, i:i + chunk], t0 + (i + chunk) / fs)
    return out


def test_a_jaw_clench_is_one_event_held_long_enough_with_a_still_head(mc):
    J = mc["muse_cube_t.jaw"]
    rng = np.random.default_rng(0)
    j = J.Jaw(256, NAMES)
    assert not j.ready and _jaw_run(j, _emg(rng, 2, [(0.5, 1.5)]), 0.0) == []      # not calibrated: nothing
    assert j.calibrate(_emg(rng, 3), _emg(rng, 2, [(0.2, 1.8)])) == (True, "") and j.rest < j.threshold < j.clench
    assert _jaw_run(j, _emg(rng, 3, [(1.0, 1.6)]), 10.0) == [("clench",)]
    assert _jaw_run(j, _emg(rng, 3, [(1.0, 1.1)]), 20.0) == []                      # 0.1 s: too short
    assert _jaw_run(j, _emg(rng, 4, [(0.5, 3.5)]), 30.0) == [("clench",)]           # held: still one
    assert _jaw_run(j, _emg(rng, 4, [(0.5, 1.0), (2.0, 2.6)]), 40.0) == [("clench",)] * 2
    j.note_motion(np.array([[0.0], [0.0], [1.0], [90.0], [0.0], [0.0]]), 50.0)      # the head moves (neck EMG)
    assert _jaw_run(j, _emg(rng, 1.0, [(0.0, 0.45)]), 50.0) == []
    weak = J.Jaw(256, NAMES)
    assert weak.calibrate(_emg(rng, 3), _emg(rng, 2)) == (False, "too_weak") and not weak.ready


def test_the_adapter_reports_eyes_on_their_own(mc, tmp_path):
    A = mc["muse_cube_t.adapter"]
    a = A.Adapter()
    assert a.ok("eyes") and a.eye_commands(256, NAMES).source == "tp"
    for name in ("head_motion_plus", "food_order"):                     # no eye_interaction
        shutil.copytree(REPO / "extensions" / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__"))
    b = A.Adapter(root=tmp_path)
    assert b.ok("head") and b.ok("tilt") and not b.ok("eyes") and "eye_interaction" in b.reason("eyes")


@pytest.fixture
def eeg_ctrl(mc, board):
    A, C = mc["muse_cube_t.adapter"], mc["muse_cube_t.controller"]
    ext = _Ext()
    c = C.CubeController(ext, A.Adapter(), 52.0, 256.0, NAMES)
    c.head.calibrated = True
    c.attach(board)
    yield c, ext, board
    c.attach(None)


def test_blink_twice_turns_clockwise_and_a_clench_counter_clockwise_only_with_a_layer(eeg_ctrl, monkeypatch):
    c, ext, w = eeg_ctrl
    assert c.eyes is not None and c.jaw is not None
    events = {"eye": [], "jaw": []}
    monkeypatch.setattr(c.eyes, "feed", lambda x, now, detect=True: (np.zeros((2, x.shape[1])), events["eye"] if detect else []))
    monkeypatch.setattr(c.jaw, "feed", lambda x, now, detect=True: events["jaw"] if detect else [])
    x = np.zeros((4, 12))
    def send(eye=(), jaw=()):
        events["eye"], events["jaw"] = list(eye), list(jaw)
        ext.now += 0.05; c.on_eeg(x); w.settle()
    send(eye=[("double_blink",)])
    assert not w.game.cube.history and c.flash[0] == "select_first"     # no layer: nothing turns
    w.command("select", "R", 1)
    send(eye=[("double_blink",)]); assert w.game.cube.history[-1] == ("L", 3) and c.flash[0] == "blink"   # 2×2 depth 1
    send(jaw=[("clench",)]); assert w.game.cube.history[-1] == ("L", 1) and c.flash[0] == "jaw"
    send(eye=[("eyes_closed",)]); assert len(w.game.cube.history) == 2  # other eye events: nothing
    ext.app.s["cube_eyejaw"] = False
    send(eye=[("double_blink",)]); assert len(w.game.cube.history) == 2  # switched off in the tab
    ext.app.s["cube_eyejaw"] = True
    w.set_extra(dict(overlay=dict(kind="calib", step="blink", i=5, n=7, phase="go", progress=0.2, ok=None, message="")))
    send(jaw=[("clench",)]); assert len(w.game.cube.history) == 2       # an overlay is open: locked
    w.set_extra({})
    c.start_calibration(); send(jaw=[("clench",)]); assert len(w.game.cube.history) == 2   # calibrating: no commands
    c.calib = None


def test_calibration_adds_blink_and_jaw_steps_and_calibrates_them(eeg_ctrl, monkeypatch):
    c, ext, w = eeg_ctrl
    C = sys.modules["muse_cube_t.controller"]
    assert [k for k, _ in c.steps()] == [k for k, _ in C.STEPS] + ["blink", "jaw"]
    ext.app.s["cube_eyejaw"] = False
    assert [k for k, _ in c.steps()] == [k for k, _ in C.STEPS]
    ext.app.s["cube_eyejaw"] = True
    seen = {}
    monkeypatch.setattr(c.head, "calibrate", lambda kind, rows: (True, ""))
    monkeypatch.setattr(c.head, "recenter", lambda: True)
    monkeypatch.setattr(c.tilt, "calibrate", lambda rolls: (True, ""))
    monkeypatch.setattr(c.eyes, "calibrate_open", lambda raw, filt: seen.setdefault("open", raw.shape) and (True, ""))
    monkeypatch.setattr(c.eyes, "calibrate_blink", lambda filt: (seen.setdefault("blink", filt.shape), (True, ""))[1])
    monkeypatch.setattr(c.jaw, "calibrate", lambda rest, raw: (seen.setdefault("jaw", (rest.shape, raw.shape)), (True, ""))[1])
    rng = np.random.default_rng(1)
    assert c.start_calibration()
    for _ in range(4000):
        ext.now += 0.05
        c.on_eeg(rng.normal(0, 5, (4, 13)))
        c._tick()
        if c.calib is None: break
    assert c.calib is None and set(seen) == {"open", "blink", "jaw"}
    assert seen["open"][1] >= 2 * 256 and seen["jaw"][1][1] >= 2 * 256          # 3 s of the still step, the clench step


def test_head_mode_lists_the_ways_to_turn(eeg_ctrl):
    c, ext, w = eeg_ctrl
    c.eyes.blink_thr = 50.0; c.jaw.threshold = 5.0                      # as if calibrated
    c.last_imu = ext.now
    w.command("select", "U")
    w.set_extra(c.extra())
    assert set(w.extra["methods"]) == {"tilt", "blink", "jaw"}
    hint = w.turn_hint()
    assert "chớp mắt 2 lần" in hint and "nghiến răng" in hint and "nghiêng" in hint
    c.test_result = dict(right=3, left=9, false=0, wrong_side=0, repeats=0, passed=False, n_each=10)
    w.set_extra(c.extra()); w.grab()
    assert "tilt" not in w.extra["methods"] and any(a == ("turn_sel", 1) for _, a in w.hits)   # buttons, still eyes / jaw
    assert "nghiến răng" in w.turn_hint()


# ---- camera recenter, 3D head only ----------------------------------------------------------------------------------
def test_camera_recenters_and_only_the_3d_head_is_shown(eeg_ctrl, monkeypatch):
    from PySide6 import QtCore, QtWidgets
    c, ext, w = eeg_ctrl
    if not c.adapter.ok("camera"): pytest.skip(c.adapter.reason("camera"))
    assert c.camera is not None and c.gate is not None
    assert c.camera.receivers(QtCore.SIGNAL("preview(PyObject)")) == 0       # the image is never used
    assert c.canvas is not None and c.canvas.parent() is w and w.head_canvas is c.canvas
    QtWidgets.QApplication.processEvents(); w.grab()
    assert c.canvas.isVisible() and c.canvas.geometry().top() < 120 and c.canvas.width() <= 320   # small, top left
    assert w.extra.get("camera") is None                                       # camera off: "3D head · camera off"
    calls = []
    monkeypatch.setattr(c.head, "recenter", lambda: calls.append(ext.now) or True)
    monkeypatch.setattr(c.head.tracker, "is_still", lambda: True)
    facing = dict(face=True, facing=True, reason="facing the screen")
    for _ in range(6): ext.now += 0.25; c._cam_result(facing)                  # 1.5 s facing and still
    assert len(calls) == 1 and c.flash[0] == "recentered_cam" and c.canvas.recentered[1] == "camera"
    for _ in range(8): ext.now += 0.25; c._cam_result(dict(face=True, facing=False, reason="turned left"))
    assert len(calls) == 1                                                     # not facing: nothing
    c.start_calibration()
    for _ in range(30): ext.now += 0.25; c._cam_result(facing)
    assert len(calls) == 1                                                     # never during the calibration
    c.calib = None
    started = []
    monkeypatch.setattr(c.camera, "start", lambda device_id=None: started.append(device_id))
    monkeypatch.setattr(type(c.camera), "running", property(lambda self: bool(started)))
    assert c.camera_start() == (True, "") and started
    c._cam_result(dict(face=True, facing=False, reason="turned left"))
    assert c.extra()["camera"] == "turned left"
    w.set_extra(c.extra()); w.grab()


def test_the_tab_asks_before_the_camera(qapp, spec, settings, monkeypatch, tmp_path):
    from musemonitor.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path / "data"))
    ext_dir = tmp_path / "exts"
    for name in ("muse_cube", "head_motion_plus", "food_order", "eye_interaction"):
        shutil.copytree(REPO / "extensions" / name, ext_dir / name, ignore=shutil.ignore_patterns("__pycache__"))
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(ext_dir)]); w.show()
    try:
        ext = next(r for r in w.extensions.records if r.id == "muse_cube").instance
        c = ext.controller
        if c.camera is None: pytest.skip(ext.adapter.reason("camera"))
        started = []
        monkeypatch.setattr(c.camera, "start", lambda device_id=None: started.append(1))
        monkeypatch.setattr(ext, "ask_camera", lambda parent: False)
        ext.tab.cam_check.setChecked(True)
        assert not ext.tab.cam_check.isChecked() and not started              # refused: stays off
        monkeypatch.setattr(ext, "ask_camera", lambda parent: True)
        ext.tab.cam_check.setChecked(True)
        assert ext.tab.cam_check.isChecked() and started
        assert c.eyes is not None and c.jaw is not None                       # EEG turns wired in the app too
    finally:
        w.close()


# ---- calibration pictograms -----------------------------------------------------------------------------------------
def test_every_calibration_and_test_step_has_a_pictogram_and_a_description(mc, board):
    from PySide6 import QtCore, QtGui
    P, C, T, X = (mc["muse_cube_t." + m] for m in ("pictos", "controller", "tilt", "text"))
    img = QtGui.QImage(200, 200, QtGui.QImage.Format_RGB32)
    for kind in [k for k, _ in C.STEPS + C.EEG_STEPS] + ["tilt", "left_tilt", "point_left", "point_right", "nod"]:
        for now, hold in ((0.3, False), (1.2, False), (0.0, True)):
            img.fill(0); p = QtGui.QPainter(img); P.draw(p, QtCore.QRectF(0, 0, 200, 200), kind, now, hold); p.end()
            assert img.pixelColor(100, 100) != QtGui.QColor(0, 0, 0)
    assert P.pose("left", 0.5)[0] > 30 and P.pose("left", 0.95)[0] == 0.0       # turns out, holds, comes back
    assert P.pose("up", 0.0, hold=True)[1] > 20 and P.pose("tilt", 0.0, hold=True)[2] > 20
    assert any(P.pose("blink", a / 100)[3] == 1.0 for a in range(100))
    assert any(P.pose("jaw", a / 100)[4] > 0.9 for a in range(100))
    for step, _ in C.STEPS + C.EEG_STEPS:
        for lang in ("vi", "en"):
            assert not X.t(f"calib.{step}.how", lang).startswith("calib.")
    for prompt in set(T.TEST_PROMPTS):
        assert not X.t(f"test.{prompt}.how", "en").startswith("test.")
    for code in ("too_small", "too_weak", "no_imu", "no_eeg", "need_axes", "not_still"):
        assert not X.t("why." + code, "vi").startswith("why.")
    for o in (dict(kind="calib", step="jaw", i=6, n=7, phase="go", progress=0.5, ok=None, message=""),
              dict(kind="calib", step="left", i=1, n=7, phase="result", progress=1.0, ok=False, message="too_small"),
              dict(kind="test", prompt="nod", i=3, n=32, progress=0.4, got=[1])):
        board.set_extra(dict(head=True, overlay=o)); assert not board.grab().toImage().isNull()


# ---- random scramble (play again) -----------------------------------------------------------------------------------
def test_the_scramble_button_plays_again_and_needs_two_clicks_mid_game(board, monkeypatch):
    from PySide6 import QtCore
    from PySide6.QtTest import QTest
    g = board.game
    def click():
        board.grab(); poly = next(pl for pl, a in board.hits if a == ("scramble",))
        QTest.mouseClick(board, QtCore.Qt.LeftButton, pos=poly.boundingRect().center().toPoint())
    first = list(board.game.scramble)
    click(); assert board.game is g and g.moves == 0 and g.scramble != first      # nothing played yet: at once
    board.command("turn", "R", 1); board.settle()
    click(); assert g.moves == 1 and board.scramble_armed_until > 0              # mid-game: armed only
    click(); assert g.moves == 0 and len(g.scramble) == g.depth                  # second click: a new scramble
    board.command("turn", "U", 1); board.settle()
    click(); board.scramble_armed_until -= 10                                     # the arm expires after 3 s
    click(); assert g.moves == 1
    while not g.solved:                                                           # solved: one click plays again
        f, t, _, d = g.show_hint(); board.command("turn", f, t, d); board.settle()
    click(); assert not g.solved and g.moves == 0 and not g.hinted
    board.set_extra(dict(overlay=dict(kind="test", prompt="nod", i=0, n=32, progress=0.1, got=[]))); board.grab()
    assert not any(a == ("scramble",) for _, a in board.hits)                     # hidden under an overlay
    board.set_extra({}); board.start_tutorial(); board.grab()
    assert not any(a == ("scramble",) for _, a in board.hits)                     # and during the tutorial


# ---- live EOG / EMG, thresholds and filters by hand -----------------------------------------------------------------
def _tp_blinks(rng, seconds, blinks=(), amp=150.0, fs=256):
    """4 × n µV with blinks (Gaussian bumps) on TP9 / TP10, the default eye source."""
    n = int(seconds * fs); t = np.arange(n) / fs
    x = rng.normal(0, 4, (4, n))
    for b in blinks: x[[0, 3]] += amp * np.exp(-0.5 * ((t - b) / 0.06) ** 2)
    return x


def _feed_eeg(c, ext, x, chunk=12, fs=256):
    for i in range(0, x.shape[1], chunk):
        ext.now += chunk / fs; c.on_eeg(x[:, i:i + chunk])


def test_a_hand_set_blink_threshold_works_without_calibration_and_is_plotted(eeg_ctrl):
    c, ext, w = eeg_ctrl
    rng = np.random.default_rng(3)
    assert c.threshold("eog") is None and c.eog_view() is None
    _feed_eeg(c, ext, _tp_blinks(rng, 2.0))
    assert c.eog_view() is not None and c.eog_view()[2] is None           # plotted, no threshold yet
    assert c.set_threshold("eog", 40.0) and c.eyes.blink_ready             # by hand: blinks now count
    w.command("select", "R")
    _feed_eeg(c, ext, _tp_blinks(rng, 3.0, blinks=(1.0, 1.3)))
    w.settle()
    assert w.game.cube.history == [("R", 1)] and len(c.marks["double_blink"]) == 1
    t, y, thr, singles, doubles = c.eog_view()
    assert thr == 40.0 and len(singles) >= 2 and len(doubles) == 1 and y.max() > 40
    second = sorted(singles)[-1]
    assert abs(doubles[0] - second) < 0.08                                 # ★ on the pair's second blink
    assert not c.reset_threshold("eog")                                    # nothing calibrated to go back to
    c.cal_blink = 55.0; assert c.reset_threshold("eog") and c.threshold("eog") == 55.0
    assert not c.set_threshold("eog", 0)


def test_jaw_threshold_and_bands_by_hand_and_the_bands_are_remembered(mc, eeg_ctrl):
    A, Cm = mc["muse_cube_t.adapter"], mc["muse_cube_t.controller"]
    c, ext, w = eeg_ctrl
    rng = np.random.default_rng(4)
    _feed_eeg(c, ext, _emg(rng, 2.0, [(0.5, 1.2)]))
    t, rms, thr, clenches = c.emg_view()
    assert thr is None and rms.max() > 3 * np.median(rms)                  # the burst stands out in the RMS
    assert c.set_threshold("emg", float(np.percentile(rms, 90)) * 0.6)
    w.command("select", "U")
    _feed_eeg(c, ext, _emg(rng, 2.0, [(0.5, 1.3)])); w.settle()
    assert w.game.cube.history[-1] == ("U", 3) and len(c.marks["clench"]) == 1
    old_sos = c.eyes.est.sos
    assert c.set_band("eog", 0.5, 5.0) and c.eyes.est.sos is not old_sos and c.eyes.est.zi is None
    assert c.set_band("emg", 55.0, 100.0) and c.jaw.band == (55.0, 100.0)
    with pytest.raises(ValueError): c.set_band("emg", 60.0, 200.0)       # above Nyquist
    assert ext.app.s["cube_eog_band"] == "0.5,5" and ext.app.s["cube_emg_band"] == "55,100"
    c2 = Cm.CubeController(ext, A.Adapter(), 52.0, 256.0, NAMES)           # a new session keeps the bands
    assert c2.band("eog") == (0.5, 5.0) and c2.jaw.band == (55.0, 100.0)


def test_the_window_shows_live_eog_and_emg_traces(eeg_ctrl):
    c, ext, w = eeg_ctrl
    rng = np.random.default_rng(5)
    c.set_threshold("eog", 40.0); c.set_threshold("emg", 6.0)
    _feed_eeg(c, ext, _tp_blinks(rng, 3.0, blinks=(1.0,)) + _emg(rng, 3.0, [(2.0, 2.5)]))
    strip = c.signal_strip(ext.now)
    assert set(strip) == {"eog", "emg"} and strip["eog"][1] == 40.0 and strip["emg"][1] == 6.0
    w.set_extra(c.extra()); assert not w.grab().toImage().isNull()
    ext.now += 5.0; assert c.signal_strip(ext.now) is None               # no EEG for a while: hidden


def test_the_tab_plots_eog_emg_and_takes_thresholds_by_hand(qapp, spec, settings, monkeypatch, tmp_path):
    from PySide6 import QtWidgets
    from musemonitor.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path / "data"))
    ext_dir = tmp_path / "exts"
    for name in ("muse_cube", "head_motion_plus", "food_order", "eye_interaction"):
        shutil.copytree(REPO / "extensions" / name, ext_dir / name, ignore=shutil.ignore_patterns("__pycache__"))
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(ext_dir)]); w.resize(1300, 900); w.show()
    try:
        ext = next(r for r in w.extensions.records if r.id == "muse_cube").instance
        box, c = ext.tab.signals, ext.controller
        assert box.thr["eog"].isEnabled() and box.thr["emg"].isEnabled()
        assert box.lo["eog"].value() == pytest.approx(0.8) and box.hi["emg"].value() == pytest.approx(45.0)
        rng = np.random.default_rng(6)
        x = _tp_blinks(rng, 2.0, blinks=(1.0,)) + _emg(rng, 2.0, [(0.3, 0.8)])
        for i in range(0, x.shape[1], 12): ext.on_eeg_samples(x[:, i:i + 12], np.zeros(12))
        monkeypatch.setattr(box, "isVisible", lambda: True)
        box.refresh()
        assert len(box.curves["eog"].getData()[0]) > 100 and len(box.curves["emg"].getData()[0]) > 10
        box.thr["eog"].setValue(70.0); assert c.threshold("eog") == 70.0     # typed
        box.lines["emg"].setValue(9.0); box._line_moved("emg", box.lines["emg"])
        assert c.threshold("emg") == pytest.approx(9.0) and box.thr["emg"].value() == pytest.approx(9.0)   # dragged
        box.lo["emg"].setValue(50.0); box.hi["emg"].setValue(90.0)
        assert c.jaw.band == (50.0, 90.0) and "re-calibrate" in box.state["emg"].text()
        box.hi["eog"].setValue(0.5 + 0.0); box.lo["eog"].setValue(3.0)       # lo ≥ hi: refused
        assert "invalid" in box.state["eog"].text()
    finally:
        w.close()


# ---- UX review fixes (P1 / P2) --------------------------------------------------------------------------------------
def test_the_cube_keeps_clear_of_the_left_column_and_the_panel_yields(eeg_ctrl):
    from PySide6 import QtCore, QtWidgets
    c, ext, w = eeg_ctrl
    w.resize(1150, 800); QtWidgets.QApplication.processEvents()
    w.set_extra(dict(c.extra(), head=True, signals={"eog": ([0, 50, 0] * 20, 40.0), "emg": ([1, 5, 1] * 20, 3.0)}))
    w.command("select", "F"); w.grab()
    col = QtCore.QRectF(0, 0, w.left_column(), w.height())
    assert w.left_column() > 0 and w.panel_shown()
    assert not any(poly.boundingRect().intersects(col) for poly, _ in w.stickers)        # nothing hidden / unclickable
    assert w._cover is not None and w._cover.isVisible() and "ĐẦU 3D" in w._cover.text  # localized caption
    w.resize(1100, 800); QtWidgets.QApplication.processEvents(); w.grab()
    assert w.width() - w.panel_width() - w.left_column() >= 460 * w._unit() or not w.panel_shown()


def test_the_head_dock_keeps_undo_and_counts_what_does_not_fit(board):
    board.resize(1280, 800)
    board.set_extra(dict(head=True, methods=["tilt", "blink", "jaw"], tilt_on=True, overlay=None)); board.grab()
    assert board.dock_hidden > 0                                                          # "+n" shown
    shown = 11 - board.dock_hidden
    order = ["chip.point", "chip.tilt", "chip.blink", "chip.jaw", "chip.shake"]
    assert shown >= len(order)                                                            # undo is among the first five


def test_turn_lines_are_short_and_name_each_direction(board):
    board.command("select", "R")
    board.set_extra(dict(head=True, methods=["tilt", "blink", "jaw"], tilt_on=True))
    lines = board.turn_hint().split("\n")
    assert len(lines) == 3 and lines[0].startswith("↻") and lines[1].startswith("↺")
    assert "chớp mắt 2 lần" in lines[0] and "nghiến răng" in lines[1]
    board.set_extra(dict(head=True, methods=["jaw"], tilt_on=False, tilt_failed=True))
    hint = board.turn_hint()
    assert "nút" not in hint and "nghiến răng" in hint and "phép thử" in hint             # the buttons speak for themselves
    assert board.bottom_reserve() > 0


def test_space_needs_two_presses_mid_game_like_the_button(board):
    from PySide6 import QtCore
    from PySide6.QtTest import QTest
    g = board.game
    board.command("turn", "R", 1); board.settle()
    QTest.keyClick(board, QtCore.Qt.Key_Space); assert g.moves == 1 and board.scramble_armed_until > 0
    QTest.keyClick(board, QtCore.Qt.Key_Space); assert g.moves == 0


def test_face_keys_select_the_layer_they_turn(mc, qapp):
    from PySide6 import QtCore, QtWidgets
    from PySide6.QtTest import QTest
    B = mc["muse_cube_t.board"]
    w = B.CubeWindow(n=3, depth=3, seed=1); w.show(); QtWidgets.QApplication.processEvents()
    try:
        w.command("select", "F", 1)
        QTest.keyClick(w, QtCore.Qt.Key_R); w.settle(); assert (w.selected, w.depth) == ("R", 0)
        QTest.keyClick(w, QtCore.Qt.Key_M); w.settle(); assert (w.selected, w.depth) == ("L", 1)
        assert w.game.cube.history[-1] == ("L", 1, 1)
    finally:
        w.close()


def test_scale_text_floor_window_size_and_texts(mc, board):
    from PySide6 import QtGui
    T = mc["muse_cube_t.text"]
    board.resize(1280, 800); assert board._unit() == 1.0
    board.resize(800, 640); assert board._unit() == pytest.approx(0.625)
    img = QtGui.QImage(10, 10, QtGui.QImage.Format_RGB32)
    p = QtGui.QPainter(img); board._font(p, 10)
    assert p.font().pointSizeF() == pytest.approx(8.5); p.end()                         # the text floor (0.85)
    avail = QtGui.QGuiApplication.primaryScreen().availableGeometry()
    B = mc["muse_cube_t.board"]; w2 = B.CubeWindow()
    assert w2.width() <= max(800, avail.width() - 40) and w2.height() <= max(640, avail.height() - 40); w2.close()
    assert "bàn phím vẫn dùng được" not in T.t("overlay.esc", "vi")                       # the game IS locked then
    assert T.t("hint.from", "vi", face="mặt phải") == "(nhìn từ mặt phải)"


def test_idle_hint_and_hint_arrow_render(board):
    board.grab()                                                                          # nothing selected: how to start
    board.command("hint"); assert board.game.hint is not None
    assert not board.grab().toImage().isNull()                                            # the curved arrow on the face
    board.command("view", "x", 2); board.settle(); board.grab()                           # the hint face turned away: no arrow


def test_ring_buttons_of_one_cluster_do_not_overlap(mc):
    F = mc["muse_cube_t.flat"]
    for n in (2, 3):
        L = F.Rings(n, 0.0, 0.0, 600.0)
        for axis in (0, 1, 2):
            pts = [pt for ax, coord, *_ in L.rings() if ax == axis for pt in L.label_points(ax, coord)]
            d = min(np.linalg.norm(a - b) for i, a in enumerate(pts) for b in pts[i + 1:])
            assert d >= 0.05 * 600                                                        # ≥ 30 px at 600 px wide
