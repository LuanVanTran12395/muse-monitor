"""Muse Bistro kiosk: ordering state machine, gesture rules on the reused estimators, and the window in the app."""
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PySide6 import QtCore, QtGui

from extensions.food_order import _reuse, menu
from extensions.food_order.gestures import EyeCommands, HeadGestures, reversals
from extensions.food_order.order import Order

REPO = Path(__file__).resolve().parents[1]


# ---- order (pure) --------------------------------------------------------------------------------------------
def test_full_order_by_pointing_and_nodding_with_undo_cart_and_simulated_checkout():
    """Pointing never selects; a nod (yes) chooses the pointed card everywhere; action cards come first."""
    o = Order(recent=["Lu123"])
    assert [c["kind"] for c in o.cards()] == ["account", "guest"]
    o.point(0); assert o.yes(0.0) and o.user == "Lu123" and o.screen == "browse"
    assert o.n_pages() == -(-len(menu.ITEMS["Pizza"]) // 3)
    o.point(0); o.yes(1.0)                                                 # Margherita
    assert o.screen == "size"; o.point(2); o.yes(1.0)                      # L
    assert o.screen == "extras" and o.cards()[0]["kind"] == "extras_done"
    o.point(1); o.yes(1.0); o.point(2); o.yes(1.0); o.yes(1.0)             # Nấm on; cheese on, off
    assert o.draft.extras == {0} and o.cards()[0]["sub"] == "tiếp tục"
    o.point(0); o.yes(1.0); assert o.screen == "qty"                       # ✓ Xong
    o.point(2); o.yes(1.0); o.yes(1.0); o.point(0); o.yes(1.0)             # 1 → 3 → 2
    assert o.draft.qty == 2
    o.point(1); o.yes(2.0)
    line = o.cart[-1]
    assert o.screen == "browse" and line.total == 2 * (129000 + 40000 + 15000) and line.describe() == "Margherita (L) · Nấm"
    assert o.toast["undo"]
    o.no(6.0)                                                             # after the 3 s window: back, not undo
    assert len(o.cart) == 1 and o.screen == "categories"
    o.point(1); o.yes(6.0); assert o.category == "Burger" and o.screen == "browse"
    o.point(0); o.yes(7.0); assert o.screen == "extras"                   # burgers have no size
    o.point(0); o.yes(7.0); o.point(1); o.yes(8.0)                        # no extras → qty → add
    assert len(o.cart) == 2 and o.no(9.0) and len(o.cart) == 1             # shake within 3 s: undo
    o.cart_open(); assert o.screen == "cart" and [c["kind"] for c in o.cards()] == ["checkout", "line"]
    o.point(0); assert o.yes(10.0) and o.popup["kind"] == "order"
    assert not o.select(10.0) and not o.page(1)                            # the popup blocks everything else
    o.yes(11.0); assert o.screen == "done" and o.placed[-1][2] == line.total and o.placed[-1][0] == "Lu123"
    o.point(0); o.yes(12.0); assert o.screen == "browse" and o.cart == []
    o.no(12.0); assert o.screen == "categories"


def test_popups_cancel_by_shake_and_timeout_and_cart_rows_edit():
    o = Order(); o.yes(0.0)                                                # guest
    assert o.user == "Khach01"
    o.point(1); o.yes(0.0); o.yes(0.0); o.point(0); o.yes(0.0); o.point(1); o.yes(0.0)   # Pepperoni M, no extras, ×1
    o.cart_open(); o.point(1); o.yes(1.0); assert o.screen == "row"
    o.point(2); o.yes(1.0); assert o.cart[0].qty == 2
    o.point(0); o.yes(1.0); o.yes(1.0)                                    # 2 → 1 → asks to delete
    assert o.popup["kind"] == "delete"
    o.no(2.0); assert o.popup is None and len(o.cart) == 1
    o.point(1); o.yes(3.0); o.tick(3.0 + 11); assert o.popup is None and len(o.cart) == 1     # timeout = cancel
    o.point(1); o.yes(20.0); o.yes(20.0); assert o.cart == [] and o.screen == "browse"
    o.categories(); o.page(1); o.point(2); o.yes(30.0); assert o.screen == "login"           # logout, empty cart
    o.yes(31.0); o.point(1); o.yes(31.0); o.yes(31.0); o.point(0); o.yes(31.0); o.point(1); o.yes(31.0)
    o.categories(); o.page(1); o.point(2); o.yes(32.0); assert o.popup["kind"] == "logout"    # cart not empty
    o.yes(33.0); assert o.screen == "login" and o.cart == []


# ---- gesture rules -----------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def head_mod():
    return _reuse.head()


def feed_angles(h, seq, dt=1 / 52, t0=0.0):
    ev, t = [], t0
    for yaw, pitch in seq:
        t += dt; ev += h.update(yaw, pitch, t)
    return ev, t


def test_reversals_count_only_real_swings():
    assert reversals([0, 10, 0, 10], 8) == 2 and reversals([0, 5, 0, 5], 8) == 0 and reversals([0, 30, 0], 8) == 1


def test_point_dwell_page_shake_nod_look_up_on_angles(head_mod):
    h = HeadGestures(head_mod, 52)
    ev, t = feed_angles(h, [(0, 0)] * 30)
    ev, t = feed_angles(h, [(15, 0)] * 15, t0=t)                         # left of centre, held
    assert ("point", 0) in ev
    ev, t = feed_angles(h, [(15, 0)] * 90, t0=t)
    assert ev.count(("select", "dwell")) == 1                             # 1.5 s dwell, then cooldown
    ev, t = feed_angles(h, [(-y, 0) for y in range(0, 32, 2)] + [(-30, 0)] * 5 + [(-y, 0) for y in range(30, -1, -3)], t0=t)
    assert ("page", 1) in ev and not any(e[0] == "select" for e in ev)    # full right turn and back = next page
    feed_angles(h, [(0, 0)] * 60, t0=t)
    shake = [(15 * np.sin(2 * np.pi * 3 * k / 52), 0) for k in range(60)]
    ev, t = feed_angles(h, shake, t0=t + 1)
    assert ev.count(("shake",)) == 1 and ("page", 1) not in ev and ("page", -1) not in ev
    ev, t = feed_angles(h, [(0, 0)] * 60, t0=t)
    nod = [(0, 10 * np.sin(2 * np.pi * 2.5 * k / 52)) for k in range(50)]
    ev, t = feed_angles(h, nod, t0=t)
    assert ev.count(("nod",)) == 1
    ev, t = feed_angles(h, [(0, 0)] * 60, t0=t)
    ev, t = feed_angles(h, [(0, min(20, 1.5 * k)) for k in range(80)], t0=t)
    assert ("look_up",) in ev


def test_head_gestures_through_the_reused_pose_tracker(head_mod):
    h = HeadGestures(head_mod, 52); t = [0.0]

    def run(gz=0.0, gy=0.0, secs=0.5):
        out = []
        for _ in range(int(secs * 52)):
            t[0] += 1 / 52; out += h.feed(np.array([[0.], [0.], [1.], [0.], [gy], [gz]]), t[0], t[0])
        return out
    run(secs=1)
    assert ("point", 0) in run(gz=60, secs=0.25) + run(secs=0.4)          # default axes: gyro z = yaw, + = left
    assert ("point", 1) in run(gz=-60, secs=0.25) + run(secs=0.5)
    assert ("page", 1) in run(gz=-120, secs=0.3) + run(secs=0.2) + run(gz=120, secs=0.3) + run(secs=0.5)
    ev = []
    for _ in range(3): ev += run(gz=150, secs=0.12) + run(gz=-150, secs=0.24) + run(gz=150, secs=0.12)
    assert ev.count(("shake",)) == 1 and run(secs=1.5) == []
    ok, msg = h.calibrate("neutral", np.tile([0, 0, 1, 0, 0, 0], (52, 1)))
    assert ok and not h.calibrate("left", np.tile([0, 0, 1, 0, 0, 0], (78, 1)))[0]   # no movement → repeat


def _eeg(rng, seconds, blinks=(), closed=None, amp=120, rows=(1, 2), alpha=0.0):
    """4 × n µV: blinks (Gaussian bumps on ``rows``: AF7 / AF8 by default; TP9 / TP10 = (0, 3) with amp < 0, the
    blink seen through the Fpz reference); closed=(t0, t1): a closing bump at t0, then quiet (+ ``alpha`` µV 10 Hz)."""
    n = int(seconds * 256); x = rng.normal(0, 5, (4, n)); t = np.arange(n) / 256; rows = list(rows)
    for b in blinks: x[rows] += amp * np.exp(-0.5 * ((t - b) / 0.06) ** 2)
    if closed:                                  # as in the captures: one large closing deflection, then quiet
        c0, c1 = closed
        x[rows] += 1.3 * amp * np.exp(-0.5 * ((t - c0) / 0.12) ** 2)
        quiet = (t > c0 + 0.4) & (t < c1); x[:, quiet] *= 0.3
        x[np.ix_(rows, quiet)] += alpha * np.sin(2 * np.pi * 10 * t[quiet])
    return x


def _run(ec, x, t0, detect=True):
    out, filt = [], []
    for i in range(0, x.shape[1], 12):
        f, ev = ec.feed(x[:, i:i + 12], t0 + i / 256, detect=detect); out += ev; filt.append(f)
    return out, np.concatenate(filt, axis=1)


def test_eye_commands_default_to_tp_and_read_the_chosen_pair():
    names = ["TP9", "AF7", "AF8", "TP10"]
    assert EyeCommands(_reuse.eyes(), 256, names).source == "tp"
    assert EyeCommands(_reuse.eyes(), 256, names, source="bogus").source == "tp"
    x = np.arange(8.0).reshape(4, 2)
    assert np.array_equal(EyeCommands(_reuse.eyes(), 256, names).inputs(x)[1:3], x[[0, 3]])
    assert np.array_equal(EyeCommands(_reuse.eyes(), 256, names, source="diff").inputs(x)[1:3], x[1:3] - x[[0, 3]])
    assert np.array_equal(EyeCommands(_reuse.eyes(), 256, names, source="af").inputs(x), x)


@pytest.mark.parametrize("source, kw", [("af", {}), ("tp", dict(rows=(0, 3), amp=-120, alpha=10.0))])
def test_eye_commands_double_blink_and_eye_closure(source, kw):
    rng = np.random.default_rng(1)
    ec = EyeCommands(_reuse.eyes(), 256, ["TP9", "AF7", "AF8", "TP10"], source=source)
    def sig(rng, seconds, **k): return _eeg(rng, seconds, **k, **kw)
    raw = sig(rng, 5.0); _, f = _run(ec, raw, 0.0, detect=False)
    assert ec.calibrate_open(raw[:, 256:], f[:, 256:])[0]
    raw = sig(rng, 6.0, blinks=(0.6, 0.95, 2.4, 2.75, 4.2, 4.55)); _, f = _run(ec, raw, 5.0, detect=False)
    assert ec.calibrate_blink(f)[0] and ec.blink_ready
    assert 0.15 <= ec.cfg["pair_min_s"] <= 0.35 <= ec.cfg["pair_max_s"] <= 0.8      # this user's spacing
    raw = sig(rng, 4.0, closed=(0.5, 3.6)); _, f = _run(ec, raw, 11.0, detect=False)
    assert ec.calibrate_closed(raw, f)[0] and ec.closure_ready
    ec.reset_runtime()
    ev, _ = _run(ec, sig(rng, 3.0, blinks=(1.0, 1.35)), 20.0)
    assert ev.count(("double_blink",)) == 1 and ev.count(("blink",)) == 2
    ev, _ = _run(ec, sig(rng, 4.0, blinks=(0.5, 2.5)), 30.0)                      # far apart: not a double
    assert ("double_blink",) not in ev
    ev, _ = _run(ec, sig(rng, 4.0, blinks=(0.5, 0.85, 1.2)), 40.0)                # three in a row: not isolated
    assert ("double_blink",) not in ev
    ev, _ = _run(ec, sig(rng, 5.0, closed=(0.5, 4.6)), 50.0)                      # closed until the tone
    assert ev.count(("eyes_closed",)) == 1
    ev, _ = _run(ec, sig(rng, 4.0, blinks=(0.5, 1.6, 2.7)), 60.0)                 # open: blinks keep coming
    assert ("eyes_closed",) not in ev
    ec.note_motion(np.array([[0.0], [0.0], [1.0], [80.0], [0.0], [0.0]]))          # head moving: no command
    ev, _ = _run(ec, sig(rng, 0.2), 70.0)
    ec.note_motion(np.array([[0.0], [0.0], [1.0], [80.0], [0.0], [0.0]]))
    ev, _ = _run(ec, sig(rng, 3.0, blinks=(0.3, 0.65)), 70.2)
    assert ("double_blink",) not in ev


def test_eye_shortcuts_are_harmless_overlays_and_a_nod_completes_them():
    o = Order(); o.yes(0.0); o.point(2)
    assert o.details(1.0) and o.overlay["kind"] == "details" and o.overlay["card"]["title"] == "Hải sản"
    assert any("Size:" in line for line in o.item_details(o.overlay["card"]))
    o.point(0); o.page(1); o.tick(1.0 + 60)                               # no time limit, head moves ignored
    assert o.overlay and o.overlay["card"]["title"] == "Hải sản" and o.focus == 2 and o.page_no() == 0
    assert o.no(62.0) and o.overlay is None                                # only a shake closes it
    o.details(63.0); assert o.yes(63.0) and o.screen == "size"             # a nod chooses the item shown
    o.no(4.0)
    assert o.cart_peek(5.0) and o.overlay["kind"] == "peek" and o.yes(5.0) is True and o.popup is None  # empty cart
    o.point(1); o.yes(6.0); o.yes(6.0); o.point(0); o.yes(6.0); o.point(1); o.yes(6.0)          # one pizza
    o.cart_peek(10.0); assert o.yes(10.0) and o.popup["kind"] == "order"   # quick cart → nod → order popup
    o.no(11.0); o.cart_peek(12.0); assert o.no(12.0) and o.overlay is None and o.screen == "browse"


# ---- the kiosk in the app ----------------------------------------------------------------------------------
@pytest.fixture
def app_with_kiosk(qapp, spec, settings, monkeypatch, tmp_path):
    from musemonitor.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path / "data"))
    ext_dir = tmp_path / "exts"
    for name in ("food_order", "head_motion_plus", "eye_interaction"):        # siblings: reused read-only
        shutil.copytree(REPO / "extensions" / name, ext_dir / name, ignore=shutil.ignore_patterns("__pycache__"))
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(ext_dir)]); w.resize(1200, 800); w.show()
    ext = next(r for r in w.extensions.records if r.id == "food_order").instance
    yield w, ext
    ext.controller.close(); w.connected = False; w.close()


