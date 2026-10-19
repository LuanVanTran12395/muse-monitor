"""Synthetic checks for the experimental ocular EEG extension."""

import numpy as np

from extensions.eye_interaction import EyeEstimator, relative_alpha


FS = 256
NAMES = ["TP9", "AF7", "AF8", "TP10"]


def _eeg(seconds, alpha_amplitude=2.0, blink_times=()):
    t = np.arange(int(seconds * FS)) / FS
    theta = 5 * np.sin(2 * np.pi * 6 * t)
    alpha = alpha_amplitude * np.sin(2 * np.pi * 11 * t)
    front = 2 * np.sin(2 * np.pi * 7 * t)
    for center in blink_times:
        front = front + 130 * np.exp(-0.5 * ((t - center) / 0.045) ** 2)
    return np.vstack((theta + alpha, front, 0.9 * front,
                      1.1 * theta + alpha))


def test_closed_eye_alpha_rises_in_synthetic_posterior_eeg():
    opened = _eeg(5, alpha_amplitude=2)
    closed = _eeg(5, alpha_amplitude=12)
    open_ratio = relative_alpha(opened[[0, 3]], FS)
    closed_ratio = relative_alpha(closed[[0, 3]], FS)
    assert closed_ratio > open_ratio * 1.25 + 0.025


def test_blinks_need_calibration_and_are_detected_once():
    detector = EyeEstimator(FS, NAMES)
    open_filtered, blink = detector.feed(_eeg(5), detect=False)
    assert not blink
    detector.calibrate_open(open_filtered)
    calibrated, _ = detector.feed(_eeg(4, blink_times=(0.8, 1.9, 3.0)), detect=False)
    assert detector.calibrate_blinks(calibrated)
    hits = 0
    new = _eeg(2, blink_times=(0.8,))
    for i in range(0, new.shape[1], 16):
        _, blink = detector.feed(new[:, i:i+16])
        hits += blink
    assert hits == 1


# ---- detection plots inside the app window -----------------------------------------------
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def test_detection_plots_mark_blinks_and_closure(qapp, spec, settings, monkeypatch):
    from musemonitor.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(REPO / "extensions")])
    ext = next(r for r in w.extensions.records if r.id == "eye_interaction").instance
    tab = ext.tab
    clock = {"t": 1000.0}
    monkeypatch.setattr(__import__("time"), "monotonic", lambda: clock["t"])
    # calibration (same synthetic signals as the estimator tests)
    open_f, _ = ext.estimator.feed(_eeg(5), detect=False); ext.estimator.calibrate_open(open_f)
    cal, _ = ext.estimator.feed(_eeg(4, blink_times=(0.8, 1.9, 3.0)), detect=False)
    assert ext.estimator.calibrate_blinks(cal)
    ext.open_alpha = relative_alpha(_eeg(5)[[0, 3]], FS)
    ext.closed_alpha = relative_alpha(_eeg(5, alpha_amplitude=12)[[0, 3]], FS)
    ext.alpha_enabled, ext.alpha_threshold = True, (ext.open_alpha + ext.closed_alpha) / 2

    T0, n = 1.79e9, [0]

    def stream(x, chunk=32):
        for i in range(0, x.shape[1], chunk):
            part = x[:, i:i + chunk]
            ts = T0 + (n[0] + np.arange(part.shape[1])) / FS
            n[0] += part.shape[1]; clock["t"] += part.shape[1] / FS
            w.on_data(part, ts)

    stream(_eeg(6, blink_times=(1.0, 3.0)))                       # eyes open, two blinks
    stream(_eeg(10, alpha_amplitude=12))                          # eyes closed from t = 6 s
    blink_t = [b[0] - T0 for b in ext.blinks]
    assert len(blink_t) == 2 and abs(blink_t[0] - 1.0) < 0.1 and abs(blink_t[1] - 3.0) < 0.1
    assert len(ext.closed_periods) == 1 and 6.0 < ext.closed_periods[0][0] - T0 < 12.0
    assert ext.closed and len(ext.alpha_series) > 20

    tab.refresh_plots()
    ref = w.ctx.store.time_ref("eeg")
    xs, _ = tab.blink_marks.getData()
    assert len(xs) == 2 and xs[0] == pytest.approx(ext.blinks[0][0] - ref)
    assert tab.blink_thr.isVisible() and tab.alpha_thr.isVisible()
    assert len(tab.alpha_curve.getData()[0]) == len(ext.alpha_series)
    region, line = tab.closed_regions[0], tab.closed_lines[0]
    assert line.isVisible() and line.value() == pytest.approx(ext.closed_periods[0][0] - ref)
    assert region.getRegion()[1] == pytest.approx(w.ctx.store.last_ts["eeg"] - ref)   # still closed
    w.close()


