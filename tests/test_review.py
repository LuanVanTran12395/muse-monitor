"""Phase 1 of debate/claude-session-review-round-2.md: File ▸ New session / Open session, reader, session.json,
ReviewStore (time cursor, live display rule, gaps) and the review window. Synthetic data only."""
import csv
import json
import os
import time

import numpy as np
import pytest
from PySide6 import QtCore

import synthetic as S
from musemonitor.core.review import ReviewStore, display_time
from musemonitor.core.store import SignalStore
from musemonitor.device.profiles import DeviceProfile, athena_profile
from musemonitor.storage.events import EventWriter
from musemonitor.storage.reader import ReaderError, inspect, load, locate
from musemonitor.storage.recording import Recorder
from musemonitor.storage.session import RecordingSession
from musemonitor.ui import main_window as mw
from musemonitor.ui.review_window import GENERIC, ReviewWindow

T0 = 1.79e9


def host_ts(n, fs_true, start=T0, pkt=12, seed=0):
    """Host-receive timestamps: whole packets share the ts of their last sample (as measured on Athena)."""
    rng = np.random.default_rng(seed)
    true = start + np.arange(n) / fs_true
    ts = true.copy()
    for i in range(0, n, pkt):
        ts[i:i + pkt] = true[min(i + pkt, n) - 1] + 0.004 * rng.random()
    return ts


def write_session(spec, root, sec=40, events=((5.0, "0"), (20.0, "blink")), opt_delay=0.0, imu_gap=None,
                  meta=True, stamp="20261008_101500"):
    """A real RecordingSession folder (Recorder + EventWriter + report), optionally with a late optics
    start and an IMU gap. Returns (folder, data dict)."""
    sess = RecordingSession(spec, root=root, device="MuseS-TEST", stamp=stamp)
    if not meta: (sess.folder / "session.json").unlink()
    rec = Recorder(sess.eeg_path, spec)
    fs, ofs, ifs = spec.eeg.fs, spec.optics.fs, spec.imu.fs
    e, o, m = S.eeg(fs, sec), S.optics(ofs, sec), S.imu(ifs, sec)
    te = host_ts(e.shape[1], 256.87)
    to = T0 + opt_delay + np.arange(o.shape[1]) / ofs
    ti = T0 + np.arange(m.shape[1]) / ifs
    keep_o = to <= T0 + sec
    keep_i = np.ones(len(ti), bool)
    if imu_gap: keep_i &= ~((ti >= T0 + imu_gap[0]) & (ti < T0 + imu_gap[1]))
    seq_e = np.arange(e.shape[1]) // 12
    rec.write("eeg", te, e, seq_e)
    rec.write("optics", to[keep_o], o[:, keep_o], None)
    rec.write("imu", ti[keep_i], m[:, keep_i], np.arange(keep_i.sum()))
    rec.close()
    ev = EventWriter(sess.eeg_path)
    for dt, label in events: ev.write(T0 + dt, label); sess.add_event(T0 + dt, label)
    ev.close()
    sess.add("eeg", e)
    sess.finish({})
    return sess.folder, dict(eeg=(te, e), opt=(to[keep_o], o[:, keep_o]), imu=(ti[keep_i], m[:, keep_i]))


@pytest.fixture
def folder(spec, tmp_path):
    return write_session(spec, tmp_path)


# ---- session.json --------------------------------------------------------------------------------
def test_session_json_written_at_start_and_updated_at_stop(spec, tmp_path):
    sess = RecordingSession(spec, root=tmp_path, device="MuseS-X", profile_id="muse_athena")
    meta = json.loads((sess.folder / "session.json").read_text())
    assert meta["schema"] == 1 and meta["profile_id"] == "muse_athena" and meta["device_name"] == "MuseS-X"
    assert meta["stopped_unix"] is None
    assert meta["streams"]["eeg"] == dict(file=sess.eeg_path.name, fs=256, channels=["TP9", "AF7", "AF8", "TP10"],
                                          units=["uV"] * 4)
    assert meta["streams"]["imu"]["units"] == ["g"] * 3 + ["deg/s"] * 3
    Recorder(sess.eeg_path, spec).close(); sess.finish({})
    assert json.loads((sess.folder / "session.json").read_text())["stopped_unix"] is not None


