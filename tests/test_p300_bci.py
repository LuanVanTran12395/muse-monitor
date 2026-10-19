"""P300 extension, stage A (debate/claude-p300-extension-proposal.md + -round-2.md).

Synthetic signals with a KNOWN ERP — they show the pipeline cuts the right window and survives Athena-like
timestamps. They are not evidence that P300 can be detected on a person with a Muse."""
import json
import shutil
import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from extensions.p300_bci import epochs, schedule, session, timing

REPO = Path(__file__).resolve().parents[1]


# ---- schedule ---------------------------------------------------------------------------------------------
def small(**kw):
    base = dict(repetitions=4, trials_per_block=2, blocks=2, rest_s=2.0, cue_s=0.5, seed=7)
    base.update(kw)
    return schedule.Config(**base)


def test_schedule_is_deterministic_balanced_and_well_formed():
    a, b = schedule.build(small()), schedule.build(small())
    assert [(s.cell, s.on_s) for s in a.stims] == [(s.cell, s.on_s) for s in b.stims]          # same seed → same plan
    assert [s.cell for s in schedule.build(small(seed=8)).stims] != [s.cell for s in a.stims]
    cfg = a.config
    for tr in a.trials:
        st = [s for s in a.stims if s.trial == tr.trial]
        assert len(st) == cfg.repetitions * len(schedule.FLASHING)
        for rep in range(cfg.repetitions):                        # every flashing cell exactly once per repetition
            assert sorted(s.cell for s in st if s.rep == rep) == list(schedule.FLASHING)
        cells = [s.cell for s in st]
        assert all(x != y for x, y in zip(cells, cells[1:]))      # never the same cell twice in a row
        assert all(s.is_target == (s.cell == tr.target) for s in st)
        on = [s.on_s for s in st]
        assert np.allclose(np.diff(on), cfg.soa_s) and on[0] == pytest.approx(tr.cue_off_s + cfg.blank_s)
    targets = [tr.target for tr in schedule.build(small(trials_per_block=5, blocks=2)).trials]
    assert sorted(targets) == sorted(list(schedule.FLASHING) * 2)  # balanced over full cycles
    assert len(a.rests) == 1 and a.duration_s > a.trials[-1].end_s


@pytest.mark.parametrize("bad", [dict(soa_s=0.2), dict(flash_s=0.38), dict(repetitions=0), dict(blocks=0),
                                 dict(seed=-1), dict(mode="keys"), dict(cue_s=9)])
def test_invalid_configuration_is_refused(bad):
    cfg = small(**bad)
    assert cfg.errors()
    with pytest.raises(ValueError):
        schedule.build(cfg)


def test_runner_pops_actions_in_time_order():
    plan = schedule.build(small(blocks=1, trials_per_block=1, repetitions=1))
    r = schedule.Runner(plan, t0=100.0)
    assert r.next_due() == pytest.approx(100.0)
    first = r.pop_due(100.0)
    assert [a.kind for _, a in first] == ["trial_start", "cue_on"]
    seen = [a for _, a in r.pop_due(100.0 + plan.duration_s + 1)]
    kinds = [a.kind for a in seen]
    assert kinds[-1] == "done" and kinds.count("flash_on") == 5 and kinds.count("flash_off") == 5
    t = [a.t_s for a in seen]
    assert t == sorted(t) and r.finished