# ---- left / right glances (AF7 − AF8 horizontal EOG proxy) ---------------------------------
from extensions.eye_interaction import GazeEstimator


def _eeg_gaze(seconds, glances=(), blink_times=(), amp=60.0):
    """glances: (start, end, 'L'|'R'). Looking LEFT raises AF7 and lowers AF8 (opposite for right)."""
    x = _eeg(seconds, blink_times=blink_times)
    t = np.arange(x.shape[1]) / FS
    for start, end, d in glances:
        step = amp * ((t >= start) & (t < end)) * (1 if d == "L" else -1)
        x[1] += step; x[2] -= step
    return x


def _calibrated_gaze():
    g = GazeEstimator(FS, NAMES)
    h, _ = g.feed(_eeg(5), detect=False); g.calibrate_noise(h[FS:])
    hl, _ = g.feed(_eeg_gaze(4, [(1.0, 2.2, "L")]), detect=False)
    hr, _ = g.feed(_eeg_gaze(4, [(1.0, 2.2, "R")]), detect=False)
    ok, why = g.calibrate(hl, hr)
    assert ok, why
    return g


def test_glances_left_right_and_blink_is_not_a_glance():
    g = _calibrated_gaze()
    x = _eeg_gaze(9, [(1.0, 2.2, "L"), (4.0, 5.2, "R")], blink_times=(7.0,))
    events = []
    for i in range(0, x.shape[1], 16):
        _, ev = g.feed(x[:, i:i + 16])
        if ev: events.append((round(g.last_event_index / FS - 13, 1), ev))   # 13 s fed before
    assert [e for _, e in events] == ["left", "center", "right", "center"], events
    assert abs(events[0][0] - 1.0) < 0.3 and abs(events[2][0] - 4.0) < 0.3
    assert all(abs(t - 7.0) > 0.5 for t, _ in events)                       # blink ignored


def test_gaze_returns_to_center_after_timeout_and_rejects_same_direction_calibration():
    g = _calibrated_gaze()
    x = _eeg_gaze(9, [(1.0, 9.0, "L")])                                       # look left and stay
    states = []
    for i in range(0, x.shape[1], 16):
        g.feed(x[:, i:i + 16]); states.append(g.state)
    assert "left" in states and states[-1] == "center"                       # no return transient → timeout
    g2 = GazeEstimator(FS, NAMES)
    h, _ = g2.feed(_eeg(5), detect=False); g2.calibrate_noise(h[FS:])
    hl, _ = g2.feed(_eeg_gaze(4, [(1.0, 2.2, "L")]), detect=False)
    hl2, _ = g2.feed(_eeg_gaze(4, [(1.0, 2.2, "L")]), detect=False)
    ok, why = g2.calibrate(hl, hl2)
    assert not ok and "same" in why


def test_glances_in_app_plot_and_avatar(qapp, spec, settings, monkeypatch):
    from musemonitor.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(REPO / "extensions")])
    ext = next(r for r in w.extensions.records if r.id == "eye_interaction").instance
    tab = ext.tab
    clock = {"t": 1000.0}
    monkeypatch.setattr(__import__("time"), "monotonic", lambda: clock["t"])
    g = ext.gaze
    h, _ = g.feed(_eeg(5), detect=False); g.calibrate_noise(h[FS:])
    hl, _ = g.feed(_eeg_gaze(4, [(1.0, 2.2, "L")]), detect=False)
    hr, _ = g.feed(_eeg_gaze(4, [(1.0, 2.2, "R")]), detect=False)
    assert g.calibrate(hl, hr)[0]
    T0, n = 1.79e9, [0]

    def stream(x):
        for i in range(0, x.shape[1], 32):
            part = x[:, i:i + 32]
            ts = T0 + (n[0] + np.arange(part.shape[1])) / FS
            n[0] += part.shape[1]; clock["t"] += part.shape[1] / FS
            w.on_data(part, ts)
            tab.canvas.advance()

    stream(_eeg_gaze(1.8, [(1.0, 9.0, "L")]))                        # now looking left
    assert ext.gaze_state == "left" and tab.canvas.gaze < -0.5      # mirror view: pupils to screen left
    stream(_eeg_gaze(3, [(0.0, 0.4, "L")]))                          # back to centre at 0.4 s
    assert ext.gaze_state == "center"
    kinds = [k for _, k, _ in ext.glances]
    assert kinds == ["left", "center"] and ext.glance_count == {"left": 1, "right": 0}
    tab.refresh_plots()
    assert len(tab.gaze_marks.data) == 2 and all(line.isVisible() for line in tab.gaze_thr)
    tab.update_texts()
    assert "<b>Gaze:</b> center · left 1 · right 0" == tab.gaze_chip.text()
    w.close()


