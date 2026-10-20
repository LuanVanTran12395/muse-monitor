"""Calibration and recentering for the Athena head motion extension."""

import numpy as np
import pytest

from extensions.head_motion_plus import PoseTracker, _rotate, axes_from_motions


def test_calibration_recovers_head_axes_from_left_turn_and_look_up():
    axes = axes_from_motions((0, 0, 25), (0, -20, 0))
    assert np.allclose(axes, ((0, 1, 0), (0, 0, 1), (1, 0, 0)))
    assert np.allclose(axes @ axes.T, np.eye(3))
    assert np.linalg.det(axes) > 0.99


def test_calibration_rejects_same_axis_twice():
    with pytest.raises(ValueError):
        axes_from_motions((0, 0, 20), (0, 0, -20))


def test_recenter_requires_stillness():
    tracker = PoseTracker(52)
    moving = np.zeros((6, 52))
    moving[2] = -1
    moving[5] = 45
    tracker.add(moving, 1.0)
    assert _rotate(tracker.q, (0, 0, 1))[0] > 0.5
    assert tracker.recenter() is False

    tracker.set_calibration(axes_from_motions((0, 0, 25), (0, -20, 0)), (0, 0, 0))
    still = np.zeros((6, 52))
    still[2] = -1
    tracker.add(still, 2.0)
    assert tracker.recenter() is True
    assert np.allclose(tracker.q, (1, 0, 0, 0))


# ---- Camera "facing the screen" reference (no real camera is opened in tests) ----------------
import math
from pathlib import Path

from extensions.head_motion_plus import camera as cam

REPO = Path(__file__).resolve().parents[1]


def face_row(yaw=0.0, pitch=0.55, roll_deg=0.0, score=0.95, width=80):
    """Synthetic YuNet row: eyes 40 px apart, nose offset by yaw ratio, mouth 50 px below eyes."""
    cx, ey = 160, 100
    r = math.radians(roll_deg)
    eye_r = (cx - 20 * math.cos(r), ey - 20 * math.sin(r))
    eye_l = (cx + 20 * math.cos(r), ey + 20 * math.sin(r))
    nose = (cx + yaw * 40, ey + pitch * 50)
    return np.array([cx - width / 2, ey - 40, width, width * 1.2, *eye_r, *eye_l, *nose,
                     cx - 18, ey + 50, cx + 18, ey + 50, score])


def test_facing_from_landmarks():
    assert cam.facing_from_face(face_row(), 320)["facing"]
    assert cam.facing_from_face(face_row(yaw=0.25), 320)["reason"] == "turned left"     # nose right of centre
    assert cam.facing_from_face(face_row(yaw=-0.25), 320)["reason"] == "turned right"
    assert cam.facing_from_face(face_row(pitch=0.85), 320)["reason"] == "looking down"  # nose near the mouth
    assert cam.facing_from_face(face_row(pitch=0.25), 320)["reason"] == "looking up"
    assert cam.facing_from_face(face_row(roll_deg=20), 320)["reason"] == "head tilted"
    assert cam.facing_from_face(face_row(width=20), 320)["reason"] == "too far from camera"
    assert cam.facing_from_face(face_row(score=0.5), 320)["reason"] == "face unclear"


def test_facing_gate_needs_hold_and_respects_cooldown():
    g = cam.FacingGate(hold_sec=1.0, cooldown_sec=5.0)
    assert not g.update(True, True, 0.0) and not g.update(True, True, 0.9)
    assert g.update(True, True, 1.0)                       # facing + still for 1 s → recenter
    assert not g.update(True, True, 2.5)                   # cooldown
    assert not g.update(True, False, 6.0)                  # moving → reset hold
    assert not g.update(True, True, 6.1) and g.update(True, True, 7.2)


def test_yunet_detects_rendered_head_facing_vs_turned(qapp):
    cv2 = pytest.importorskip("cv2")
    ok, why = cam.availability()
    if not ok: pytest.skip(why)
    from PySide6 import QtGui
    from extensions.head_motion_plus import HeadCanvas
    tracker = PoseTracker(52); canvas = HeadCanvas(tracker); canvas.resize(640, 480)
    det = cv2.FaceDetectorYN.create(str(cam.MODEL), "", (320, 240), 0.5)
    results = {}
    for name, yaw in (("front", 0), ("turned", 25)):
        a = math.radians(yaw) / 2
        tracker.q = np.array((math.cos(a), 0, math.sin(a), 0))
        img = canvas.grab().toImage().convertToFormat(QtGui.QImage.Format_RGB888)
        w, h = img.width(), img.height()
        rgb = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h, w, 3)
        small = cv2.resize(rgb[:, :, ::-1].copy(), (320, int(h * 320 / w)))
        det.setInputSize((small.shape[1], small.shape[0]))
        _, faces = det.detect(small)
        assert faces is not None and len(faces)
        results[name] = cam.facing_from_face(max(faces, key=lambda f: f[2] * f[3]), small.shape[1])
    assert results["front"]["facing"] and not results["turned"]["facing"]