def key(k):
    return QtGui.QKeyEvent(QtCore.QEvent.KeyPress, k, QtCore.Qt.NoModifier, "")


def rect_of(win, action):
    win.grab()                                                            # paint: hit boxes = what is drawn
    return next(r for r, a in win.hits if a == action)


def click(win, action=None, at=None):
    from PySide6 import QtTest
    pos = (rect_of(win, action).center() if action else at).toPoint()
    QtTest.QTest.mouseClick(win, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, pos)


def test_kiosk_keyboard_and_mouse_order_and_every_screen_draws(app_with_kiosk):
    w, ext = app_with_kiosk
    c = ext.controller
    assert c.reuse_error == "" and c.head is not None and c.eyes is not None
    win = c.open(); win.resize(1280, 800)
    assert c.calib is not None and win.view["mode"] == "calib"            # quick calibration first
    assert not win.grab().isNull()
    c._key(key(QtCore.Qt.Key_Escape)); assert c.calib is None              # skip → keyboard / mouse / dwell
    assert win.edit.isVisible()
    win.edit.setText("M 01"); win._clean("M 01"); win.edit.returnPressed.emit()
    assert c.order.user == "M_01" and ext.app.setting("recent_accounts") == "M_01"
    seen = set()
    for k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Return, QtCore.Qt.Key_1, QtCore.Qt.Key_Y,     # pizza, M, ✓ Xong
              QtCore.Qt.Key_2, QtCore.Qt.Key_Return,                                              # qty → add
              QtCore.Qt.Key_Up, QtCore.Qt.Key_PageDown, QtCore.Qt.Key_1, QtCore.Qt.Key_Return,   # categories → dessert
              QtCore.Qt.Key_3, QtCore.Qt.Key_Return, QtCore.Qt.Key_Return,                        # item 3 → qty → add
              QtCore.Qt.Key_C, QtCore.Qt.Key_1, QtCore.Qt.Key_Y):                                 # cart → Đặt hàng
        c._key(key(k)); c._render(); seen.add(c.order.screen); assert not win.grab().isNull()
    assert c.order.popup and c.order.popup["kind"] == "order"
    click(win, ("popup_yes",))                                              # the Yes button, where it is drawn
    assert c.order.screen == "done" and c.order.placed and len(c.order.placed[-1][1]) == 2
    assert {"browse", "size", "extras", "qty", "categories", "cart"} <= seen | {"size", "extras"}
    c.order.no(0.0); assert c.order.screen == "login"