def test_glances_do_not_count_as_blinks():
    est = EyeEstimator(FS, NAMES)
    f, _ = est.feed(_eeg(5), detect=False); est.calibrate_open(f)
    cal, _ = est.feed(_eeg(4, blink_times=(0.8, 1.9, 3.0)), detect=False)
    assert est.calibrate_blinks(cal)
    x = _eeg_gaze(8, [(1.0, 2.2, "L"), (4.0, 5.2, "R")])
    blinks = 0
    for i in range(0, x.shape[1], 16):
        blinks += est.feed(x[:, i:i + 16])[1]
    assert blinks == 0


def test_quick_look_and_back_and_return_with_blink_are_detected():
    """Real Athena data showed returns 0.25–0.4 s after the glance being missed (refractory window,
    blink at the return). Each glance must give exactly one out + one back, in order."""
    g = _calibrated_gaze()
    plan = [(1.0, 1.25, "L"), (3.0, 3.30, "R"), (5.0, 5.40, "L"), (7.0, 7.35, "R")]
    x = _eeg_gaze(9.5, plan, blink_times=(5.42,))
    start = g.sample_count
    events = []
    for i in range(0, x.shape[1], 16):
        _, ev = g.feed(x[:, i:i + 16])
        if ev: events.append(((g.last_event_index - start) / FS, ev))
    assert [e for _, e in events] == ["left", "center", "right", "center"] * 2, events
    expected = [1.0, 1.25, 3.0, 3.30, 5.0, 5.40, 7.0, 7.35]
    assert all(0 <= t - want < 0.12 for (t, _), want in zip(events, expected)), events



def test_long_hold_then_return_is_back_to_center_not_opposite_glance():
    """Holding a side longer than RETURN_SEC (or a missed return) must not turn the eventual return
    into a glance to the other side."""
    for d, hold in (("L", 4.0), ("R", 9.0)):
        g = _calibrated_gaze(); start = g.sample_count; ev = []
        x = _eeg_gaze(13, [(1.0, 1.0 + hold, d)])
        for i in range(0, x.shape[1], 12):
            _, e = g.feed(x[:, i:i + 12])
            if e: ev.append(e)
        assert ev == ["left" if d == "L" else "right", "center"], (d, hold, ev)


# ---- E1 sound cues, E2 keys 1–5 run the calibration steps -------------------------------------------
def _eye_window(qapp, spec, settings, monkeypatch):
    from musemonitor.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    monkeypatch.setattr(mw.MainWindow, "isActiveWindow", lambda self: True)
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(REPO / "extensions")])
    w.resize(1200, 800); w.show()
    ext = next(r for r in w.extensions.records if r.id == "eye_interaction").instance
    return w, ext


def test_cue_tones_are_short_clean_wav(tmp_path):
    import wave
    from musemonitor.plugins.cues import TONES, tone_samples, write_wav
    for name, parts in TONES.items():
        y = tone_samples(parts)
        assert y.dtype.str == "<i2" and np.abs(y).max() <= 0.5 * 32767 + 1    # half scale: no clipping
        assert abs(int(y[0])) < 200 and abs(int(y[-1])) < 200                  # faded: no click
        write_wav(tmp_path / f"{name}.wav", y)
        with wave.open(str(tmp_path / f"{name}.wav")) as f:
            assert f.getframerate() == 44100 and f.getnframes() == len(y)
            assert 0.1 < f.getnframes() / 44100 < 0.6