@pytest.fixture
def plus_tab(qapp, spec, settings, monkeypatch):
    from musemonitor.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(REPO / "extensions")])
    rec = next(r for r in w.extensions.records if r.id == "head_motion_plus")
    started = []
    monkeypatch.setattr(rec.instance.tab.cam, "start", lambda device_id=None: started.append(device_id))
    yield rec.instance.tab, started, w
    w.close()


def test_camera_needs_consent_every_time(plus_tab, monkeypatch):
    tab, started, _ = plus_tab
    assert not tab.cam_check.isChecked()                                 # off by default
    monkeypatch.setattr(tab, "_ask_camera_consent", lambda: False)
    tab.cam_check.setChecked(True)
    assert started == [] and not tab.cam_check.isChecked() and "permission" in tab.cam_status.text()


def test_camera_blocked_by_macos_is_explained(plus_tab, monkeypatch):
    tab, started, _ = plus_tab
    monkeypatch.setattr(tab, "_ask_camera_consent", lambda: True)
    monkeypatch.setattr(tab, "_os_camera_permission", lambda: "denied")
    tab.cam_check.setChecked(True)
    assert started == [] and not tab.cam_check.isChecked() and "System Settings" in tab.cam_status.text()


def test_camera_on_auto_recenters_when_facing_and_still(plus_tab, monkeypatch):
    tab, started, w = plus_tab
    import sys
    mod = type(tab).__module__                                       # module the loader imported the tab from
    monkeypatch.setattr(tab, "_ask_camera_consent", lambda: True)
    monkeypatch.setattr(tab, "_os_camera_permission", lambda: "granted")
    tab.cam_check.setChecked(True)
    assert started == [tab.cam_select.currentData()] and tab.cam_check.isChecked()
    tab._camera_running(True)
    assert tab.cam_auto.isEnabled() and not tab.cam_live.isHidden()     # "● Camera on" shown while running
    tracker = tab.ext.tracker
    still = np.zeros((6, 52)); still[2] = -1
    tracker.add(still, 1.0)
    tracker.q = np.array((math.cos(0.2), 0, math.sin(0.2), 0))       # drifted yaw
    clock = iter([100.0, 100.5, 101.1])
    monkeypatch.setattr(sys.modules[mod].time, "monotonic", lambda: next(clock))
    for _ in range(3):
        tab._camera_result(dict(face=True, facing=True, reason="facing the screen"))
    assert np.allclose(tracker.q, (1, 0, 0, 0)) and "Auto-recentered" in tab.calibration_info.text()
    tab.ext.deactivate()                                             # unload / app close → camera off
    assert not tab.cam_check.isChecked() and tab.cam_live.isHidden() and tab.cam_status.text() == "Camera off."


def test_prefers_mac_camera_over_iphone_continuity():
    cams = [("iphone-id", "Luan's iPhone Camera"), ("mac-id", "FaceTime HD Camera")]
    assert cam.preferred_camera(cams) == "mac-id"                       # iPhone listed first → still Mac
    assert cam.preferred_camera(cams, saved_id="iphone-id") == "iphone-id"   # explicit user choice wins
    assert cam.preferred_camera(cams, saved_id="gone") == "mac-id"
    assert cam.preferred_camera([("i", "iPhone Camera")]) == "i"            # only camera available
    assert cam.preferred_camera([]) is None