def test_gesture_events_drive_the_order_and_calibration_finishes(app_with_kiosk):
    w, ext = app_with_kiosk
    c = ext.controller
    now = [100.0]; ext.mono = lambda: now[0]
    win = c.open()
    # calibration with a still head and flat EEG: steps fail, are repeated once, then skipped — it must end
    w.connected = w.streaming = True
    for _ in range(3000):
        if c.calib is None: break
        now[0] += 0.04
        c.on_imu(np.array([[0.0] * 2, [0.0] * 2, [1.0] * 2, [0.0] * 2, [0.0] * 2, [0.0] * 2]), np.array([now[0]] * 2))
        c.on_eeg(np.random.default_rng(0).normal(0, 3, (4, 10)), np.array([now[0]] * 10))
        c._tick()
    assert c.calib is None
    c.order.recent = []
    c._event(("point", 0), now[0]); c._event(("select", "dwell"), now[0])  # dwell is off by default: nothing
    assert c.order.user is None and c.order.screen == "login"
    c._event(("nod",), now[0])                                             # a nod chooses (guest)
    assert c.order.user and c.order.screen == "browse"
    c._event(("look_up",), now[0]); assert c.order.screen == "categories"
    c._event(("shake",), now[0]); assert c.order.screen == "browse"
    c._event(("page", 1), now[0]); assert c.order.page_no() == 1
    c._event(("double_blink",), now[0])                                  # eye shortcut: details of the pointed item
    assert c.order.overlay and c.order.overlay["kind"] == "details" and c.order.screen == "browse"
    c._event(("nod",), now[0]); assert c.order.screen in ("size", "extras", "qty")
    c._event(("eyes_closed",), now[0]); assert c.order.overlay["kind"] == "peek"
    c._event(("shake",), now[0]); assert c.order.overlay is None
    ext.app.set_setting("eye_details", False)
    c._event(("double_blink",), now[0]); assert c.order.overlay is None     # switched off in the tab
    c._event(("blink",), now[0]); assert c.view()["eye"]["blink"] is True   # every blink is shown
    assert ("Nhắm mắt", "off") in c.signals()                              # not calibrated: shown as off