def test_existing_folder_gets_no_session_json(spec, tmp_path):
    RecordingSession(spec, folder=tmp_path, stamp="20261008_000000")      # organize_data path
    assert not (tmp_path / "session.json").exists()


# ---- reader --------------------------------------------------------------------------------------
def test_locate_from_folder_csv_companion_or_json(folder):
    folder, _ = folder
    paths = [folder, folder / "session.json", next(folder.glob("muse_eeg_*_optics.csv")),
             next(f for f in folder.glob("muse_eeg_*.csv") if f.stem.count("_") == 3)]
    got = {(f.eeg, f.optics, f.imu, f.events) for f in map(locate, paths)}
    assert len(got) == 1 and all(p is not None for p in next(iter(got)))


def test_load_new_session_round_trip(spec, folder):
    folder, data = folder
    info = inspect(locate(folder), [athena_profile()])
    assert info.certainty == "certain" and info.profile.id == "muse_athena" and info.device_name == "MuseS-TEST"
    sess = load(info)
    for k in ("eeg", "opt", "imu"):
        ts, x = sess.streams[k]
        assert x.dtype == np.float32 and ts.dtype == np.float64
        assert np.array_equal(ts, data[k][0]) and np.allclose(x, data[k][1], atol=1e-3)
    assert [label for _, label in sess.events] == ["0", "blink"]