def test_camera_list_selects_mac_and_remembers_choice(plus_tab, monkeypatch):
    import sys
    tab, started, _ = plus_tab
    mod = sys.modules[type(tab).__module__].camera                       # module the loader imported
    monkeypatch.setattr(mod, "list_cameras", lambda: [("iphone-id", "Camera iPhone"), ("mac-id", "Camera FaceTime HD")])
    tab.refresh_cameras()
    assert tab.cam_select.count() == 2 and tab.cam_select.currentData() == "mac-id"
    tab.cam_select.setCurrentIndex(tab.cam_select.findData("iphone-id"))     # user picks the iPhone
    assert tab.ext.app.setting("camera_id") == "iphone-id"
    tab.refresh_cameras()                                                 # e.g. devices changed
    assert tab.cam_select.currentData() == "iphone-id"
    monkeypatch.setattr(tab, "_ask_camera_consent", lambda: True)
    monkeypatch.setattr(tab, "_os_camera_permission", lambda: "granted")
    tab.cam_check.setChecked(True)
    assert started == ["iphone-id"]                                       # starts the chosen device


def test_analyse_frame_on_rendered_head(qapp):
    cv2 = pytest.importorskip("cv2")
    ok, why = cam.availability()
    if not ok: pytest.skip(why)
    from PySide6 import QtGui
    from extensions.head_motion_plus import HeadCanvas
    canvas = HeadCanvas(PoseTracker(52)); canvas.resize(640, 480)
    img = canvas.grab().toImage().scaledToWidth(cam.DETECT_WIDTH).convertToFormat(QtGui.QImage.Format_RGB888)
    w, h = img.width(), img.height()
    rgb = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h, w, 3)
    det = cv2.FaceDetectorYN.create(str(cam.MODEL), "", (w, h), 0.7)
    res, preview = cam.analyse_frame(det, rgb[:, :, ::-1].copy())
    assert res["face"] and res["facing"] and preview.shape == (h, w, 3)


# ---- H1–H5, H7–H12 (User_Analysis UX review) ---------------------------------------------------------
def _still(n=52):
    x = np.zeros((6, n)); x[2] = -1.0                 # gravity on z, no rotation
    return x


def _turn(n, axis, dps):
    x = _still(n); x[3 + axis] = dps
    return x


def test_steps_countdown_sound_and_progress(plus_tab):
    tab, _, w = plus_tab
    b = tab.step_buttons
    assert not any(x.isEnabled() for x in b.values()) and "Connect Athena" in b["neutral"].toolTip()
    tab.ext.on_imu(_still(), 1.0); tab.refresh_steps()
    assert b["neutral"].isEnabled() and not b["left"].isEnabled() and b["neutral"].font().bold()
    tab.begin_capture("neutral")
    assert tab.pending == "neutral" and "GO in 3" in tab.calibration_info.text() and b["neutral"].text().startswith("… ")
    for _ in range(3): tab._countdown_tick()
    assert tab.capture_kind == "neutral" and tab.ext.cues.played[-1] == "go"            # H1
    assert "GO — step 1: hold your head still" in tab.calibration_info.text()          # H4: no "neutral"
    tab.collect(_still(26))
    frac, left = tab.capture_progress()
    assert frac == pytest.approx(0.5) and left == pytest.approx(0.5)
    tab.on_frame(); assert not tab.progress.isHidden() and "Hold still · 0.5 s left" in tab.progress.format()
    tab.collect(_still(26))
    assert tab.ext.cues.played[-1] == "done" and b["neutral"].text().startswith("✓ ") and b["left"].isEnabled()
    tab.begin_capture("left"); tab._start_capture("left", tab.capture_generation)
    tab.collect(_still(80))                                                           # did not turn
    assert tab.ext.cues.played[-1] == "retry" and b["left"].text().startswith("✕ ")
    w.connected = False


def test_calibrate_all_runs_three_steps(plus_tab, monkeypatch):
    tab, _, w = plus_tab
    later = []
    monkeypatch.setattr(tab, "schedule", lambda ms, fn: later.append(fn))
    tab.ext.on_imu(_still(), 1.0); tab.refresh_steps()
    tab.all_btn.click()
    assert tab.pending == "neutral" and tab.queue == ["left", "up"] and tab.all_btn.text() == "■ Cancel"
    tab._start_capture("neutral", tab.capture_generation); tab.collect(_still(52))
    later.pop()()
    assert tab.pending == "left"
    tab._start_capture("left", tab.capture_generation); tab.collect(_turn(78, 1, 40.0))   # turn about one axis
    later.pop()()
    assert tab.pending == "up"
    tab._start_capture("up", tab.capture_generation); tab.collect(_turn(78, 0, 40.0))     # another axis
    assert tab.calibrated and tab.step_buttons["up"].text().startswith("✓ ") and not tab.busy()
    assert "Recenter (R)" in tab.calibration_info.text()


