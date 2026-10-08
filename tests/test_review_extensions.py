"""Phase 2 of debate/claude-session-review-round-2.md: extensions in review windows (API 2), the replay
contract, side-effect limits, and the artifact_log extension (live, recording, review)."""
import csv
import importlib.util

import numpy as np
import pytest
from PySide6 import QtCore

import synthetic as S
from musemonitor.device.profiles import athena_profile
from musemonitor.plugins.api import API_VERSION, Extension
from musemonitor.plugins.loader import PROJECT_DIR
from musemonitor.plugins.replay import CHUNK_SEC, Replay
from musemonitor.storage.reader import inspect, load, locate
from musemonitor.ui import main_window as mw
from musemonitor.ui.review_window import ReviewWindow
from test_review import T0, write_session


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


AL = _module(PROJECT_DIR / "artifact_log" / "__init__.py", "artifact_log_under_test")

RECORDER = '''
from musemonitor.plugins.api import Extension

class Recorder(Extension):
    supports_review = {review}
    def activate(self, app):
        self.calls, self.views, self.app = [], [], app
        self.last_seen = {{}}
    def on_eeg(self, x, ts):
        self.calls.append(("eeg", x.shape[1], ts)); self.last_seen["eeg"] = self.app.store.last_ts["eeg"]
    def on_optics(self, x, ts): self.calls.append(("opt", x.shape[1], ts))
    def on_imu(self, x, ts): self.calls.append(("imu", x.shape[1], ts))
    def on_event(self, t, label): self.calls.append(("event", label, t))
    def on_view_changed(self, t_end): self.views.append(t_end)

EXTENSION = Recorder
'''


@pytest.fixture
def ext_dir(tmp_path):
    d = tmp_path / "exts"; d.mkdir()
    (d / "rec_review.py").write_text(RECORDER.format(review=True))
    (d / "rec_live_only.py").write_text(RECORDER.format(review=False))
    return d


@pytest.fixture
def session(spec, tmp_path):
    folder, data = write_session(spec, tmp_path / "s", sec=30, events=((5.0, "0"), (12.0, "blink")))
    return load(inspect(locate(folder), [athena_profile()])), data


def open_window(session, settings, dirs, replay=True):
    sess, _ = session
    return ReviewWindow(sess, settings, profile=athena_profile(), extension_dirs=[str(d) for d in dirs], replay=replay)


def rec_of(w, ext_id):
    return next(r for r in w.extensions.records if r.id == ext_id)


def finish(w):
    w.replay.run(); w._replay_finished()


# ---- API 2 ------------------------------------------------------------------------------------------
def test_api_version_and_compatibility(qapp, spec, settings, ext_dir, monkeypatch):
    assert API_VERSION >= 2 and Extension.supports_review is False
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    live = mw.MainWindow(spec, settings=settings, extension_dirs=[str(ext_dir)])
    st = {r.id: r.status for r in live.extensions.records}
    assert st == {"rec_review": "active", "rec_live_only": "active"}            # API-1 style extension: unchanged live
    live.close()


def test_only_review_capable_extensions_load_in_review(qapp, settings, session, ext_dir):
    w = open_window(session, settings, [ext_dir, PROJECT_DIR], replay=False)
    st = {r.id: r.status for r in w.extensions.records}
    assert st["rec_review"] == "active" and st["rec_live_only"] == "not applicable"
    assert "supports_review" in rec_of(w, "rec_live_only").error
    for ext_id in ("eye_interaction", "head_motion", "head_motion_plus"):
        assert st[ext_id] == "not applicable"
    for ext_id in ("hello_world", "band_power", "artifact_log"):
        assert st[ext_id] == "active"
    assert rec_of(w, "rec_review").instance.app.is_review
    w.close()