def test_old_flat_files_without_package_num(spec, tmp_path):
    """Pre-folder layout in data/, written before package_num existed."""
    fs = spec.eeg.fs
    e = S.eeg(fs, 20); ts = T0 + np.arange(e.shape[1]) / fs
    with open(tmp_path / "muse_eeg_20261006_182028.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["timestamp", "TP9", "AF7", "AF8", "TP10"]); w.writerows(np.column_stack([ts, e.T]))
    info = inspect(locate(tmp_path / "muse_eeg_20261006_182028.csv"), [athena_profile()])
    assert info.certainty == "certain" and info.files.optics is None
    assert any("only EEG" in w for w in info.warnings)
    sess = load(info)
    assert sess.streams["eeg"][1].shape == (4, e.shape[1]) and "opt" not in sess.streams


def test_bad_files_give_clear_errors(spec, tmp_path):
    (tmp_path / "muse_eeg_20261006_000000.csv").write_text("")
    with pytest.raises(ReaderError, match="empty"):
        inspect(locate(tmp_path / "muse_eeg_20261006_000000.csv"), [athena_profile()])
    (tmp_path / "muse_eeg_20261006_000001.csv").write_text("timestamp,TP9,AF7,AF8,TP10\n")
    info = inspect(locate(tmp_path / "muse_eeg_20261006_000001.csv"), [athena_profile()])
    with pytest.raises(ReaderError, match="no data"):
        load(info)
    with pytest.raises(ReaderError, match="not a Muse Monitor"):
        locate(tmp_path / "notes.csv") if (tmp_path / "notes.csv").write_text("x") else None
    with pytest.raises(ReaderError, match="No recording"):
        locate(tmp_path.joinpath("empty_dir").mkdir() or tmp_path / "empty_dir")


def test_missing_companion_and_unequal_lengths(spec, tmp_path):
    folder, _ = write_session(spec, tmp_path, opt_delay=3.0)
    next(folder.glob("*_imu.csv")).unlink()
    sess = load(inspect(locate(folder), [athena_profile()]))
    assert "imu" not in sess.streams
    assert sess.streams["opt"][1].shape[1] < sess.streams["eeg"][1].shape[1] / 4


def two_profiles(spec):
    twin = DeviceProfile(id="twin", name="Twin", make_spec=lambda: spec, make_worker=None, matches=lambda n: False)
    return [athena_profile(), twin]


def test_ambiguous_and_unknown_devices(spec, tmp_path):
    folder, _ = write_session(spec, tmp_path, meta=False)
    info = inspect(locate(folder), two_profiles(spec))
    assert info.certainty == "ambiguous" and {p.id for p in info.candidates} == {"muse_athena", "twin"}
    # unknown device: estimate rates from timestamps
    fs = 200
    x = S.eeg(fs, 15, n_ch=2); ts = T0 + np.arange(x.shape[1]) / fs
    with open(tmp_path / "muse_eeg_20261008_120000.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["timestamp", "Fp1", "Fp2"]); w.writerows(np.column_stack([ts, x.T]))
    info = inspect(locate(tmp_path / "muse_eeg_20261008_120000.csv"), [athena_profile()])
    assert info.certainty == "unknown"
    sess = load(info, profile=None)
    assert sess.fs_estimated and sess.rates["eeg"] == pytest.approx(200, rel=1e-3) and sess.spec is None


def test_estimating_a_too_short_stream_is_refused(tmp_path):
    x = np.zeros((2, 500)); ts = T0 + np.arange(500) / 100
    with open(tmp_path / "muse_eeg_20261008_120001.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["timestamp", "A", "B"]); w.writerows(np.column_stack([ts, x.T]))
    with pytest.raises(ReaderError, match="too short"):
        load(inspect(locate(tmp_path / "muse_eeg_20261008_120001.csv"), []))


def test_non_monotonic_timestamps_load(spec, tmp_path):
    folder, data = write_session(spec, tmp_path)
    sess = load(inspect(locate(folder), [athena_profile()]))
    ts = sess.streams["eeg"][0]
    assert (np.diff(ts) == 0).any()                       # many samples share one ts
    st = ReviewStore(spec, sess.streams, sess.events)
    assert np.all(np.diff(st.t_rel["eeg"]) >= 0)


# ---- ReviewStore ---------------------------------------------------------------------------------
@pytest.fixture
def review(spec, tmp_path):
    folder, data = write_session(spec, tmp_path, sec=60, opt_delay=7.0, imu_gap=(25.0, 29.0))
    sess = load(inspect(locate(folder), [athena_profile()]))
    return ReviewStore(spec, sess.streams, sess.events), data


def test_views_are_read_only_and_follow_the_cursor(review):
    st, data = review
    for t in (10.0, 45.0, 12.5, 59.0, 0.0):               # forward and back
        st.set_view_end(t)
        for k in ("eeg", "opt", "imu"):
            v, tr = st.views[k], st.t_rel[k]
            assert v.end == np.searchsorted(tr, st.view_end, "right")
            if v.end: assert np.array_equal(v.get(50), v.x[:, max(0, v.end - 50):v.end])
    st.set_view_end(30.0)
    with pytest.raises(ValueError):
        st.eeg.get(10)[0, 0] = 1.0


def test_three_streams_share_one_time_cursor(review):
    st, _ = review
    assert st.t_rel["opt"][0] == pytest.approx(7.0, abs=0.05)          # optics started 7 s late
    st.set_view_end(40.0)
    for k in ("eeg", "opt", "imu"):
        tr, end = st.t_rel[k], st.views[k].end
        assert tr[end - 1] <= 40.0 < (tr[end] if end < len(tr) else np.inf)


def test_gap_is_drawn_broken_not_bridged(review, spec):
    st, _ = review
    st.set_view_end(35.0)
    n = int(15 * spec.imu.fs)
    t = st.time_axis("imu", n)
    assert np.isnan(t).sum() == 1
    j = int(np.flatnonzero(np.isnan(t))[0])
    assert t[j - 1] < 25.1 and t[j + 1] > 28.9                          # 4 s hole, not compressed


def test_event_marker_lands_on_its_sample(review):
    st, _ = review
    for k in ("eeg", "opt", "imu"):
        j = len(st.ts[k]) // 2
        st.set_view_end(st.t_rel[k][j] + 5)
        t_event = st.t0 + st.t_rel[k][j]
        assert t_event - st.time_ref(k) == pytest.approx(st.t_rel[k][j], abs=1 / st.fs[k])


def test_display_time_matches_live_rule(spec):
    fs = spec.eeg.fs
    e = S.eeg(fs, 90); ts = host_ts(e.shape[1], 256.87)
    live = SignalStore(spec)
    for i in range(0, e.shape[1], 64): live.add_eeg(e[:, i:i + 64], ts[i:i + 64])
    st = ReviewStore(spec, {"eeg": (ts, e.astype(np.float32))})
    st.set_view_end(st.duration)
    n = 30 * fs
    a_live = live.time_axis("eeg", n) + live.time_ref("eeg") - st.t0
    assert np.nanmax(np.abs(a_live - st.time_axis("eeg", n))) < 1e-3     # block-wise fit, ≤ 1 ms
    assert np.allclose(live.eeg_display(n), st.eeg_display(n), atol=1e-3)


def test_filter_toggle_and_independent_stores(review, spec):
    st, data = review
    st.set_view_end(30.0)
    st.set_filter(notch=False, band=False)
    raw = st.eeg_display(256)
    assert np.allclose(raw.mean(axis=1), 0, atol=1e-3)                     # raw → DC removed only
    st.set_filter(notch=True, band=True)
    other = ReviewStore(spec, {"eeg": data["eeg"]})
    other.set_view_end(5.0)
    assert st.view_end == 30.0 and st.eeg.end != other.eeg.end


def test_display_time_splits_segments():
    ts = np.concatenate([T0 + np.arange(500) / 50, T0 + 20 + np.arange(500) / 50])
    t, gap = display_time(ts, 50)
    assert gap.sum() == 1 and t[500] - t[499] == pytest.approx(10.02, abs=0.01)


# ---- windows --------------------------------------------------------------------------------------
@pytest.fixture
def live(qapp, spec, settings, monkeypatch, tmp_path):
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path / "data"))
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[]); w.resize(1200, 860); w.show()
    yield w
    for r in list(ReviewWindow._open): r.close()
    w.connected = False; w.close()