def test_kiosk_without_the_other_extensions_is_keyboard_only(qapp, spec, settings, monkeypatch, tmp_path):
    from musemonitor.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path / "data"))
    ext_dir = tmp_path / "exts"
    shutil.copytree(REPO / "extensions" / "food_order", ext_dir / "food_order", ignore=shutil.ignore_patterns("__pycache__"))
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(ext_dir)]); w.show()
    ext = next(r for r in w.extensions.records if r.id == "food_order").instance
    c = ext.controller
    try:
        assert c.head is None and "head_motion_plus" in c.reuse_error
        win = c.open(); assert c.calib is None and win.edit.isVisible()
        assert "keyboard and mouse only" in ext.kiosk_status()
        win.edit.setText("K1"); win.edit.returnPressed.emit(); assert c.order.screen == "browse"
    finally:
        c.close(); w.connected = False; w.close()


# ---- camera (head_motion_plus's module, reused) and the demo video --------------------------------------------
def test_camera_recenters_when_facing_and_still_and_switches_the_demo_layout(app_with_kiosk):
    w, ext = app_with_kiosk
    c = ext.controller
    if c.camera is None: pytest.skip(f"camera unavailable: {c.camera_why}")    # OpenCV is optional (not in CI)
    assert c.gate is not None
    win = c.open(calibrate=False)
    c._key(key(QtCore.Qt.Key_Escape))
    for _ in range(60):                                                   # a still head
        c.on_imu(np.array([[0.0] * 3, [0.0] * 3, [1.0] * 3, [0.0] * 3, [0.0] * 3, [0.0] * 3]), np.array([0.0] * 3))
    c.head.yaw_offset = 7.0
    c.gate.hold_sec = 0.0                                                 # the rule itself is FacingGate's (1 s)
    c._cam_result(dict(face=False, facing=False, reason="no face")); assert c.head.yaw_offset == 7.0
    c._cam_result(dict(face=True, facing=True, reason="facing the screen"))
    assert c.head.yaw_offset == 0.0 and "camera" in c.received[0]          # recentered, and said so
    c._cam_result(dict(face=True, facing=True, reason="facing the screen"))  # cooldown: not again at once
    img = QtGui.QImage(640, 480, QtGui.QImage.Format_RGB32); img.fill(QtGui.QColor("#88aacc"))
    c._cam_frame(img)
    assert win.demo() and win.content_right() < win.width() and not win.grab().isNull()
    assert win.avatars[0].geometry().left() >= win.content_right()        # head and eyes moved to the right column
    c.camera_stop(); assert not win.demo()