# ---- replay contract ----------------------------------------------------------------------------------
def test_replay_order_chunks_and_timestamps(qapp, settings, session, ext_dir):
    sess, data = session
    w = open_window(session, settings, [ext_dir], replay=False)
    w.start_replay(); finish(w)
    inst = rec_of(w, "rec_review").instance
    calls = inst.calls
    # every sample delivered exactly once, in chunks of ~0.1 s, with the raw ts of each chunk's last sample
    for key, fs in (("eeg", 256), ("opt", 64), ("imu", 52)):
        mine = [c for c in calls if c[0] == key]
        assert sum(c[1] for c in mine) == data[key][0].size
        assert max(c[1] for c in mine) == round(CHUNK_SEC * fs)
        ends = np.cumsum([c[1] for c in mine]) - 1
        assert np.array_equal([c[2] for c in mine], data[key][0][ends])
    # merged in time order across streams; events after the data up to their time
    st = w.store
    t_of = {"eeg": st.t_rel["eeg"], "opt": st.t_rel["opt"], "imu": st.t_rel["imu"]}
    seen, order_t = {k: 0 for k in t_of}, []
    for c in calls:
        if c[0] == "event": order_t.append(c[2] - st.t0); continue
        seen[c[0]] += c[1]; order_t.append(t_of[c[0]][seen[c[0]] - 1])
    assert np.all(np.diff(order_t) >= -1e-9)
    assert [c[1] for c in calls if c[0] == "event"] == ["0", "blink"]
    # app.store during a hook = what had arrived by then
    assert inst.last_seen["eeg"] == data["eeg"][0][-1]
    w.close()


def test_replay_does_not_move_the_view_and_view_changes_follow(qapp, settings, session, ext_dir):
    w = open_window(session, settings, [ext_dir], replay=False)
    w.go_to(20.0); w.refresh()
    before = w.store.view_end
    w.start_replay()
    assert w.replaying and w.extension_store is not w.store
    w.replay.step(0.001)
    w.go_to(25.0); w.refresh()                                    # user scrolls during the replay
    assert w.store.view_end == pytest.approx(25.0, abs=0.11) and before != w.store.view_end
    finish(w)
    inst = rec_of(w, "rec_review").instance
    assert not w.replaying and w.extension_store is None
    assert inst.views and inst.views[-1] == pytest.approx(w.store.t0 + w.store.view_end)
    w.go_to(10.0); w.refresh()
    assert inst.views[-1] == pytest.approx(w.store.t0 + 10.0, abs=0.11)
    w.close()


def test_timer_driven_replay_finishes_and_close_cancels(qapp, settings, session, ext_dir):
    w = open_window(session, settings, [ext_dir])
    assert w.replaying
    deadline = QtCore.QDeadlineTimer(5000)
    while w.replaying and not deadline.hasExpired(): qapp.processEvents()
    assert not w.replaying and rec_of(w, "rec_review").instance.views
    w2 = open_window(session, settings, [ext_dir])
    inst = rec_of(w2, "rec_review").instance
    w2.close()
    n = len(inst.calls)
    for _ in range(20): qapp.processEvents()
    assert not w2.replaying and len(inst.calls) == n                           # cancelled on close
    w.close()


def test_side_effects_are_contained(qapp, settings, session, ext_dir):
    sess, _ = session
    folder = sess.info.files.folder
    files_before = sorted(p.name for p in folder.iterdir())
    w = open_window(session, settings, [ext_dir, PROJECT_DIR], replay=False)
    w.start_replay(); finish(w)
    app = rec_of(w, "rec_review").instance.app
    n_list = w.ev_list.count()
    app.mark_event("note")
    assert len(w.markers) == 3 and w.ev_list.count() == n_list + 1 and "temporary" in w.ev_list.item(n_list).text()
    app.set_setting("x", 5)
    assert app.setting("x") == 5 and settings.value("extensions/rec_review/x") is None
    hello = rec_of(w, "hello_world").instance
    hello.say_hi()
    assert settings.value("extensions/hello_world/greetings") is None
    w.close()
    assert sorted(p.name for p in folder.iterdir()) == files_before                # nothing written next to it