def test_file_menu_has_new_open_close(live):
    titles = [a.text() for a in live.menuBar().actions()]
    assert titles == ["File", "Analysis", "HCI/BCI", "Extensions"]
    file_menu = live.menuBar().actions()[0].menu()
    assert [a.text() for a in file_menu.actions() if a.text()] == ["New session", "Open session…", "Close window"]


def test_open_session_review_window(live, spec, tmp_path, qapp):
    folder, _ = write_session(spec, tmp_path, sec=60)
    rw = live.open_session(str(folder))
    assert isinstance(rw, ReviewWindow) and rw in ReviewWindow._open and "Review" in rw.windowTitle()
    assert live.isVisible() and rw.isVisible()
    page = rw.page
    assert not page.record_btn.isVisible() and not page.disc_btn.isVisible()
    for theme in ("Light", "Dark"):
        rw.apply_theme(theme)
        for i in range(page.tabs.count()):
            page.tabs.setCurrentIndex(i); rw.refresh()
    T = rw.ctx.window_sec
    p = rw.ctx.plots.time_plots[0]
    rw.scroll.setValue(rw.scroll.maximum()); rw.refresh()
    lo, hi = p.getViewBox().viewRange()[0]
    assert hi == pytest.approx(rw.store.duration, abs=0.11) and hi - lo == pytest.approx(T)
    rw.scroll.setValue(0); rw.refresh()
    assert p.getViewBox().viewRange()[0][1] == pytest.approx(T)
    assert len(rw.markers) == 2 and rw.ev_list.count() == 2
    rw._jump_to_item(rw.ev_list.item(1))                                    # "blink" at 20 s
    rw.refresh()
    lo, hi = p.getViewBox().viewRange()[0]
    t_blink = T0 + 20 - rw.store.t0
    assert lo < t_blink < hi and abs((lo + hi) / 2 - t_blink) <= 0.11
    page.range_spin.setValue(5); rw.refresh()
    assert rw.scroll.pageStep() == 50
    assert live.ctx.store.eeg.n == 0                                        # live store untouched


def test_open_ambiguous_asks_and_generic(live, spec, tmp_path):
    folder, _ = write_session(spec, tmp_path, meta=False)
    live.profiles = two_profiles(spec)
    asked = []
    rw = live.open_session(str(folder), choose_profile=lambda parent, info, opts: asked.append(len(opts)) or opts[1])
    assert asked == [2] and rw.ctx.profile.id == "twin"
    assert live.open_session(str(folder), choose_profile=lambda *a: None) is None        # cancelled


