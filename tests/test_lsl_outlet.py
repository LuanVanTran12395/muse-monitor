"""Stage 3 of the LSL plan (debate/claude-lsl-athena-stage3-proposal.md + -round-2.md, Codex round 2):
the lsl_outlet extension — EEG + Markers + Quality outlets on a fake pylsl, driven by the stage 2 simulator.

Every sample of the simulated EEG carries its input index as its value (channel 0), so what an outlet
published can be mapped back to the timeline sample it came from."""
import importlib.util
import json
import sys

import numpy as np
import pytest

import fake_pylsl
import timeline_sim as TS
from musemonitor.plugins.loader import PROJECT_DIR
from musemonitor.ui import main_window as mw

LO = importlib.util.module_from_spec(importlib.util.spec_from_file_location(
    "lsl_outlet_under_test", PROJECT_DIR / "lsl_outlet" / "__init__.py"))
LO.__spec__.loader.exec_module(LO)

NAMES = ["TP9", "AF7", "AF8", "TP10"]
EEG, MARKERS, QUALITY = "MuseMonitor-Athena-EEG", "MuseMonitor-Athena-Markers", "MuseMonitor-Athena-Quality"
SEEDS = range(10)
SCENARIOS = {
    "clean": [],
    "lost_2s": [TS.Event("pause", 20.0, 2.0, "lost")],
    "late_0.5s": [TS.Event("pause", 20.0, 0.5, "late")],
    "drain_1.2": [TS.Event("pause", 20.0, 2.0, "late", drain=1.2)],
    "drain_1.01": [TS.Event("pause", 30.0, 2.0, "late", drain=1.01)],    # after period acquisition → backward rebases
    "clock_step": [TS.Event("clock_step", 25.013, -2.0)],
}


# ---- helpers ---------------------------------------------------------------------------------------------
class Run:
    """A simulated connection fed through LO.Monitor on a fake pylsl."""
    def __init__(self, seed, events=(), dur=60.0, max_drop_s=LO.MAX_REBASE_DROP_S, start=True):
        self.sim = TS.simulate(seed, dur, events=list(events))
        self.clocks = TS.FakeClocks(self.sim)
        self.lsl = fake_pylsl.make()
        self.lsl.local_clock = self.clocks.mono
        self.m = LO.Monitor(self.lsl, 256.0, NAMES, "musemonitor-athena-test", unix_clock=self.clocks.unix,
                            mono_clock=self.clocks.mono, max_drop_s=max_drop_s)
        self.next_chunk = 0
        if start: self.m.open()

    def feed(self, until=None, each=None):
        """Feed chunks up to mono time ``until`` (all if None)."""
        ch = self.sim.chunks
        while self.next_chunk < len(ch) and (until is None or ch[self.next_chunk][2] <= until):
            i0, i1, arr = ch[self.next_chunk]
            self.clocks.now = arr
            x = np.vstack([np.arange(i0, i1, dtype=float)] + [-np.arange(i0, i1, dtype=float)] * 3)
            self.m.push_eeg(x, self.sim.ts_unix[i0:i1])
            if each: each(self)
            self.next_chunk += 1
        return self

    def eeg(self):
        """(input index, timestamp) of every published EEG sample, over all EEG outlets."""
        idx, ts = [], []
        for name, kind, x, t in self.lsl.log:
            if name == EEG: idx.append(x[:, 0]); ts.append(t)
        cat = lambda v: np.concatenate(v) if v else np.empty(0)
        return cat(idx).astype(int), cat([np.array(t) for t in ts])

    def quality(self):
        return [(json.loads(x[0]), t[0]) for name, kind, x, t in self.lsl.log if name == QUALITY]


def per_sample_reason(timeline):
    out = [None] * timeline.n
    for a, b, r in timeline.uncertain:
        out[a:b] = [r] * (b - a)
    return out


