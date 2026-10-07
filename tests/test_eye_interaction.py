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
    assert "gaze: center (L 1 / R 0)" in tab.status.text()
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