# ---- synthetic EEG with a known ERP -------------------------------------------------------------------------
def synth(fs, seconds, onsets_true, targets, names, amp=8.0, peak=0.3, noise=1.0, seed=0):
    """Continuous EEG (n_ch, n) and its true sample times; a Gaussian ERP (+amp µV at onset+peak, σ 50 ms) after
    each TARGET onset on every channel; non-targets add nothing."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * fs)) / fs
    x = noise * rng.standard_normal((len(names), t.size)) + 5 * np.sin(2 * np.pi * 9.73 * t)   # not phase-locked to the 400 ms SOA
    for on, is_t in zip(onsets_true, targets):
        if is_t: x += amp * np.exp(-0.5 * ((t - on - peak) / 0.05) ** 2)
    return x, t


@pytest.mark.parametrize("fs, names", [(256, ["TP9", "AF7", "AF8", "TP10"]), (250, ["Fp1", "Fp2"])])
def test_epochs_are_locked_to_the_onset(fs, names):
    onsets = np.arange(2.0, 60.0, 0.4)
    targets = (np.arange(onsets.size) % 5) == 2
    x, t = synth(fs, 62, onsets, targets, names)
    preset = epochs.Preset("t", tuple(names[:2]), baseline_s=(-0.2, 0.0), reject_uv=None)
    y = epochs.filter_blocks(epochs.select(x, names, preset), fs, preset, [(0, x.shape[1])])
    ep, times, reasons = epochs.extract(y, t, fs, onsets, preset)
    res = epochs.erp(ep, targets, reasons)
    mean = res["target"][0][0]
    assert times[mean.argmax()] == pytest.approx(0.3, abs=1.5 / fs + 0.01)        # peak where it was put
    assert mean.max() > 4 * np.abs(res["nontarget"][0][0]).max()
    ep2, _, r2 = epochs.extract(y, t, fs, onsets + 0.1, preset)                     # onset 100 ms too late
    shifted = epochs.erp(ep2, targets, r2)["target"][0][0]
    assert times[shifted.argmax()] == pytest.approx(0.2, abs=1.5 / fs + 0.01)      # → peak 100 ms earlier


def test_paper_preset_refuses_a_device_without_its_channels():
    x = np.zeros((2, 1000))
    with pytest.raises(ValueError, match="TP9, TP10"):
        epochs.select(x, ["Fp1", "Fp2"], epochs.PRESETS["li2020"])
    custom = replace(epochs.PRESETS["li2020"], channels=("Fp1", "Fp2"))
    assert epochs.select(x, ["Fp1", "Fp2"], custom).shape == (1, 1000)


def test_epochs_over_gaps_uncertain_or_segment_changes_are_rejected():
    fs = 256
    onsets = np.arange(2.0, 30.0, 0.4)
    x, t = synth(fs, 32, onsets, np.zeros(onsets.size, bool), ["TP9", "TP10"])
    t = t.copy()
    gap = np.searchsorted(t, 10.0); t[gap:] += 0.5                                  # 0.5 s gap at 10 s
    unc = np.zeros(t.size, bool); unc[np.searchsorted(t, 20.0):np.searchsorted(t, 21.0)] = True
    seg = np.zeros(t.size); seg[np.searchsorted(t, 25.0):] = 1
    preset = epochs.Preset("t", ("TP9", "TP10"), reject_uv=None)
    y = epochs.filter_blocks(epochs.select(x, ["TP9", "TP10"], preset), fs, preset, [(0, t.size)])
    ep, _, reasons = epochs.extract(y, t, fs, onsets, preset, seg, unc, missed=[i == 3 for i in range(onsets.size)])
    c = epochs.reason_counts(reasons)
    assert c["gap"] >= 2 and c["uncertain"] >= 2 and c["segment_boundary"] >= 1 and c["missed"] == 1
    assert all(np.isnan(ep[i]).all() for i, r in enumerate(reasons) if r)


def test_grouped_averages_follow_the_rules():
    meta, n_rep = [], 6
    for trial in range(2):
        for rep in range(n_rep):
            for cell in (1, 3):
                meta.append(dict(trial=trial, cell=cell, rep=rep, is_target=cell == 1, reason=None))
    meta[5]["reason"] = "amplitude"                                                 # trial 0, rep 2, cell 3
    ep = np.ones((len(meta), 1, 10))
    avg, gm, counts = epochs.group_average(ep, meta, k=4)
    assert counts["remainder_dropped"] == 2 * 2 * 2                                 # 6 mod 4 = 2 per cell per trial
    assert counts["incomplete_groups"] == 1 and counts["groups"] == 3 and len(avg) == 3
    with pytest.raises(ValueError, match="only 6 repetitions"):
        epochs.group_average(ep, meta, k=7)


def test_timestamp_statistics_count_duplicates_steps_back_and_gaps():
    fs = 256
    ts = np.repeat(np.arange(0, 10, 12 / fs), 12)[:2000]                            # packets: 12 equal timestamps
    ts[1000] -= 0.01                                                                # one step back
    ts[1500:] += 0.3                                                                # one gap
    s = timing.eeg_timestamp_stats(ts, fs)
    assert s["duplicate_timestamps"] > 1500 and s["steps_back"] == 1
    assert s["receive_pauses"] == 1 and s["longest_receive_interval_ms"] > 290      # the 0.3 s jump
    assert s["bursty_intervals"] >= s["receive_pauses"]                              # packets, not data loss


def test_timing_report_keeps_the_three_groups_apart():
    stims = [dict(planned_mono=1.0, fired_mono=1.002, painted_mono=1.006, missed=False),
             dict(planned_mono=1.4, fired_mono=1.47, painted_mono=None, missed=True)]
    rep = timing.summarize(stims, None, 256)
    assert rep["measured"]["missed"] == 1 and rep["measured"]["no_paint"] == 1
    assert rep["measured"]["paint_after_plan_ms"]["max"] == pytest.approx(6.0)
    assert rep["not_measured"] == dict(display_latency="not measured", ble_fixed_delay="not measured")
    assert rep["display_latency_s"] is None and "uncertainty" not in json.dumps(rep["measured"])


# ---- session writer -------------------------------------------------------------------------------------------
def test_writer_never_overwrites_and_closes_cleanly(tmp_path):
    a = session.new_folder(tmp_path, "20261019_120000"); b = session.new_folder(tmp_path, "20261019_120000")
    assert a != b and b.name.endswith("_2")
    w = session.SessionWriter(a, dict(channels=["TP9", "TP10"], fs=256), ["TP9", "TP10"])
    x = np.zeros((2, 12))
    assert w.put("eeg", (0, np.arange(12.0), np.arange(12.0), np.arange(12.0), 0, None, x))
    assert w.put("stim", dict(seq=0, cell=1, is_target=True, planned_mono=1.0))
    assert w.put("trial", dict(trial=0, block=0, target=1))
    assert w.close("completed", lambda wr: dict(ok=True))
    cfg = json.loads((a / "config.json").read_text())
    assert cfg["completed"] and cfg["rows_written"]["eeg"] == 12 and (a / "timing.json").exists()
    assert session.check(a) == (True, [])
    assert not w.put("eeg", (12, *([np.arange(12.0)] * 3), 0, None, x))           # closed: refused


def test_full_queue_and_writer_errors_are_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "QUEUE_MAX", 3)
    gate = threading.Event()
    orig = session.SessionWriter._handle
    monkeypatch.setattr(session.SessionWriter, "_handle", lambda self, k, p: (gate.wait(5), orig(self, k, p)))
    w = session.SessionWriter(session.new_folder(tmp_path), dict(channels=["A"]), ["A"])
    oks = [w.put("log", f"line {i}") for i in range(10)]
    assert not all(oks)                                                             # full → refused, never dropped silently
    t0 = time.monotonic()
    assert not w.close("writer_backlog", None, timeout_s=0.2)                       # GUI does not wait forever
    assert time.monotonic() - t0 < 1.0 and w.close_timed_out
    gate.set(); assert w.finished.wait(5)
    cfg = json.loads((w.folder / "config.json").read_text())
    assert cfg["stop_reason"] == "writer_backlog" and cfg["writer"]["close_timed_out"] and not cfg["completed"]
    monkeypatch.setattr(session.SessionWriter, "_handle", lambda self, k, p: 1 / 0)
    w2 = session.SessionWriter(session.new_folder(tmp_path), dict(channels=["A"]), ["A"])
    w2.put("log", "boom"); assert w2.finished.wait(5)
    assert w2.error.startswith("ZeroDivisionError") and not w2.put("log", "after")
    ok, findings = session.check(w2.folder)
    assert not ok and any("writer error" in f for f in findings)


# ---- the extension in the app (fake clocks, Athena-like timestamps) ----------------------------------------------
class Sim:
    """Drives the extension: a fake monotonic clock, EEG in packets of 12 samples sharing ONE receive timestamp
    (arrival = last sample + BLE_S), timer ticks every 5 ms, synchronous repaints, a known ERP after target flashes."""
    FS, PACKET, BLE_S, UNIX0 = 256, 12, 0.02, 1.79e9

    def __init__(self, w, ext, amp=8.0, seed=0):
        self.w, self.ext, self.amp = w, ext, amp
        self.now = 1000.0
        self.rng = np.random.default_rng(seed)
        ext.mono = lambda: self.now
        ext.unix = lambda: self.now - 1000.0 + self.UNIX0
        ext._reset_timeline()
        ext._schedule_next = lambda: None                        # ticks are driven here, not by a real QTimer
        self.n = 0                                               # samples generated
        self.targets_on = []                                     # painted onsets of target flashes (true times)
        orig = ext._painted

        def painted(tag, mono):
            orig(tag, mono)
            rec = ext.records.get(tag[1])
            if tag[0] == "on" and rec is not None and rec["is_target"]: self.targets_on.append(mono)
        ext._painted = painted
        if ext.window is not None: ext.window.on_painted = painted

    def sample_times(self, k):
        return 1000.0 + (self.n + np.arange(k)) / self.FS          # the signal starts with the simulation

    def eeg(self, k):
        t = self.sample_times(k)
        x = self.rng.standard_normal((4, k)) + 5 * np.sin(2 * np.pi * 9.73 * t)   # not phase-locked to the 400 ms SOA
        for on in self.targets_on:
            x += self.amp * np.exp(-0.5 * ((t - on - 0.3) / 0.05) ** 2)
        return x, t

    def run(self, seconds, session_running=False):
        end = self.now + seconds
        while self.now < end:
            self.now += 0.005
            if session_running and self.ext.writer is not None:
                self.ext._tick()
                if self.ext.window is not None and self.ext.window.pending: self.ext.window.repaint()
            while self.sample_times(1)[0] + (self.PACKET - 1) / self.FS + self.BLE_S <= self.now:
                x, t = self.eeg(self.PACKET)
                ts = np.full(self.PACKET, t[-1] + self.BLE_S - 1000.0 + self.UNIX0)
                self.n += self.PACKET
                self.w.on_data(x, ts)


@pytest.fixture
def app_with_p300(qapp, spec, settings, monkeypatch, tmp_path):
    from musemonitor.ui import main_window as mw
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path / "data"))              # sessions under tmp
    ext_dir = tmp_path / "exts"; shutil.copytree(REPO / "extensions" / "p300_bci", ext_dir / "p300_bci",
                                                  ignore=shutil.ignore_patterns("__pycache__"))
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(ext_dir)]); w.resize(1200, 800); w.show()
    rec = next(r for r in w.extensions.records if r.id == "p300_bci")
    assert rec.status == "active", rec.error
    ext = rec.instance
    monkeypatch.setattr(type(ext), "data_root", None, raising=False)
    ext.tab.subject.setText("T01")
    yield w, ext
    if ext.window is not None: ext.window.on_closed = lambda: None
    w.connected = False; w.close()


def connected(w):
    w.connected = w.streaming = True; w.device_name = "MuseS-TEST"


def test_start_is_blocked_until_stream_and_timing_are_ready(app_with_p300):
    w, ext = app_with_p300
    assert "Connect the headset" in ext.blockers()[0] and ext.start() is False
    connected(w)
    sim = Sim(w, ext)
    sim.run(5)
    assert any("Measuring EEG timing" in b for b in ext.blockers())
    sim.run(25)                                                                     # ≥ 20 s: period acquired
    assert ext.blockers() == [], ext.blockers()


def run_session(w, ext, mode="eeg_only", amp=8.0):
    connected(w)
    ext.tab.write_config(schedule.Config(repetitions=6, trials_per_block=3, blocks=1, cue_s=0.5, rest_s=0.0,
                                         seed=3, mode=mode))
    ext.tab.instr.setChecked(False); ext.tab.countdown.setValue(0)          # straight into the session
    sim = Sim(w, ext, amp=amp)
    sim.run(30)
    assert ext.start(), ext.blockers()
    from PySide6 import QtTest
    assert QtTest.QTest.qWaitForWindowExposed(ext.window)       # a hidden / unexposed window is never painted
    return sim


def test_session_records_onset_locked_erp_under_athena_like_timestamps(app_with_p300):
    w, ext = app_with_p300
    sim = run_session(w, ext)
    folder = ext.writer.folder
    sim.run(ext.plan.duration_s + 2, session_running=True)
    assert ext.writer is None                                                       # finished → stop("completed")
    s = session.load(folder)
    assert s["config"]["completed"] and s["config"]["display_latency_s"] is None
    assert session.check(folder) == (True, [])
    st = s["stimuli"]
    assert len(st) == len(ext.plan.stims) and all(r["painted_mono"] is not None for r in st)
    assert sum(r["missed"] for r in st) == 0
    rep = json.loads((folder / "timing.json").read_text())
    assert rep["estimated"]["duplicate_timestamps"] > 1000                          # packets share one timestamp
    assert rep["not_measured"]["ble_fixed_delay"] == "not measured"
    res = epochs.analyse_session(s, epochs.PRESETS["default"], timing.fit_timeline)
    mean = res["erp"]["target"][0][0]
    peak = res["times"][mean.argmax()]
    # the receive times include the (unmeasured) 20 ms BLE delay and the 12-sample packet: the ERP appears later
    # than the true +300 ms by about that much — exactly the limitation the report states
    assert 0.29 <= peak <= 0.37, peak
    assert mean.max() > 3 * np.abs(res["erp"]["nontarget"][0][0]).max()
    assert res["counts"]["kept"] >= 0.9 * len(st)


def test_eeg_only_ignores_keys_and_response_mode_records_them_apart(app_with_p300):
    w, ext = app_with_p300
    sim = run_session(w, ext, mode="eeg_only")
    space = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Space, QtCore.Qt.NoModifier, " ")
    ext._key(space)
    folder = ext.writer.folder
    ext.stop("stopped")
    assert not (folder / "keys.csv").exists()
    ext.tab.write_config(replace(ext.tab.read_config(), mode="response_assisted"))
    assert ext.start()
    sim.run(2, session_running=True)
    ext._key(space); ext._key(space)
    folder2 = ext.writer.folder
    ext.stop("stopped")
    keys = session.load(folder2)["keys"]
    assert len(keys) == 2 and keys[0]["key"] == "space"
    assert json.loads((folder2 / "config.json").read_text())["mode"] == "response_assisted"


@pytest.mark.parametrize("how", ["disconnect", "unload", "window", "backlog"])
def test_every_way_of_stopping_closes_the_files(app_with_p300, how, monkeypatch):
    w, ext = app_with_p300
    sim = run_session(w, ext)
    sim.run(3, session_running=True)
    writer = ext.writer
    if how == "disconnect": ext.on_disconnected(); expected = "disconnected"
    elif how == "unload": w.extensions.unload("p300_bci"); expected = "unloaded"
    elif how == "window": ext.window.close(); expected = "window_closed"
    else:
        monkeypatch.setattr(writer, "put", lambda kind, payload: False); expected = "writer_backlog"
        sim.run(0.5, session_running=True)
    assert writer.finished.wait(5)
    cfg = json.loads((writer.folder / "config.json").read_text())
    assert cfg["stop_reason"] == expected and not cfg["completed"]
    assert (writer.folder / "timing.json").exists()
    assert ext.writer is None and not ext._timer.isActive()
    if how == "unload": assert ext.window is None
    trials = session.load(writer.folder)["trials"]
    if how == "backlog":                     # a full queue refuses everything after it: incomplete, never silent
        assert trials == [] and cfg["stop_reason"] == "writer_backlog"
    else:
        assert trials and trials[-1]["aborted"] == 1                                # the trial in progress


def test_offline_cli(app_with_p300, capsys):
    from extensions.p300_bci import offline
    w, ext = app_with_p300
    sim = run_session(w, ext)
    folder = ext.writer.folder
    sim.run(ext.plan.duration_s + 2, session_running=True)
    assert offline.main(["check", str(folder)]) == 0
    assert offline.main(["timing", str(folder)]) == 0
    out_csv = folder / "erp.csv"
    assert offline.main(["erp", str(folder), "--csv", str(out_csv)]) == 0
    text = capsys.readouterr().out
    assert "OK — complete" in text and "[not_measured]" in text and "target: n=" in text
    assert out_csv.read_text().startswith("time_s,target_mean_uv")


# ---- instructions and countdown before the session -------------------------------------------------------------
def key(k):
    return QtGui.QKeyEvent(QtCore.QEvent.KeyPress, k, QtCore.Qt.NoModifier, "")


def ready(w, ext, lang="vi", countdown=3, mode="eeg_only"):
    connected(w)
    ext.tab.write_config(schedule.Config(repetitions=2, trials_per_block=2, blocks=2, rest_s=10, cue_s=0.5, mode=mode))
    ext.tab.instr.setChecked(True); ext.tab.countdown.setValue(countdown)
    ext.tab.lang.setCurrentIndex(ext.tab.lang.findData(lang))
    sim = Sim(w, ext); sim.run(30)
    return sim


def sessions(ext):
    from musemonitor.storage.session import data_root
    root = data_root() / "p300_bci"
    return [p for p in root.iterdir() if p.is_dir()] if root.exists() else []


def test_instructions_then_countdown_then_session(app_with_p300):
    w, ext = app_with_p300
    ready(w, ext)
    assert ext.start() and ext.phase == "instructions" and ext.writer is None and sessions(ext) == []
    win = ext.window
    assert win.page["title"] == "Thí nghiệm P300" and "1 / 6" in win.page["footer"]
    assert "Chưa có dữ liệu nào được ghi" in " ".join(win.page["lines"])
    ext._key(key(QtCore.Qt.Key_Space)); ext._key(key(QtCore.Qt.Key_Right))
    assert ext.page_i == 2 and win.page.get("demo") and win.cue == 1 and ext._demo.isActive()   # example page
    ext._demo_tick(); assert win.lit == 1                                       # the target flashes in the example
    ext._key(key(QtCore.Qt.Key_Left)); assert ext.page_i == 1 and not ext._demo.isActive()
    win.on_click(); win.on_click(); win.on_click(); win.on_click()              # click works too
    assert ext.page_i == 5 and win.page["title"] == "Sẵn sàng?"
    ext._key(key(QtCore.Qt.Key_Space))
    assert ext.phase == "countdown" and win.countdown[0] == 3 and win.page is None and sessions(ext) == []
    assert "nothing recorded yet" in ext.status_texts()["Session"]
    ext._count_tick(); assert win.countdown[0] == 2
    ext._count_tick(); ext._count_tick()
    assert ext.phase == "running" and ext.writer is not None and win.countdown is None
    cfg = json.loads((ext.writer.folder / "config.json").read_text())
    assert cfg["preparation"]["instructions_shown"] and cfg["preparation"]["language"] == "vi"
    assert cfg["preparation"]["countdown_s"] == 3 and cfg["preparation"]["seconds_before_session"] >= 0
    ext.stop("stopped")


@pytest.mark.parametrize("how", ["esc", "stop_button", "disconnect", "window"])
def test_cancelling_before_the_session_records_nothing(app_with_p300, how):
    w, ext = app_with_p300
    ready(w, ext)
    ext.start()
    if how == "esc": ext._key(key(QtCore.Qt.Key_Escape))
    elif how == "stop_button": ext.tab.stop_btn.click()
    elif how == "disconnect": ext.on_disconnected()
    else: ext.window.close()
    assert ext.phase == "idle" and ext.writer is None and sessions(ext) == []
    assert not ext._count.isActive() and not ext._demo.isActive()
    assert ext.tab.start_btn.isEnabled() or how == "disconnect"


def test_readiness_is_checked_again_when_the_countdown_ends(app_with_p300):
    w, ext = app_with_p300
    ready(w, ext, countdown=1)
    ext.tab.instr.setChecked(False)
    assert ext.start() and ext.phase == "countdown"
    w.streaming = False                                                         # stream lost while counting down
    ext._count_tick()
    assert ext.phase == "idle" and ext.writer is None and sessions(ext) == []


def test_pages_follow_the_configuration_and_language(app_with_p300):
    from extensions.p300_bci import instructions
    plan = schedule.build(schedule.Config(repetitions=2, trials_per_block=3, blocks=2, rest_s=20, mode="response_assisted"))
    en = instructions.pages(plan, "en")
    text = " ".join(" ".join(p["lines"]) for p in en)
    assert "6 trials in 2 blocks" in text and "press Space each time" in text and "20 s break" in text
    vi = " ".join(" ".join(p["lines"]) for p in instructions.pages(replace(plan, config=replace(plan.config, mode="eeg_only")), "vi"))
    assert "Không cần nhấn phím nào" in vi and len(en) == 6


def test_session_messages_follow_the_language(app_with_p300):
    w, ext = app_with_p300
    sim = run_session(w, ext)                                                   # default language: Vietnamese
    sim.run(1.2, session_running=True)
    assert ext.window.message.startswith("Nhìn vào: ") and "đếm số lần nó sáng" in ext.window.message
    ext.stop("stopped")
    assert ext.window.message == "Phiên đã kết thúc (stopped)"
    ext.tab.lang.setCurrentIndex(ext.tab.lang.findData("en"))
    assert ext.start()
    sim.run(1.2, session_running=True)
    assert ext.window.message.startswith("Look at: ")
    ext.stop("stopped")


# ---- break screen before block 2, sounds at session start / block start / end ------------------------------------
def two_blocks(w, ext, sound=True, countdown=3):
    connected(w)
    ext.tab.write_config(schedule.Config(repetitions=2, trials_per_block=1, blocks=2, rest_s=8, cue_s=0.5, seed=2))
    ext.tab.instr.setChecked(False); ext.tab.countdown.setValue(0); ext.tab.sound.setChecked(sound)
    sim = Sim(w, ext); sim.run(30)
    assert ext.start()
    ext.tab.countdown.setValue(countdown)                       # used for the countdown before the next block
    from PySide6 import QtTest
    QtTest.QTest.qWaitForWindowExposed(ext.window)
    return sim


def test_break_screen_then_countdown_before_the_next_block(app_with_p300):
    w, ext = app_with_p300
    sim = two_blocks(w, ext)
    rest_on, rest_off = ext.plan.rests[0]
    t0 = ext.runner.t0
    sim.run(rest_on + 0.3 - (sim.now - t0), session_running=True)
    win = ext.window
    assert win.rest is not None and win.rest[1] == "Nghỉ" and 7 <= win.rest[0] <= 8   # seconds left shown
    sim.run(rest_off - 2.5 - (sim.now - t0), session_running=True); ext._rest_tick()
    assert win.countdown is not None and win.countdown[0] == 3 and "Khối tiếp theo" in win.countdown[1]
    assert 0 < win.countdown[2] <= 1                                                    # ring fraction
    sim.run(rest_off + 0.2 - (sim.now - t0), session_running=True)
    assert win.rest is None and win.countdown is None and not ext._rest.isActive()      # back to the grid
    assert win.message.startswith("Nhìn vào: ")                                         # next trial's cue
    ext.stop("stopped")


def test_sounds_at_session_start_block_start_and_end(app_with_p300):
    w, ext = app_with_p300
    sim = two_blocks(w, ext)
    folder = ext.writer.folder
    assert ext.cues.played[-1] == "go"                                                  # session start
    sim.run(ext.plan.duration_s + 2, session_running=True)
    assert ext.cues.played[-3:] == ["go", "go", "done"]                                 # start, block 2, end
    log = (folder / "log.txt").read_text()
    assert "sound go (session start)" in log and "sound go (block start)" in log and "sound done (session end)" in log
    ext.tab.countdown.setValue(0)                                # straight into the session again
    assert ext.start() and ext.phase == "running"
    sim.run(1, session_running=True); ext.stop("stopped")
    assert ext.cues.played[-1] == "retry"                                                # interrupted: low tone


def test_no_sound_when_turned_off(app_with_p300):
    w, ext = app_with_p300
    sim = two_blocks(w, ext, sound=False)
    folder = ext.writer.folder
    sim.run(ext.plan.duration_s + 2, session_running=True)
    assert ext.cues.played == [] and "sound" not in (folder / "log.txt").read_text()


def test_navigation_keys_know_the_first_and_last_page(app_with_p300):
    w, ext = app_with_p300
    ready(w, ext)
    ext.start()
    page = ext.window.page
    assert page["index"] == 0 and page["total"] == 6 and page["nav"]["back"] == "quay lại"
    ext.page_i = 5; ext._show_page()
    assert ext.window.page["index"] == 5 and ext.window.page["nav"]["start"] == "bắt đầu"
    ext.stop("stopped")


def test_clock_steps_are_counted_per_session(app_with_p300):
    w, ext = app_with_p300
    sim = run_session(w, ext)
    ext.bridge.steps += 1                                        # a clock step BEFORE this session started …
    ext.steps_at_start += 1
    ext.bridge.steps += 2                                        # … and two during it
    folder = ext.writer.folder
    ext.stop("stopped"); assert ext.writer is None
    rep = json.loads((folder / "timing.json").read_text())["estimated"]
    assert rep["clock_steps_during_session"] == 2
    assert "package_num_steps_not_0_or_1_during_session" in rep and "NOT a lost-packet count" in rep["package_num_note"]
    assert "gaps" not in rep


# ---- report.html -------------------------------------------------------------------------------------------
def test_report_after_a_session_has_every_section(app_with_p300):
    from extensions.p300_bci import report
    w, ext = app_with_p300
    sim = run_session(w, ext)
    folder = ext.writer.folder
    sim.run(ext.plan.duration_s + 2, session_running=True)
    s = session.load(folder)
    assert len(s["contact"]) >= 10 and set(s["contact"][0]["channels"]) == {"TP9", "AF7", "AF8", "TP10"}   # every 2 s
    out = report.write(folder, lang="vi")
    doc = out.read_text()
    for section in ("Tóm tắt", "Tình trạng điện cực", "Epoch đạt", "ERP và P300", "Độ lệch thời gian",
                    "Giới hạn và phương pháp"):
        assert f">{section}<" in doc
    assert "TP9+TP10 (default)" in doc and doc.count("<svg") >= 1 + 5 + 1          # contact strip, 5 ERPs, histogram
    assert "CHỈ MANG TÍNH THĂM DÒ" in doc and "not measured" in doc
    assert (folder / "erp_tp9_tp10.csv").read_text().startswith("time_s,target_mean_uv")
    stats = report.window_stats(epochs.analyse_session(s, epochs.PRESETS["default"], timing.fit_timeline))
    assert stats["diff"] > 1.0 and stats["p"] < 0.01 and 0.29 <= stats["peak_latency"] <= 0.37      # synthetic ERP found
    assert "Có khác biệt target / non-target" in doc
    en = report.write(folder, lang="en").read_text()
    assert ">Electrodes<" in en and ">Good epochs<" in en and "EXPLORATORY" in en


def test_report_without_an_erp_says_so_and_handles_old_sessions(app_with_p300):
    from extensions.p300_bci import offline, report
    w, ext = app_with_p300
    sim = run_session(w, ext, amp=0.0)                                              # no ERP at all
    folder = ext.writer.folder
    sim.run(ext.plan.duration_s + 2, session_running=True)
    (folder / "contact.csv").unlink()                                               # like a session from before
    assert offline.main(["report", str(folder), "--lang", "vi"]) == 0
    doc = (folder / "report.html").read_text()
    assert "Chưa thấy khác biệt" in doc and "không ghi chất lượng tiếp xúc" in doc


def test_report_is_written_after_the_session_and_opened_from_the_tab(app_with_p300, monkeypatch):
    w, ext = app_with_p300
    sim = run_session(w, ext)
    folder = ext.writer.folder
    sim.run(ext.plan.duration_s + 2, session_running=True)                          # completed → analyse → report
    end = time.monotonic() + 20
    while not hasattr(ext, "last_analysis") and time.monotonic() < end: QtWidgets.QApplication.processEvents(); time.sleep(0.02)
    assert ext.last_analysis.get("report") == str(folder / "report.html") and (folder / "report.html").exists()
    assert ext.tab.report_btn.isEnabled() and "report.html written" in ext.tab.summary.text()
    opened = []
    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()))
    ext.tab.report_btn.click()
    assert opened == [str(folder / "report.html")]


def test_sessions_go_next_to_the_app_recordings_not_into_the_code(app_with_p300, tmp_path):
    w, ext = app_with_p300
    sim = run_session(w, ext)
    folder = ext.writer.folder
    ext.stop("stopped")
    assert folder.parent == tmp_path / "data" / "p300_bci"                          # <data root>/p300_bci/<stamp>
    assert REPO / "extensions" not in folder.parents


def test_subject_id_is_required_and_names_the_session(app_with_p300):
    w, ext = app_with_p300
    ext.tab.subject.setText("")
    assert ext.blockers()[0].startswith("Enter a subject ID")
    ext.tab.subject.setText("Nguyễn A")                              # validator refuses names / spaces / accents
    assert not ext.tab.subject.hasAcceptableInput()
    ext.tab.subject.setText("S07")
    sim = run_session(w, ext)
    folder = ext.writer.folder
    sim.run(ext.plan.duration_s + 2, session_running=True)
    assert ext.writer is None and folder.name.endswith("_S07")
    assert session.load(folder)["config"]["subject_id"] == "S07"
    assert "start: subject S07" in (folder / "log.txt").read_text(encoding="utf-8")
    assert ext.app.setting("subject") == "S07"                         # pre-filled next time

def test_new_folder_with_subject(tmp_path):
    a = session.new_folder(tmp_path, stamp="20260101_000000", subject="S01")
    b = session.new_folder(tmp_path, stamp="20260101_000000", subject="S01")
    assert a.name == "20260101_000000_S01" and b.name == "20260101_000000_S01_2"
    with pytest.raises(ValueError): session.new_folder(tmp_path, subject="../x")