def reconstruct(events, n):
    """Reason of every input index from open/state events, in emission order (None before the first open)."""
    out, cur, at = [None] * n, None, None
    def fill(upto):
        if at is not None: out[at:upto] = [cur] * (upto - at)
    for e, _ in events:
        if e["event"] in ("open", "status"):
            fill(e["next_input_index"]); cur, at = e["reason"], e["next_input_index"]
        elif e["event"] == "state":
            fill(e["input_sample_index"]); cur, at = e["reason"], e["input_sample_index"]
    fill(n)
    return out


# ---- T7: push_chunk ------------------------------------------------------------------------------------------
def test_push_chunk_per_sample_timestamps_and_values():
    r = Run(0, dur=30).feed()
    chunks = [(x, t) for name, kind, x, t in r.lsl.log if name == EEG]
    assert chunks and all(x.dtype == np.float32 and x.shape == (len(t), 4) for x, t in chunks)  # fake checks list/float
    idx, ts = r.eeg()
    assert np.array_equal(idx, np.arange(r.m.timeline.n))                     # clean: every sample, in order
    assert np.all(np.diff(ts) > 0)
    x0 = np.concatenate([x for x, _ in chunks])
    assert np.array_equal(x0[:, 1], -x0[:, 0])                                # channels kept apart


# ---- T18: the quality contract ----------------------------------------------------------------------------
@pytest.mark.parametrize("name", list(SCENARIOS))
@pytest.mark.parametrize("seed", SEEDS)
def test_quality_events_reproduce_the_timeline_flags(name, seed):
    dur = 300 if name == "drain_1.01" else 60
    r = Run(seed, SCENARIOS[name], dur=dur).feed()
    q = r.quality()
    assert q[0][0]["event"] == "open" and q[0][0]["inherited"] is False
    assert [e["seq"] for e, _ in q] == list(range(1, len(q) + 1))
    assert np.all(np.diff([t for _, t in q]) > 0)                             # Quality stream never goes back
    states = [e for e, _ in q if e["event"] == "state"]
    assert all(s["reason"] != s["prev"] for s in states)                      # one event per change, no repeats
    assert all(a["reason"] == b["prev"] for a, b in zip(states, states[1:]))
    tl = r.m.timeline
    assert reconstruct(q, tl.n) == per_sample_reason(tl)                     # by input index, not published ts
    idx, ts = r.eeg()
    pub = dict(zip(idx.tolist(), ts.tolist()))
    for s in states:                                                          # effective ts = published time or null
        assert s["effective_eeg_ts"] == pub.get(s["input_sample_index"])
    if name == "clean": assert not states
    if name in ("lost_2s", "drain_1.01"): assert tl.timing_uncertain is not None and states


def test_events_before_the_first_eeg_chunk():
    r = Run(1, dur=10)
    r.clocks.now = 0.001
    ts = r.m.marker(r.clocks.unix(), "early")                                 # marker before any EEG
    assert ts == pytest.approx(0.001, abs=1e-6)
    r.m.marker(r.clocks.unix() - 0.5, "older than any clock measurement")    # → flagged, not guessed
    r.m.close("stopped")                                                      # stop before any EEG
    q = r.quality()
    assert [e["event"] for e, _ in q] == ["open", "marker_uncertain", "close"]
    assert q[1][0]["label"].startswith("older")
    assert q[0][0]["next_input_index"] == 0 and q[0][0]["reason"] is None
    assert q[2][0]["eeg"] == dict(received=0, published=0, rebase_dropped=0, guard_dropped=0)


# ---- T19: rebase, drops, limit, watermark -------------------------------------------------------------------
def rebase_run(seed=3, **kw):
    return Run(seed, SCENARIOS["drain_1.01"], dur=300, **kw).feed()


def eeg_counters_hold(r):
    q = r.quality()
    t = r.m.totals
    assert t["timeline_samples"] == r.m.timeline.n
    assert t["timeline_samples"] == t["published"] + t["rebase_dropped"] + t["guard_dropped"] + t["monitored_while_eeg_off"]
    assert t["guard_dropped"] == 0 and not [e for e, _ in q if e["event"] == "guard_drop"]