def test_open_bad_path_shows_message(live, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(mw.QtWidgets.QMessageBox, "warning", lambda *a: shown.append(a[2]))
    assert live.open_session(str(tmp_path / "nope")) is None and "does not exist" in shown[0]


def test_review_new_session_closes_review_only(live, spec, tmp_path):
    folder, _ = write_session(spec, tmp_path)
    rw = live.open_session(str(folder))
    rw.new_session()
    assert rw not in ReviewWindow._open and live.isVisible()


# ---- New session in the live window ---------------------------------------------------------------
class FakeWorker:
    def __init__(self, window, late_chunk=None):
        self.w, self.late, self.calls = window, late_chunk, []
    def start_recording(self, path): self.calls.append("start"); Recorder(path, self.w.spec).close()
    def stop_recording(self): self.calls.append("stop")
    def request_stop(self):
        self.calls.append("request_stop")
        def finish():
            if self.late is not None: self.w.on_data(*self.late)       # queued before `stopped`
            self.w.on_stopped()
        QtCore.QTimer.singleShot(0, finish)


def feed(w, sec=10):
    fs = w.spec.eeg.fs
    e = S.eeg(fs, sec)
    for k in range(sec): w.on_data(e[:, k * fs:(k + 1) * fs], T0 + k + 1)


def wait_until(qapp, cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not cond(): qapp.processEvents(); time.sleep(0.005)
    return cond()


def assert_clean(w):
    assert w.ctx.store.eeg.n == 0 and len(w.markers) == 0
    assert w.stack.currentIndex() == mw.PAGE_CONNECT and not w._pending_new_session
    assert w.new_action.isEnabled() and w.open_action.isEnabled()


def test_new_session_idle(live):
    feed(live); live.add_event("x")
    live.new_session()
    assert_clean(live)


def test_new_session_while_recording_writes_report_and_drops_late_chunk(live, qapp, tmp_path):
    late = (S.eeg(256, 1), T0 + 99)
    live.worker = FakeWorker(live, late_chunk=late)
    live.connected = live.streaming = True
    feed(live)
    live.toggle_record()
    folder = live.session.folder
    live.new_session()
    assert not live.new_action.isEnabled()                                  # waiting for the worker
    assert wait_until(qapp, lambda: not live._pending_new_session)
    assert_clean(live)
    assert (folder / "report.html").exists() and not live.connected
    assert np.abs(live.ctx.store.eeg.get()).size == 0                       # the late chunk did not survive


def test_new_session_report_failure_still_resets(live, qapp, monkeypatch):
    live.worker = FakeWorker(live); live.connected = live.streaming = True
    feed(live); live.toggle_record()
    monkeypatch.setattr(RecordingSession, "finish", lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("disk")))
    live.new_session()
    assert wait_until(qapp, lambda: not live._pending_new_session)
    assert_clean(live)
    assert "report failed" in live.status and "New session" in live.status


def test_new_session_while_connecting_without_data(live, qapp):
    live.worker = FakeWorker(live); live.connected = True
    live.new_session()
    assert wait_until(qapp, lambda: not live._pending_new_session)
    assert_clean(live)


def test_new_session_waits_for_a_running_scan(live):
    class Scan:
        def wait(self, ms): return True
    feed(live)
    live.scan_thread = Scan()
    live.new_session()
    assert live._pending_new_session and live.ctx.store.eeg.n > 0
    live._on_scan_done()
    assert_clean(live)


# ---- memory (slow; run with MUSEMONITOR_SLOW=1) ---------------------------------------------------------
@pytest.mark.skipif(not os.environ.get("MUSEMONITOR_SLOW"), reason="slow: set MUSEMONITOR_SLOW=1")
def test_two_hour_session_memory(spec, tmp_path):
    import resource
    import tracemalloc
    sec = 7200
    folder, _ = write_session(spec, tmp_path, sec=sec, events=())
    tracemalloc.start()
    t = time.perf_counter()
    sess = load(inspect(locate(folder), [athena_profile()]))
    st = ReviewStore(spec, sess.streams, sess.events)
    load_s = time.perf_counter() - t
    cur, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    t = time.perf_counter()
    for v in np.linspace(0, sec, 200): st.set_view_end(v); st.eeg_display(30 * 256); st.time_axis("opt", 30 * 64)
    scroll_ms = (time.perf_counter() - t) / 200 * 1000
    print(f"\n2 h Athena: load {load_s:.1f} s · steady {cur / 1e6:.0f} MB · peak {peak / 1e6:.0f} MB · "
          f"cursor move {scroll_ms:.2f} ms · RSS max {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6:.0f} MB")
    assert peak <= 450e6 and load_s <= 15