def test_demo_recorder_writes_a_playable_video(app_with_kiosk, tmp_path):
    cv2 = pytest.importorskip("cv2")                                     # OpenCV is optional (not in CI)
    w, ext = app_with_kiosk
    c = ext.controller
    ok, msg = c.record_start()
    assert ok and c.recorder.active and c.last_video.suffix == ".mp4"
    for _ in range(5): c.recorder._grab()
    c._tick(); assert c.window.recording is not None
    path = c.record_stop()
    assert path.exists() and path.stat().st_size > 0 and c.window.recording is None
    cap = cv2.VideoCapture(str(path)); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); cap.release()
    assert n >= 5


# ---- bilingual (VI / EN) --------------------------------------------------------------------------------------
def test_every_text_exists_in_both_languages():
    from extensions.food_order import text
    for key, (vi, en) in text.S.items():
        assert vi and en, key
    assert text.t("pop.order", "en", n=2, total="10đ") == "Place 2 items · 10đ?"
    assert text.t("pop.order", "vi", n=2, total="10đ") == "Đặt 2 món · 10đ?"
    assert text.t("no.such.key", "en") == "no.such.key"


def test_english_order_and_switching_language_mid_order_translates_the_cart():
    o = Order(lang="en")
    assert [c["title"] for c in o.cards()] == ["New guest"]
    o.yes(0.0); assert o.user == "Guest01" and o.toast["text"] == "Hello Guest01!"
    assert [c["title"] for c in o.cards()] == ["Margherita", "Pepperoni", "Seafood"]
    o.categories(); assert [c["title"] for c in o.cards()] == ["Pizza", "Burgers", "Drinks"]
    o.point(2); o.yes(1.0); o.point(0); o.yes(1.0)                       # Drinks → Peach tea
    assert o.screen == "size" and o.cards()[1]["sub"] == "Medium · 500 ml"
    o.yes(1.0); assert o.cards()[0]["title"] == "✓ Done" and o.cards()[1]["title"] == "Less ice"
    o.point(1); o.yes(1.0); o.point(0); o.yes(1.0); o.point(1); o.yes(2.0)
    line = o.cart[0]
    assert line.describe("en") == "Peach tea (M) · Less ice" and o.toast["text"] == "✓ Added Peach tea (M) · Less ice × 1"
    assert o.set_lang("vi") and line.describe(o.lang) == "Trà đào (M) · Ít đá"     # the same line, now in Vietnamese
    o.cart_open(); assert o.cards()[1]["title"] == "Trà đào (M) · Ít đá" and o.cards()[0]["title"] == "Đặt hàng"
    o.set_lang("en"); assert not o.details(10.0)                          # not on the cart screen: nothing
    o.no(10.0); assert o.screen == "browse"; o.point(0); o.details(11.0)
    assert o.overlay and any(l.startswith("Size:") for l in o.item_details(o.overlay["card"]))