def test_backward_rebase_drops_and_resumes():
    r = rebase_run()
    q = r.quality()
    rebases = [e for e, _ in q if e["event"] == "rebase"]
    resumes = [e for e, _ in q if e["event"] == "resume"]
    assert len(rebases) >= 2 and any(e["dropping"] for e in rebases)        # repeated rebases, at least one backward
    idx, ts = r.eeg()
    assert np.all(np.diff(ts) > 0)                                            # one outlet, strictly increasing
    missing = np.setdiff1d(np.arange(r.m.timeline.n), idx)
    assert len(missing) == r.m.totals["rebase_dropped"] == sum(e["dropped"] for e in resumes)
    chunk_sizes = [i1 - i0 for i0, i1, _ in r.sim.chunks]
    assert max(e["dropped"] for e in resumes) > max(chunk_sizes)              # whole chunks were dropped
    for e in resumes:                                                         # index mapping
        assert idx[e["first_published_index"]] == e["first_input_index"]
        assert ts[e["first_published_index"]] == e["first_published_eeg_ts"]
        assert e["first_input_index"] - e["dropped"] in [b["input_sample_index"] for b in rebases]
    eeg_counters_hold(r)
    r.m.close("stopped")
    c = r.quality()[-1][0]
    assert c["eeg"]["received"] == c["eeg"]["published"] + c["eeg"]["rebase_dropped"] + c["eeg"]["guard_dropped"]


def test_rebase_event_comes_in_the_detecting_chunk():
    r = Run(3, SCENARIOS["drain_1.01"], dur=300)
    seen = []
    def check(run):
        res_reb = run.m.timeline.rebases
        if res_reb and res_reb[-1].index >= run.m.timeline.n - (run.sim.chunks[run.next_chunk][1] - run.sim.chunks[run.next_chunk][0]):
            seen.append(res_reb[-1].index)
            last_q = [json.loads(x[0]) for name, k, x, t in run.lsl.log if name == QUALITY]
            assert any(e["event"] == "rebase" and e["input_sample_index"] == res_reb[-1].index for e in last_q)
    r.feed(each=check)
    assert seen


def test_drop_limit_closes_eeg_only_and_restart_keeps_the_watermark():
    r = Run(3, SCENARIOS["drain_1.01"], dur=300, max_drop_s=0.05)            # 13 samples: the first backward rebase exceeds it
    closed_at = []
    def watch(run):
        if not closed_at and run.m.bundle.eeg is None:
            closed_at.append(run.clocks.now)
    r.feed(each=watch)
    assert closed_at
    q = r.quality()
    ec = [e for e, _ in q if e["event"] == "eeg_closed"]
    assert len(ec) == 1 and ec[0]["code"] == "rebase_drop_limit"
    assert not [e for e, _ in q if e["event"] == "close"]                     # the bundle is still open
    n_eeg = sum(1 for name, *_ in r.lsl.log if name == EEG)
    assert r.m.marker(r.clocks.unix(), "after") is not None                   # Markers still running
    assert r.lsl.log[-1][0] == MARKERS
    assert sum(1 for name, *_ in r.lsl.log if name == EEG) == n_eeg
    eeg_counters_hold(r)


def test_restart_in_the_same_connection_never_goes_back():
    """Limit hit → stop/start in the same connection: the union of EEG outlets (same source_id) increases."""
    r = Run(3, SCENARIOS["drain_1.01"], dur=300, max_drop_s=0.05)
    restarts = []
    def restart(run):
        if run.m.bundle.eeg is None:
            run.m.close("stopped"); run.m.open(); restarts.append(run.clocks.now)
    r.feed(each=restart)
    assert restarts
    idx, ts = r.eeg()
    assert np.all(np.diff(ts) > 0)
    opens = [e for e, _ in r.quality() if e["event"] == "open"]
    assert len(opens) == 1 + len(restarts) and all(o["inherited"] for o in opens[1:])
    eeg_counters_hold(r)