def test_go_and_end_of_capture_are_heard(qapp, spec, settings, monkeypatch):
    w, ext = _eye_window(qapp, spec, settings, monkeypatch)
    tab = ext.tab
    ext.samples_seen = 1
    tab._start("open", tab.generation)
    assert ext.cues.played[-1] == "go"
    fs = ext.estimator.fs
    ext.capture_raw = [_eeg(5)]; ext.capture_filtered = [_eeg(5)]; ext.capture_h = [np.zeros(5 * fs)]
    ext._finish_capture()
    assert ext.cues.played[-1] == "done" and ext.open_alpha is not None
    tab._start("closed", tab.generation)
    bad = np.full((4, 5 * fs), np.nan)                         # unusable posterior EEG → repeat the step
    ext.capture_raw = [bad]; ext.capture_filtered = [bad]; ext.capture_h = [np.zeros(5 * fs)]
    ext._finish_capture()
    assert ext.cues.played[-2:] == ["go", "retry"] and "Repeat" in tab.info.text()
    w.close()


def test_sound_cues_can_be_turned_off_and_are_remembered(qapp, spec, settings, monkeypatch):
    w, ext = _eye_window(qapp, spec, settings, monkeypatch)
    assert ext.tab.sound.isChecked()
    ext.tab.sound.setChecked(False)
    n = len(ext.cues.played)
    ext.cues.play("go")
    assert len(ext.cues.played) == n                           # silent
    w.close()
    w2, ext2 = _eye_window(qapp, spec, settings, monkeypatch)
    assert not ext2.cues.enabled and not ext2.tab.sound.isChecked()
    w2.close()


def test_keys_1_to_5_run_steps_not_quick_events(qapp, spec, settings, monkeypatch):
    from PySide6 import QtCore, QtTest
    from musemonitor.ui import main_window as mw
    w, ext = _eye_window(qapp, spec, settings, monkeypatch)
    w.stack.setCurrentIndex(mw.PAGE_RECORDING)
    panel = w.panels.find(ext.tab.title); w.panels.set_shown(panel, True, select=True)
    started = []
    monkeypatch.setattr(ext.tab, "begin", lambda kind: started.append(kind))
    ext.tab.setFocus()
    for key in (QtCore.Qt.Key_1, QtCore.Qt.Key_2, QtCore.Qt.Key_5):
        QtTest.QTest.keyClick(ext.tab, key)
    assert started == ["open", "closed", "right"] and len(w.markers) == 0
    QtTest.QTest.keyClick(ext.tab, QtCore.Qt.Key_7)            # not a step: still a quick event
    assert [e[1] for e in w.markers.events] == ["7"]
    from PySide6 import QtWidgets
    b = ext.tab.findChildren(QtWidgets.QPushButton)[0]; b.setFocus()     # focus on a child (a button) works too
    QtTest.QTest.keyClick(b, QtCore.Qt.Key_3)
    assert started[-1] == "blink" and len(w.markers) == 1
    w.close()


# ---- E4 calibration progress, E5 labelled readouts, E7 closure estimate, E8 alpha axis --------------
def _finish(ext, kind, data):
    fs = ext.estimator.fs
    ext.capture_kind = kind
    ext.capture_raw = [data]; ext.capture_filtered = [data]; ext.capture_h = [np.zeros(data.shape[1])]
    ext._finish_capture()


def test_steps_show_state_and_unmet_steps_are_disabled(qapp, spec, settings, monkeypatch):
    w, ext = _eye_window(qapp, spec, settings, monkeypatch)
    tab, b = ext.tab, ext.tab.step_buttons
    assert not any(x.isEnabled() for x in b.values()) and not tab.all_btn.isEnabled()   # no EEG yet
    assert "Connect Athena" in b["open"].toolTip()
    ext.samples_seen = 1; tab.refresh_steps()
    assert b["open"].isEnabled() and not b["closed"].isEnabled() and not b["right"].isEnabled()
    assert b["open"].font().bold() and "Complete step 1" in b["closed"].toolTip()
    _finish(ext, "open", _eeg(5))
    assert b["open"].text().startswith("✓ ") and b["closed"].isEnabled() and b["left"].isEnabled()
    assert b["closed"].font().bold() and not b["open"].font().bold()                     # next required step
    _finish(ext, "closed", np.full((4, 5 * FS), np.nan))                                  # failed capture
    assert b["closed"].text().startswith("✕ ") and "repeated" in b["closed"].toolTip()
    _finish(ext, "closed", _eeg(5, alpha_amplitude=2))                                    # alpha unchanged
    assert b["closed"].text().startswith("⚠ ") and "did not change" in b["closed"].toolTip()
    w.close()