def test_kiosk_language_per_account_look_up_and_l_key(app_with_kiosk):
    w, ext = app_with_kiosk
    c = ext.controller
    win = c.open(calibrate=False); c._key(key(QtCore.Qt.Key_Escape))
    assert c.order.lang == "vi"
    c._event(("look_up",), 0.0); assert c.order.lang == "en"              # sign-in screen: look up = language
    assert win.edit.placeholderText().startswith("Customer code") and win.view["lang"] == "en"
    assert c.view()["chips"][-1] == ("L", "language") and not win.grab().isNull()      # no IMU: keyboard chips
    c._login("ANNA"); assert c.order.user == "ANNA"
    c.order._logout(); c._key(key(QtCore.Qt.Key_L)); assert c.order.lang == "vi"    # ANNA signed in with EN
    c._login("ANNA"); assert c.order.lang == "en"                         # her language comes back with her account
    assert "Browsing · Pizza" in c.view()["mode_label"] and c.view()["heading"] == "Pizza"
    assert ext.tab.lang_box.findData("en") >= 0
    ext.tab.update_texts(); assert ext.tab.lang_box.currentData() == "en"



# ---- mouse hit testing, closing, keyboard mode (Codex UI/UX review P0 / P1) ----------------------------------------
def _signed_in_with_one_item(c, win):
    c._key(key(QtCore.Qt.Key_Escape)); c._login("T1")
    for k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Return, QtCore.Qt.Key_1, QtCore.Qt.Key_Return, QtCore.Qt.Key_2,
              QtCore.Qt.Key_Return):                                    # pizza, M, ✓ Done, add
        c._key(key(k))
    assert len(c.order.cart) == 1