def test_band_power_keeps_the_whole_session_and_follows_the_view(qapp, settings, spec, tmp_path):
    folder, _ = write_session(spec, tmp_path / "long", sec=1200, events=())        # 20 min > live HISTORY (900)
    sess = load(inspect(locate(folder), [athena_profile()]))
    w = ReviewWindow(sess, settings, profile=athena_profile(), extension_dirs=[str(PROJECT_DIR)], replay=False)
    w.start_replay(); finish(w)
    bp = rec_of(w, "band_power").instance
    assert len(bp.history) > 1100                                                   # not capped at 900
    tab = next(t for t in w.page.tab_list if t.owner == "band_power")
    w.page.tabs.setCurrentWidget(tab); w.show()
    w.go_to(300.0); w.refresh()
    x, _ = tab.curves["alpha"].getData()
    assert x.max() <= w.store.view_end + 1e-6 and x.max() > w.store.view_end - 2
    w.close()


# ---- artifact_log: detector ----------------------------------------------------------------------------
FS, NAMES = 256, ["TP9", "AF7", "AF8", "TP10"]
START = 2 * FS                                    # epoch analysed = samples [2 s, 3 s) of a 4 s window


def clean(sec=4, seed=0, noise=3.0):
    rng = np.random.default_rng(seed); t = np.arange(sec * FS) / FS
    return t, np.vstack([20 * np.sin(2 * np.pi * 10 * t + k) + noise * rng.standard_normal(t.size) for k in range(4)])


def bump(t, at, amp=150.0, sd=0.09):
    return amp * np.exp(-0.5 * ((t - at) / sd) ** 2)


def found(x, gyro=None, th=None):
    return AL.detect_epoch(x, FS, NAMES, START, gyro, th)


def kinds(res):
    return {(ch, k) for ch, k, *_ in res}


def test_clean_epoch_has_no_artifacts():
    _, x = clean()
    assert found(x) == []


def test_blink_is_marked_where_it_happens():
    t, x = clean(); b = bump(t, 2.5); x[1] += b; x[2] += b
    res = [r for r in found(x) if r[1] == "blink"]
    assert {r[0] for r in res} == {"AF7", "AF8"}
    ch, kind, value, thr, off, dur = res[0]
    assert 0.1 < dur < 0.5 and off < 0.5 < off + dur                   # an interval around 2.5 s, not the whole second
    assert value == pytest.approx(150, rel=0.25)


def test_negative_blink_and_noisy_background():
    t, x = clean(noise=25.0); b = bump(t, 2.4, amp=-160); x[1] += b; x[2] += b
    assert ("AF7", "blink") in kinds(found(x))                        # polarity and noise do not hide it


def test_blink_across_epoch_boundary_counted_once():
    t, x = clean(); b = bump(t, 3.0); x[1] += b; x[2] += b            # peak on the boundary of epochs [2,3) and [3,4)
    first = [r for r in AL.detect_epoch(x, FS, NAMES, START) if r[1] == "blink"]
    second = [r for r in AL.detect_epoch(x, FS, NAMES, START + FS) if r[1] == "blink"]
    assert len(first) + len(second) == 2                                 # one blink on AF7 + AF8, in one epoch only


def test_saccade_and_slow_drift_are_not_blinks():
    t, x = clean()
    s = 150 * np.tanh((t - 2.5) / 0.03)                                 # glance: AF7 and AF8 move opposite ways
    sac = x.copy(); sac[1] += s; sac[2] -= s
    assert not any(k == "blink" for _, k, *_ in found(sac))
    drift = x.copy(); d = 200 * np.exp(-0.5 * ((t - 2.5) / 0.6) ** 2); drift[1] += d; drift[2] += d   # too wide
    assert not any(k == "blink" for _, k, *_ in found(drift))
    one = x.copy(); one[1] += bump(t, 2.5)                              # one side only
    assert not any(k == "blink" for _, k, *_ in found(one))