def test_countdown_then_go_and_progress(qapp, spec, settings, monkeypatch):
    from extensions.eye_interaction import COUNTDOWN_S
    w, ext = _eye_window(qapp, spec, settings, monkeypatch)
    tab = ext.tab; ext.samples_seen = 1
    tab.begin("open")
    assert tab.pending == "open" and "GO in 3" in tab.info.text() and tab.step_buttons["open"].text().startswith("… ")
    assert not tab.step_buttons["open"].isEnabled() and tab.all_btn.text() == "■ Cancel"     # busy
    for _ in range(COUNTDOWN_S - 1):
        tab._countdown_tick()
    assert "GO in 1" in tab.info.text() and ext.capture_kind is None
    tab._countdown_tick()
    assert ext.capture_kind == "open" and ext.cues.played[-1] == "go" and tab.step_buttons["open"].text().startswith("● ")
    ext.capture_raw = [np.zeros((4, 2 * FS))]
    frac, left = ext.capture_progress()
    assert frac == pytest.approx(0.4) and left == pytest.approx(3.0)
    tab.on_frame()
    assert not tab.progress.isHidden() and "Eyes open · 3.0 s left" in tab.progress.format()
    tab.cancel()
    assert ext.capture_kind is None and tab.progress.isHidden() and "cancelled" in tab.info.text()
    w.close()


def test_calibrate_all_runs_steps_1_to_3_and_stops_on_failure(qapp, spec, settings, monkeypatch):
    from PySide6 import QtCore
    w, ext = _eye_window(qapp, spec, settings, monkeypatch)
    tab = ext.tab; ext.samples_seen = 1
    later = []
    monkeypatch.setattr(tab, "schedule", lambda ms, fn: later.append(fn))       # not Qt's own singleShot
    tab.update_texts()                                       # EEG arrived → buttons refresh (2×/s in the app)
    tab.all_btn.click()
    assert tab.pending == "open" and tab.queue == ["closed", "blink"]
    tab._start("open", tab.generation); _finish(ext, "open", _eeg(5))
    later.pop()()                                            # the pause between steps elapses
    assert tab.pending == "closed" and tab.queue == ["blink"]
    tab._start("closed", tab.generation); _finish(ext, "closed", np.full((4, 5 * FS), np.nan))
    assert tab.queue == [] and later == [] and not tab.busy()            # failure ends the run
    tab.all_btn.click(); assert tab.busy()
    tab.all_btn.click()                                      # second click cancels
    assert not tab.busy() and tab.all_btn.text() == "▶ Calibrate 1–3"
    w.close()


def test_readouts_are_labelled_with_details_in_tooltips(qapp, spec, settings, monkeypatch):
    w, ext = _eye_window(qapp, spec, settings, monkeypatch)
    tab = ext.tab
    tab.update_texts()
    assert tab.eyes_chip.text() == "<b>Eyes:</b> waiting for EEG…"
    assert tab.blink_chip.text() == "<b>Blinks:</b> calibrate step 3" and "optional steps 4–5" in tab.gaze_chip.text()
    ext.samples_seen = 1; ext.last_alpha = 0.31
    tab.update_texts()
    assert "not calibrated yet (step 2)" in tab.eyes_chip.text() and "0.31" in tab.eyes_chip.toolTip()
    ext.open_alpha, ext.closed_alpha, ext.alpha_enabled = 0.2, 0.21, False
    tab.update_texts()
    assert "detection off" in tab.eyes_chip.text() and "alpha" not in tab.blink_chip.text()
    w.close()