def test_clicks_hit_only_the_drawn_controls_and_never_fall_through_a_modal_layer(app_with_kiosk):
    w, ext = app_with_kiosk
    c = ext.controller
    win = c.open(calibrate=False); win.resize(1280, 800)
    _signed_in_with_one_item(c, win)
    c._key(key(QtCore.Qt.Key_C)); c._key(key(QtCore.Qt.Key_1)); c._key(key(QtCore.Qt.Key_Return))   # order popup
    assert c.order.popup["kind"] == "order"; c._render()
    click(win, at=QtCore.QPointF(30, 300))                                  # dark area outside the popup: nothing
    yes = rect_of(win, ("popup_yes",))
    click(win, at=QtCore.QPointF(yes.left() + 10, yes.top() - 120))         # the popup's title, left half: nothing
    assert c.order.popup and not c.order.placed
    click(win, ("popup_no",)); assert c.order.popup is None and not c.order.placed
    c._key(key(QtCore.Qt.Key_1)); c._key(key(QtCore.Qt.Key_Return)); c._render()
    click(win, ("popup_yes",)); assert c.order.screen == "done" and len(c.order.placed) == 1
    c._key(key(QtCore.Qt.Key_1)); c._key(key(QtCore.Qt.Key_Return))        # new order → browse
    c._render(); click(win, ("cat", "Drink")); assert c.order.category == "Drink" and c.order.screen == "browse"
    gap_x = (rect_of(win, ("card", 0)).right() + rect_of(win, ("card", 1)).left()) / 2
    click(win, at=QtCore.QPointF(gap_x, rect_of(win, ("card", 0)).center().y()))   # between two cards: nothing
    assert c.order.screen == "browse"
    c.eyes.blink_thr = 40.0; c.order.point(0); c.order.details(0.0); c._render()
    click(win, at=rect_of(win, ("overlay_no",)).center() + QtCore.QPointF(0, 200))  # behind the sheet: blocked
    assert c.order.overlay and c.order.screen == "browse"
    click(win, ("overlay_no",)); assert c.order.overlay is None
    c._render(); click(win, ("card", 2)); assert c.order.screen == "size"   # a card, where it is drawn
    c.order.no(0.0); c._render(); click(win, ("cart",)); assert c.order.screen == "cart"
    img = QtGui.QImage(640, 480, QtGui.QImage.Format_RGB32); img.fill(QtGui.QColor("#557"))
    c._cam_frame(img); c.order.no(0.0); c._render()                          # demo layout: narrower cards
    r = rect_of(win, ("card", 2)); assert r.right() < win.content_right()
    click(win, ("card", 2)); assert c.order.screen == "size"
    c.camera_stop()


def test_closing_keeps_the_cart_and_says_so_when_reopened(app_with_kiosk):
    w, ext = app_with_kiosk
    c = ext.controller
    win = c.open(calibrate=False)
    _signed_in_with_one_item(c, win)
    win.close(); assert c.window is None and len(c.order.cart) == 1          # no dialog, nothing lost
    c.open(calibrate=False)
    assert "1" in c.order.toast["text"] and ("vẫn còn" in c.order.toast["text"] or "still" in c.order.toast["text"])


def test_keyboard_mode_when_the_imu_is_silent_and_undo_window_vs_toast(app_with_kiosk):
    w, ext = app_with_kiosk
    c = ext.controller
    now = [100.0]; ext.mono = lambda: now[0]
    win = c.open(calibrate=False); c._key(key(QtCore.Qt.Key_Escape)); c._login("T2")
    v = c.view()
    assert v["keyboard_only"] and ("Enter", "chọn") in v["chips"] and dict(c.signals())["Đầu"] == "off"
    assert v["mode_label"].startswith("Bàn phím / chuột")
    imu = np.array([[0.0] * 3, [0.0] * 3, [1.0] * 3, [0.0] * 3, [0.0] * 3, [0.0] * 3])
    c.on_imu(imu, np.array([0.0] * 3))
    v = c.view(); assert not v["keyboard_only"] and v["chips"][1] == ("↕", "gật: chọn") and dict(c.signals())["Đầu"] == "ok"
    now[0] += 1.5                                                           # IMU stops while EEG may go on
    assert c.view()["keyboard_only"] and dict(c.signals())["Đầu"] == "off"
    for k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Return, QtCore.Qt.Key_1, QtCore.Qt.Key_Return, QtCore.Qt.Key_2,
              QtCore.Qt.Key_Return):
        c._key(key(k))
    assert "lắc để hoàn tác" in c.view()["toast"]["right"]
    now[0] += 3.5
    t = c.view()["toast"]; assert t and "right" not in t                   # still readable, undo over
    c.order.no(now[0]); assert len(c.order.cart) == 1                       # a late shake does not undo
    assert "Đang trỏ" in win.accessibleDescription()