# ---- T20: lifecycle at the Monitor level --------------------------------------------------------------------
def test_stop_start_after_unrecovered_jump_keeps_the_flag():
    r = Run(4, SCENARIOS["lost_2s"], dur=60).feed(until=40.0)
    assert r.m.timeline.timing_uncertain is not None
    seg = r.m.timeline.segment
    r.m.close("stopped")
    r.feed(until=45.0)                                                        # still monitored while stopped
    assert r.m.totals["monitored_while_eeg_off"] > 0
    r.m.open()
    o = [e for e, _ in r.quality() if e["event"] == "open"][-1]
    assert o["inherited"] is True and o["timing_uncertain"] is True
    assert o["reason"].startswith("timing_uncertain:") and o["segment"] == seg
    r.feed()
    assert r.m.timeline.timing_uncertain is not None                          # not cleared by a restart
    q = r.quality()
    tl = r.m.timeline
    rec = reconstruct(q, tl.n)
    exp = per_sample_reason(tl)
    gaps = [(e["next_input_index"]) for e, _ in q if e["event"] == "open"]
    stop_at = [e for e, _ in q if e["event"] == "close"][0]["connection"]["timeline_samples"]
    for i in range(tl.n):                                                     # equal wherever an outlet was open
        if not (stop_at <= i < gaps[1]): assert rec[i] == exp[i]
    eeg_counters_hold(r)


def test_status_snapshot_when_a_consumer_connects_and_periodically():
    """A recorder that connects after Start never receives `open` (found with LabRecorder): the state is
    re-sent when the Quality stream gets a consumer, then every STATUS_EVERY_S."""
    r = Run(4, SCENARIOS["lost_2s"], dur=60).feed(until=30.0)
    st = [e for e, _ in r.quality() if e["event"] == "status"]
    assert st and all(e["why"] == "periodic" for e in st)
    period = np.diff([t for e, t in r.quality() if e["event"] == "status"])
    assert np.all((period >= LO.STATUS_EVERY_S) & (period < LO.STATUS_EVERY_S + 0.1))
    r.lsl.consumers = True                                                    # LabRecorder connects
    r.feed(until=r.sim.chunks[r.next_chunk][2])                               # one chunk
    st = [e for e, _ in r.quality() if e["event"] == "status"]
    assert st[-1]["why"] == "consumer_connected" and st[-1]["reason"] == r.m.reason
    assert st[-1]["next_input_index"] == r.m.timeline.n and st[-1]["timing_uncertain"] is True
    r.feed()
    assert reconstruct(r.quality(), r.m.timeline.n) == per_sample_reason(r.m.timeline)


def test_closed_outlets_linger_so_close_is_delivered(window, fake):
    """liblsl drops a record pushed right before the outlet is destroyed: Stop keeps the outlets for LINGER_S."""
    import gc
    from PySide6 import QtCore, QtWidgets
    w = window
    ext = rec_of(w).instance
    connect(w); ext.toggle(); stream(w)
    ext.toggle(); gc.collect()                                                # Stop
    assert json.loads(fake.log[-1][2][0])["event"] == "close"
    assert any(o() is not None for o in fake.outlets)                         # still alive
    deadline = QtCore.QDeadlineTimer(int(LO.LINGER_S * 1000) + 500)
    while not deadline.hasExpired(): QtWidgets.QApplication.processEvents(); QtCore.QThread.msleep(20)
    gc.collect()
    assert all(o() is None for o in fake.outlets)                             # released afterwards


def test_cost_is_measured_with_and_without_outlets():
    r = Run(0, dur=20, start=False).feed(until=10.0)
    r.m.open(); r.feed()
    c = r.m.cost_summary()
    assert c["eeg_outlet_off"]["n"] > 0 and c["eeg_outlet_open"]["n"] > 0


# ---- T8: markers ----------------------------------------------------------------------------------------------
def test_marker_timestamp_is_unix_plus_offset():
    r = Run(2, dur=30).feed(until=10.0)
    t = r.clocks.unix() - 0.3                                                 # Space pressed 0.3 s ago
    ts = r.m.marker(t, "stim")
    off = r.m.bridge.marker_offset(t)[0]
    assert ts == pytest.approx(t + off, abs=1e-6)
    assert r.lsl.log[-1][:3] == (MARKERS, "sample", ["stim"])
    assert not [e for e, _ in r.quality() if e["event"] == "marker_uncertain"]