def test_closure_estimate_shows_maybe_states_and_caption(qapp, spec, settings, monkeypatch):
    from extensions.eye_interaction import ESTIMATE_CAPTION
    w, ext = _eye_window(qapp, spec, settings, monkeypatch)
    tab = ext.tab
    assert ext.eye_estimate() == "open"                                  # not calibrated: always open
    ext.alpha_enabled, ext.alpha_threshold, ext.samples_seen = True, 0.4, 1
    ext.open_alpha, ext.closed_alpha = 0.2, 0.6
    ext.closed_votes = 1
    assert ext.eye_estimate() == "closing"
    for _ in range(30): tab.canvas.advance()
    assert tab.canvas.openness == pytest.approx(0.55, abs=0.02)          # half-open: "maybe"
    tab.update_texts(); assert "closing?" in tab.eyes_chip.text()
    ext.closed, ext.closed_votes, ext.open_votes = True, 0, 0
    assert ext.eye_estimate() == "closed"
    tab.update_texts(); assert "closed (estimated, a few s late)" in tab.eyes_chip.text()
    ext.open_votes = 1
    assert ext.eye_estimate() == "opening"
    tab.canvas.resize(500, 400)
    assert not tab.canvas.grab().toImage().isNull()                      # caption path paints
    assert set(ESTIMATE_CAPTION) == {"closed", "closing", "opening"}
    w.close()


def test_alpha_axis_is_fixed_0_to_1(qapp, spec, settings, monkeypatch):
    w, ext = _eye_window(qapp, spec, settings, monkeypatch)
    tab = ext.tab
    ext.alpha_series = [(1.79e9 + i, 0.835 + 0.0001 * i) for i in range(50)]
    w.ctx.store.last_ts["eeg"] = 1.79e9 + 50
    tab.refresh_plots()
    lo, hi = tab.alpha_plot.getViewBox().viewRange()[1]
    assert lo == pytest.approx(0) and hi == pytest.approx(1)              # small changes stay small
    w.close()


# ---- E11 mirror view, E13 panel rename, E14 accessibility -------------------------------------------
def test_mirror_view_flips_pupils_and_is_remembered(qapp, spec, settings, monkeypatch):
    w, ext = _eye_window(qapp, spec, settings, monkeypatch)
    tab = ext.tab
    assert ext.mirror and tab.mirror.isChecked()
    ext.gaze_state = "left"
    for _ in range(20): tab.canvas.advance()
    assert tab.canvas.gaze < -0.9                                   # mirror: your left → screen left
    tab.mirror.setChecked(False)
    for _ in range(20): tab.canvas.advance()
    assert tab.canvas.gaze > 0.9                                    # avatar view: its left → screen right
    assert tab.gaze_hint.textItem.toPlainText() == "↑ your left · ↓ your right"
    assert tab.gaze_hint.parentItem() is tab.gaze_plot.getViewBox()           # fixed corner, not data coords
    w.close()
    w2, ext2 = _eye_window(qapp, spec, settings, monkeypatch)
    assert not ext2.mirror and not ext2.tab.mirror.isChecked()
    w2.close()


def test_renamed_panel_keeps_the_users_tick(qapp, spec, settings, monkeypatch):
    from musemonitor.ui.panels import SEEN_KEY, SHOWN_KEY
    from extensions.eye_interaction import EyeTab
    old = EyeTab.OLD_TITLES[0]
    settings.setValue(SHOWN_KEY.format(kind="live", owner="eye_interaction", title=old), True)
    settings.setValue(SEEN_KEY.format(owner="eye_interaction", title=old), True)
    w, ext = _eye_window(qapp, spec, settings, monkeypatch)
    panel = w.panels.find("Eyes (experimental)")
    assert panel is not None and panel.shown                        # still ticked after the rename
    assert all(p.title != "Eyes (experimental)" for p in w.panels.new_panels)   # not announced as new
    assert w.panels.find(old) is None
    w.close()


def test_accessible_names_and_descriptions(qapp, spec, settings, monkeypatch):
    w, ext = _eye_window(qapp, spec, settings, monkeypatch)
    tab = ext.tab
    ext.samples_seen = 1; ext.blink_count = 4; ext.gaze_state = "right"
    tab.update_texts(); tab.refresh_steps()
    assert tab.canvas.accessibleName() == "Eye avatar"
    assert "looking right" in tab.canvas.accessibleDescription() and "4 blinks" in tab.canvas.accessibleDescription()
    assert "Blink threshold not calibrated" in tab.gfx.accessibleDescription()
    assert tab.eyes_chip.accessibleName().startswith("Eyes:") and "<b>" not in tab.eyes_chip.accessibleName()
    assert tab.step_buttons["open"].accessibleName() == "Step 1, Eyes open: not done"
    assert tab.progress.accessibleName() == "Calibration progress"
    tab.failed.add("blink"); tab.refresh_steps()
    assert tab.step_buttons["blink"].accessibleName() == "Step 3, Blink 3×: repeat this step"
    w.close()