def test_whole_order_with_the_keyboard_only_real_key_events(app_with_kiosk):
    """No headset: sign in, choose, options, cart, order, edit and delete, details and quick cart — keys only, sent to
    the window as real key events. Enter must do what the dock says (choose / confirm / act on a sheet)."""
    from PySide6 import QtTest
    w, ext = app_with_kiosk
    c = ext.controller
    win = c.open(calibrate=False)
    press = lambda k: QtTest.QTest.keyClick(win, k)
    press(QtCore.Qt.Key_Escape)                                            # skip calibration
    win.edit.clear(); QtTest.QTest.keyClicks(win.edit, "KB1"); QtTest.QTest.keyClick(win.edit, QtCore.Qt.Key_Return)
    o = c.order
    assert o.user == "KB1" and o.screen == "browse" and c.view()["keyboard_only"]
    assert ("Enter", "chọn") in c.view()["chips"]
    press(QtCore.Qt.Key_Right); press(QtCore.Qt.Key_Return)               # Hải sản
    assert o.screen == "size" and o.draft.index == 2
    press(QtCore.Qt.Key_Right); press(QtCore.Qt.Key_Return)               # L
    assert o.screen == "extras" and o.draft.size == 2
    press(QtCore.Qt.Key_2); press(QtCore.Qt.Key_Return)                   # Nấm on
    press(QtCore.Qt.Key_1); press(QtCore.Qt.Key_Return)                   # ✓ Xong
    assert o.screen == "qty"
    press(QtCore.Qt.Key_3); press(QtCore.Qt.Key_Return)                   # 2
    press(QtCore.Qt.Key_2); press(QtCore.Qt.Key_Return)                   # add
    assert o.screen == "browse" and o.cart[0].qty == 2 and o.cart[0].describe("vi") == "Hải sản (L) · Nấm"
    press(QtCore.Qt.Key_C); assert o.screen == "cart"
    press(QtCore.Qt.Key_2); press(QtCore.Qt.Key_Return)                   # the line → edit
    assert o.screen == "row"
    press(QtCore.Qt.Key_2); press(QtCore.Qt.Key_Return)                   # Xoá → popup
    assert o.popup["kind"] == "delete" and c.view()["chips"][0] == ("Enter", "đồng ý")
    press(QtCore.Qt.Key_Backspace); assert o.popup is None and len(o.cart) == 1   # ⌫ cancels
    press(QtCore.Qt.Key_2); press(QtCore.Qt.Key_Return); press(QtCore.Qt.Key_Return)   # Enter confirms the removal
    assert o.cart == [] and o.screen == "browse"
    press(QtCore.Qt.Key_1); press(QtCore.Qt.Key_D)                        # details sheet (Margherita)
    assert o.overlay and o.overlay["kind"] == "details"
    press(QtCore.Qt.Key_Return)                                           # Enter on the sheet chooses the item
    assert o.overlay is None and o.screen == "size" and o.draft.index == 0
    press(QtCore.Qt.Key_Return); press(QtCore.Qt.Key_1); press(QtCore.Qt.Key_Return); press(QtCore.Qt.Key_2)
    press(QtCore.Qt.Key_Return)                                           # M, no extras, add ×1
    assert len(o.cart) == 1
    press(QtCore.Qt.Key_V); assert o.overlay["kind"] == "peek"            # quick cart sheet
    press(QtCore.Qt.Key_Return); assert o.popup["kind"] == "order"        # Enter on the sheet → order popup
    press(QtCore.Qt.Key_Return)                                           # Enter confirms the order
    assert o.screen == "done" and o.placed and o.placed[-1][0] == "KB1" and len(o.placed[-1][1]) == 1
    press(QtCore.Qt.Key_Backspace); assert o.screen == "login" and o.user is None   # ⌫ on the done screen: sign out


def test_demo_video_is_started_and_stopped_from_the_kiosk_and_the_tab_says_what_it_does(app_with_kiosk):
    pytest.importorskip("cv2")                                           # the recorder writes with OpenCV
    w, ext = app_with_kiosk
    c = ext.controller
    win = c.open(calibrate=False); c._key(key(QtCore.Qt.Key_Escape))
    assert ext.tab.rec_btn.text() == "🎬 Record demo video"
    from PySide6 import QtTest
    QtTest.QTest.keyClick(win, QtCore.Qt.Key_F9)                          # start from the (full-screen) kiosk
    assert c.recorder.active and "F9" in c.order.toast["text"]
    c.recorder._grab(); c._tick()
    ext.tab.update_texts(); assert ext.tab.rec_btn.text().startswith("■ Stop demo video")
    assert "Stop recording" not in ext.tab.rec_btn.text()                 # never the app's EEG-recording wording
    c._render(); click(win, ("rec_stop",))                                # the red label is the stop button
    assert not c.recorder.active and c.last_video.exists()
    assert c.last_video.name in c.order.toast["text"]                     # the kiosk says where it went
    ext.tab.update_texts(); assert ext.tab.rec_btn.text() == "🎬 Record demo video"   # tab follows a kiosk stop


def test_eye_closure_calibration_is_long_enough():
    from extensions.food_order.controller import CALIB
    assert dict(CALIB)["closed"] >= 6.0


def test_eye_source_defaults_to_tp_and_switching_it_asks_for_a_new_eye_calibration(app_with_kiosk):
    w, ext = app_with_kiosk
    c = ext.controller
    assert c.eyes.source == "tp" and ext.tab.eye_src.currentData() == "tp"
    old = c.eyes
    ext.tab.eye_src.setCurrentIndex(ext.tab.eye_src.findData("af"))
    assert c.eyes is not old and c.eyes.source == "af" and c.eye_source() == "af"
    assert not c.eyes.blink_ready and not c.eyes.closure_ready              # calibrate again for the new pair