def test_keys_run_steps_and_r_recenters(plus_tab, monkeypatch):
    from PySide6 import QtCore, QtTest
    from musemonitor.ui import main_window as mw
    tab, _, w = plus_tab
    monkeypatch.setattr(mw.MainWindow, "isActiveWindow", lambda self: True)
    w.show(); w.stack.setCurrentIndex(mw.PAGE_RECORDING)
    w.panels.set_shown(w.panels.find(tab.title), True, select=True)
    started, centred = [], []
    monkeypatch.setattr(tab, "begin_capture", lambda kind: started.append(kind))
    monkeypatch.setattr(tab, "recenter", lambda: centred.append(1))
    tab.setFocus()
    for key in (QtCore.Qt.Key_1, QtCore.Qt.Key_3, QtCore.Qt.Key_R):
        QtTest.QTest.keyClick(tab, key)
    assert started == ["neutral", "up"] and centred == [1] and len(w.markers) == 0      # H2: no quick events
    QtTest.QTest.keyClick(tab, QtCore.Qt.Key_5)
    assert [e[1] for e in w.markers.events] == ["5"]                                   # unclaimed digit: event


def test_status_words_and_recenter_age(plus_tab, monkeypatch):
    import sys
    tab, _, w = plus_tab
    tab.update_texts()
    assert tab.status.text() == "<b>IMU:</b> waiting for Athena…"
    tab.ext.on_imu(_still(), 1.0); tab.update_texts()
    assert tab.status.text() == "<b>IMU:</b> stable" and "52 samples at 52 Hz" in tab.status.toolTip()
    assert tab.canvas.recenter_text() == "not recentered yet"
    tab.recenter()
    assert tab.canvas.recentered[1] == "manual" and tab.canvas.recenter_text() == "recentered just now (manual)"
    mod = sys.modules[type(tab).__module__]
    t0 = tab.canvas.recentered[0]
    assert tab.canvas.recenter_text(t0 + 140) == "recentered 2 min ago (manual)"   # 2.33 min (not 2.5: rounds either way)
    assert tab.canvas.flash_until > t0                                                 # "Recentered" label shown
    assert not tab.canvas.grab().toImage().isNull()


def test_mirror_view_reflects_the_model_not_the_angles(plus_tab):
    tab, _, w = plus_tab
    t = tab.ext.tracker
    t.q = np.array((math.cos(math.radians(10)), 0, math.sin(math.radians(10)), 0))      # turned left 20°
    mod = __import__("sys").modules[type(tab).__module__]
    assert round(mod.pose_angles(t.q)[0]) == 20
    face = lambda: (mod.MIRROR @ mod._rotation_matrix(t.q) @ mod.MIRROR if tab.canvas.mirror
                    else mod._rotation_matrix(t.q))[:, 2]
    assert tab.mirror.isChecked() and face()[0] < 0                                    # mirror: screen left
    tab.mirror.setChecked(False)
    assert face()[0] > 0 and tab.ext.app.setting("mirror_view") in (False, "false")    # facing you: screen right
    tab.update_texts()
    assert "turned 20° left" in tab.canvas.accessibleDescription()                     # angles = your head
    assert "roll + = tilted to the left" in tab.note.text()


def test_camera_on_mark_follows_theme_and_auto_recenter_hidden_when_off(plus_tab):
    from musemonitor.ui.theme import THEMES, contrast_ratio
    tab, _, w = plus_tab
    for name in ("Light", "Dark"):
        w.apply_theme(name)
        colour = THEMES[name]["q"]["Bad"]
        assert colour in tab.cam_live.styleSheet()
        assert contrast_ratio(colour, THEMES[name]["base"]) >= 4.5
    assert tab.cam_auto.isHidden()                                                      # camera off
    tab._camera_running(True)
    assert not tab.cam_auto.isHidden() and tab.cam_auto.isEnabled()
    tab.stop_camera("Camera off.")
    assert tab.cam_auto.isHidden()


def test_accessible_names(plus_tab):
    tab, _, w = plus_tab
    tab.ext.on_imu(_still(), 1.0); tab.update_texts(); tab.refresh_steps()
    assert tab.canvas.accessibleName() == "3D head pose" and "not recentered yet" in tab.canvas.accessibleDescription()
    assert tab.step_buttons["neutral"].accessibleName() == "Step 1, Hold still: not done"
    assert tab.recenter_button.accessibleName() == "Recenter head"
    assert tab.cam_preview.accessibleName() == "Camera preview (mirrored)"
    assert tab.status.accessibleName() == "IMU: stable"