def test_marker_after_a_clock_step_is_flagged():
    r = Run(2, SCENARIOS["clock_step"], dur=40).feed(until=30.0)
    ts = r.m.marker(r.clocks.unix() - 1.0, "stim")
    mu = [e for e, _ in r.quality() if e["event"] == "marker_uncertain"]
    assert len(mu) == 1 and mu[0]["label"] == "stim" and mu[0]["marker_ts"] == ts


def test_no_marker_while_stopped():
    r = Run(2, dur=10, start=False).feed()
    assert r.m.marker(r.clocks.unix(), "x") is None and not r.lsl.log


# ---- T22: metadata ---------------------------------------------------------------------------------------------
def test_metadata():
    r = Run(0, dur=5)
    infos = {o().info.name(): o().info for o in r.lsl.outlets if o() is not None}
    e, mk, q = infos[EEG], infos[MARKERS], infos[QUALITY]
    assert (e.type(), e.channel_count(), e.nominal_srate(), e.channel_format()) == ("EEG", 4, 256.0, "float32")
    assert (mk.type(), mk.channel_count(), mk.nominal_srate(), mk.channel_format()) == ("Markers", 1, 0.0, "string")
    assert (q.type(), q.channel_count(), q.nominal_srate(), q.channel_format()) == ("Quality", 1, 0.0, "string")
    assert [i.source_id() for i in (e, mk, q)] == ["musemonitor-athena-test-eeg", "musemonitor-athena-test-markers",
                                                    "musemonitor-athena-test-quality"]
    chans = e.desc().child("channels").all("channel")
    assert [c.child_value("label") for c in chans] == NAMES
    assert {c.child_value("unit") for c in chans} == {"microvolts"} and {c.child_value("type") for c in chans} == {"EEG"}
    for info in (e, mk, q):
        d = info.desc()
        assert d.child_value("model") == "Muse S Athena"
        tm = d.child("timing")
        assert tm.child_value("clock_policy") == "host_receive_smoothed"
        assert "not calibrated" in tm.child_value("note") and tm.child_value("monitoring_since") == "connect"
        assert tm.child("timeline").child_value("fs_nominal") == "256.0"
        assert "same name" in d.child_value("source_id_note")
    assert q.desc().child_value("schema") == LO.QUALITY_SCHEMA
    assert LO.source_base(1, "MuseS-1234") == LO.source_base(1, "MuseS-1234") != LO.source_base(1, "MuseS-9999")


def test_close_releases_the_outlets():
    import gc
    r = Run(0, dur=5).feed()
    r.m.close("stopped"); gc.collect()
    assert all(o() is None for o in r.lsl.outlets)


def test_inputs_are_not_modified():
    r = Run(0, dur=5)
    i0, i1, arr = r.sim.chunks[3]
    x = np.random.default_rng(0).normal(size=(4, i1 - i0)); ts = r.sim.ts_unix[i0:i1].copy()
    x0, ts0 = x.copy(), ts.copy()
    r.clocks.now = arr
    r.m.push_eeg(x, ts)
    assert np.array_equal(x, x0) and np.array_equal(ts, ts0)


# ---- extension in the app: lifecycle, missing pylsl, review ----------------------------------------------
@pytest.fixture
def fake(monkeypatch):
    f = fake_pylsl.make()
    monkeypatch.setitem(sys.modules, "pylsl", f)
    return f


@pytest.fixture
def window(qapp, spec, settings, monkeypatch, tmp_path):
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path / "data"))
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(PROJECT_DIR)])
    yield w
    w.connected = False; w.close()


def rec_of(w, ext_id="lsl_outlet"):
    return next(r for r in w.extensions.records if r.id == ext_id)


def connect(w, name="MuseS-TEST"):
    w.device_name = name; w.connected = True; w.on_stream_started()


def disconnect(w):
    w.on_stopped()


def stream(w, n_chunks=5, t0=None):
    import time
    t0 = time.time() if t0 is None else t0
    for k in range(n_chunks):
        ts = t0 + (np.arange(12) + 12 * k) / 256.0
        w.on_data(np.zeros((4, 12)), ts)