def test_other_rules():
    from scipy.signal import sosfiltfilt
    from musemonitor.core.filters import bandpass_sos
    t, x = clean()
    e = x.copy(); e[0, START:START + FS] += sosfiltfilt(bandpass_sos(FS, 30, 45), 60 * np.random.default_rng(1).standard_normal(FS))
    assert ("TP9", "emg") in kinds(found(e))
    f = x.copy(); f[3, START:START + FS] = 5.0
    assert ("TP10", "flat") in kinds(found(f))
    a = x.copy(); a[0, START + FS // 2:START + FS] += 400
    assert ("TP9", "amplitude") in kinds(found(a))
    gyro = np.zeros((3, 52)); gyro[1, 20] = 50
    assert (AL.HEAD, "motion") in kinds(found(x, gyro))
    b = x.copy(); bb = bump(t, 2.5); b[1] += bb; b[2] += bb
    assert found(b, th={"blink_uv": 500}) == []                          # thresholds are settings


def test_no_frontal_pair_means_no_blink_rule():
    assert AL.frontal_pair(["TP9", "TP10"]) is None and AL.frontal_pair(["Fp1", "Fp2"]) == (0, 1)


# ---- artifact_log: live + recording + review consistency -------------------------------------------------
def blinky_eeg(sec, at=(4.5, 11.5)):
    e = S.eeg(FS, sec)
    t = np.arange(e.shape[1]) / FS
    for tb in at:
        e[1:3] += bump(t, tb)
    return e


def blink_centres(ext, t0):
    return sorted({round(r[0] + r[1] / 2 - t0, 1) for r in ext.records if r[3] == "blink"})


def test_artifact_log_live_and_recording_csv(qapp, spec, settings, monkeypatch, tmp_path):
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path / "data"))
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(PROJECT_DIR)])
    ext = rec_of(w, "artifact_log").instance
    from test_review import FakeWorker
    w.worker = FakeWorker(w); w.connected = w.streaming = True
    w.toggle_record()
    path = w.rec_path
    e = blinky_eeg(16)
    for k in range(0, e.shape[1], 64): w.on_data(e[:, k:k + 64], T0 + (k + 64) / FS)
    w.toggle_record()
    assert blink_centres(ext, T0) == [4.5, 11.5]                              # at the blink, not the epoch
    with open(str(path).replace(".csv", "_artifacts.csv")) as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["timestamp_start", "duration_s", "channel", "kind", "value", "threshold", "unit"]
    blink_rows = [r for r in rows[1:] if r[3] == "blink"]
    assert {r[2] for r in blink_rows} == {"AF7", "AF8"} and all(float(r[1]) < 0.5 for r in blink_rows)
    assert ext.epochs == 15                                                   # the newest second waits for the next
    w.panels.find("Artifacts").action.trigger(); w.show()
    tab = next(t for t in w.rec_page.tab_list if t.owner == "artifact_log")
    w.stack.setCurrentIndex(mw.PAGE_RECORDING); w.rec_page.range_spin.setValue(16); w.update_analysis()
    x, y = tab.bcurve.getData()
    assert len(x) > 0 and tab.bmarks.data.size == 2                           # detector trace + 2 accepted blinks
    xs, _ = tab.traces[1].getData()
    assert len(xs) > 0                                                        # EEG trace drawn in the AF7 row
    w.connected = False; w.close()


def test_artifact_log_review_matches_live(qapp, spec, settings, tmp_path):
    e = blinky_eeg(16)
    folder, _ = write_session(spec, tmp_path / "rv", sec=16, events=())
    eeg = next(f for f in folder.glob("muse_eeg_*.csv") if f.stem.count("_") == 3)
    rows = list(csv.reader(open(eeg)))
    head, body = rows[0], rows[1:]
    with open(eeg, "w", newline="") as f:
        wr = csv.writer(f); wr.writerow(head)
        for i, r in enumerate(body): wr.writerow([r[0], *e[:, i], r[-1]])
    sess = load(inspect(locate(folder), [athena_profile()]))
    w = ReviewWindow(sess, settings, profile=athena_profile(), extension_dirs=[str(PROJECT_DIR)], replay=False)
    w.start_replay(); finish(w)
    ext = rec_of(w, "artifact_log").instance
    assert blink_centres(ext, w.store.ts["eeg"][0]) == pytest.approx([4.5, 11.5], abs=0.1)   # host timestamps (256.87 Hz)
    tab = next(t for t in w.page.tab_list if t.owner == "artifact_log")
    w.panels.find("Artifacts").action.trigger(); w.show()
    w.center_on(11.5); w.refresh()
    assert "blink 1" in tab.info.text() and "Whole recording" in tab.info.text()
    w.close()