def test_supported_only_for_athena(spec):
    assert LO.LslOutlet.supports(spec)
    assert not LO.LslOutlet.supports(type("S", (), {"board_id": 22})())


def test_start_before_connect_then_disconnect_and_reconnect(window, fake):
    w = window
    ext = rec_of(w).instance
    assert rec_of(w).status == "active"
    ext.toggle()                                                              # Start while not connected
    assert ext.wanted and ext.toggle_action.text() == "Stop LSL streams" and not fake.outlets
    connect(w); stream(w)
    m1 = ext.monitor
    assert m1.running and m1.monitoring_since == "connect" and m1.timeline.n == 60
    assert {o().info.name() for o in fake.outlets if o()} == {EEG, MARKERS, QUALITY}
    w.add_event("stim", None)
    assert any(name == MARKERS for name, *_ in fake.log)
    disconnect(w)
    assert ext.monitor is None and json.loads(fake.log[-1][2][0])["event"] == "close"
    assert ext.wanted                                                         # applies to the next connection
    connect(w); stream(w, 2)
    assert ext.monitor is not m1 and ext.monitor.timeline.n == 24 and ext.monitor.running   # fresh timeline
    ext.toggle()
    assert not ext.monitor.running and ext.toggle_action.text() == "Start LSL streams"
    assert ext.monitor.timeline.n == 24                                      # still monitoring the connection
    stream(w, 1); assert ext.monitor.timeline.n == 36


def test_loaded_mid_connection_through_the_manager(window, fake):
    w = window
    connect(w); stream(w, 2)
    w.extensions.unload("lsl_outlet")
    assert w.extensions.load("lsl_outlet") == "active"                        # catch-up calls on_connected
    ext = rec_of(w).instance
    assert ext.monitor is not None and ext.monitor.monitoring_since == "extension_enabled_mid_connection"
    ext.toggle(); stream(w, 1)
    o = json.loads(next(x[0] for name, k, x, t in fake.log if name == QUALITY))
    assert o["event"] == "open" and o["monitoring_since"] == "extension_enabled_mid_connection"
    w.extensions.unload("lsl_outlet")                                         # deactivate closes the outlets
    assert json.loads(fake.log[-1][2][0])["event"] == "close"


def test_missing_pylsl(window, monkeypatch):
    monkeypatch.setitem(sys.modules, "pylsl", None)                           # import pylsl → ImportError
    w = window
    ext = rec_of(w).instance
    connect(w); stream(w)
    assert ext.monitor is None and "pylsl" in ext.lsl_error
    ext.toggle()
    assert not ext.wanted and rec_of(w).status == "active"
    w.add_event("stim", None)
    assert rec_of(w).status == "active" and "unavailable" in ext.status_text()


def test_native_library_failure(window, monkeypatch):
    broken = fake_pylsl.make()
    def boom(): raise OSError("liblsl.dylib not found")
    broken.local_clock = boom
    monkeypatch.setitem(sys.modules, "pylsl", broken)
    w = window
    ext = rec_of(w).instance
    connect(w); stream(w)                                                     # on_connected must not raise
    assert rec_of(w).status == "active" and ext.monitor is None and "OSError" in ext.lsl_error
    ext.toggle()
    assert not ext.wanted


def test_status_text(window, fake):
    w = window
    ext = rec_of(w).instance
    connect(w); ext.toggle(); stream(w)
    s = ext.status_text()
    assert "Outlets: running" in s and "Monitoring since: connect" in s and "only means loaded" in s


def test_not_loaded_in_review_windows(qapp, spec, settings, tmp_path):
    from musemonitor.device.profiles import athena_profile
    from musemonitor.storage.reader import inspect, load, locate
    from musemonitor.ui.review_window import ReviewWindow
    from test_review import write_session
    folder, _ = write_session(spec, tmp_path / "s", sec=5, events=())
    sess = load(inspect(locate(folder), [athena_profile()]))
    w = ReviewWindow(sess, settings, profile=athena_profile(), extension_dirs=[str(PROJECT_DIR)], replay=False)
    rec = rec_of(w)
    assert rec.status == "not applicable" and rec.instance is None
    w.close()
