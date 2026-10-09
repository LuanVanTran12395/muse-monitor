"""OnlineTimeline + ClockBridge (LSL stage 2, debate/claude-lsl-athena-stage2-*.md).

CI checks INVARIANTS only, on the measured-batching model ("athena_empirical") over 20 seeds plus three
robustness models. Error percentiles are not pass conditions — tools/timeline_report.py reports them.
"""
import numpy as np
import pytest

import timeline_sim as TS
from musemonitor.core.online_timeline import ClockBridge, OnlineTimeline, TimelineConfig

SEEDS = range(20)
FS_NOM = 256.0
G = 0.25                                  # max(gap_s, gap_periods / fs) with the defaults


def run(seed=0, events=(), model="athena_empirical", stream="eeg", dur=60.0, fs_nom=FS_NOM, **cfg):
    sim = TS.simulate(seed, dur, stream, model, events=events)
    tl = OnlineTimeline(TimelineConfig(fs_nom, **cfg))
    return sim, TS.replay(sim, tl), tl


def check_invariants(out, fs_nom=FS_NOM, slack=0.03):
    t, seg, arr = out["t_out"], out["segment"], out["arrival"]
    same = seg[1:] == seg[:-1]
    d = np.diff(t)[same]
    assert np.all(d > 0), "not strictly increasing within a segment"
    assert np.all(t <= arr + G + 1e-9), "timestamp in the future"
    jumps = d > (1 + slack) / fs_nom
    return d, jumps


# ---- T17: the model itself matches the measured batching ----------------------------------------------
@pytest.mark.parametrize("stream, lo, hi", [("eeg", 0.35, 0.41), ("opt", 0.13, 0.19), ("imu", 0.0, 0.0)])
def test_model_reproduces_measured_duplicate_share(stream, lo, hi):
    sim = TS.simulate(1, 120, stream)
    share = np.mean(np.diff(sim.ts_unix) == 0)
    assert lo <= share <= hi


# ---- T1 / T1b: clean streams ----------------------------------------------------------------------------
@pytest.mark.parametrize("seed", SEEDS)
def test_T1_clean_stream_invariants(seed):
    _, out, tl = run(seed)
    d, jumps = check_invariants(out)
    assert not jumps.any() and np.all(d > 0.97 / FS_NOM)               # nearly regular spacing
    rep = tl.report()
    assert rep["counters"]["arrival_pauses"] == 0 and not rep["rebases"] and not rep["forward_jumps"]
    assert rep["counters"]["period_acquired"] == 1 and abs(rep["fs_estimate"] - TS.FS_TRUE["eeg"]) < 0.2


@pytest.mark.parametrize("model", ["distinct", "fixed_12", "bursty"])
@pytest.mark.parametrize("seed", range(3))
def test_T1b_other_batching_models(model, seed):
    _, out, tl = run(seed, model=model)
    check_invariants(out)
    assert not tl.report()["rebases"] and not tl.report()["forward_jumps"]


@pytest.mark.parametrize("stream, fs_nom", [("opt", 64.0), ("imu", 52.0)])
def test_T1c_optics_and_imu(stream, fs_nom):
    _, out, tl = run(1, stream=stream, fs_nom=fs_nom, dur=90)
    check_invariants(out, fs_nom)
    assert abs(tl.report()["fs_estimate"] - TS.FS_TRUE[stream]) < 0.1


# ---- T2: rate change -------------------------------------------------------------------------------------
@pytest.mark.parametrize("seed", range(5))
def test_T2_rate_change_is_followed_in_bounded_steps(seed):
    _, out, tl = run(seed, events=[TS.Event("rate", 30.0, fs=256.70)], dur=120)
    check_invariants(out)
    log = tl.period_log
    after = np.array([p for _, p in log[1:]])                            # after acquisition
    steps = np.abs(np.diff(np.r_[log[0][1], after])) / np.r_[log[0][1], after][:-1]
    assert steps.max() <= 200e-6 + 1e-12
    assert tl.report()["counters"]["period_rejected"] == 0
    assert abs(tl.report()["fs_estimate"] - 256.70) < 0.05


# ---- T3 / T3b / T3c / T5 / T15: pauses ---------------------------------------------------------------------
@pytest.mark.parametrize("seed", range(5))
def test_T3_lost_data_one_forward_jump_marked_uncertain(seed):
    _, out, tl = run(seed, events=[TS.Event("pause", 30.0, 2.0, "lost")])
    check_invariants(out)
    rep = tl.report(); c = rep["counters"]
    assert c["arrival_pauses"] == 1 and c["pauses_unrecovered_after_wait"] == 1 and c["pauses_caught_up"] == 0
    assert len(rep["forward_jumps"]) == 1 and abs(rep["forward_jumps"][0][1] - 2.0) <= G
    assert any(r == "pause_unrecovered_after_wait" for *_, r in rep["uncertain_intervals"])
    assert not rep["rebases"]
    assert "lost" not in " ".join(c)                                     # no counter claims lost samples


@pytest.mark.parametrize("seed", range(5))
def test_T5_stall_then_burst_no_jump(seed):
    _, out, tl = run(seed, events=[TS.Event("pause", 30.0, 0.5, "late")])
    check_invariants(out)
    rep = tl.report()
    assert rep["counters"]["arrival_pauses"] <= 1 and rep["counters"]["pauses_unrecovered_after_wait"] == 0
    assert rep["timing_uncertain"] is None
    assert not rep["forward_jumps"] and not rep["rebases"]


@pytest.mark.parametrize("seed", range(3))
def test_T3b_slowly_drained_backlog_is_waited_for(seed):
    """Backlog of 2 s drained at 1.2 × fs (~10 s): still catching up at C → wait longer, no jump, no rebase."""
    _, out, tl = run(seed, events=[TS.Event("pause", 30.0, 2.0, "late", drain=1.2)], dur=90)
    check_invariants(out)
    c = tl.report()["counters"]
    assert c["pauses_caught_up"] == 1 and c["pause_extensions"] >= 1
    assert not tl.report()["forward_jumps"] and not tl.report()["rebases"]


def test_T3c_backlog_too_slow_to_wait_for_signals_rebase():
    """Drained at 1.01 × fs (~200 s): forward jump after C, then the timeline would run into the future →
    an explicit rebase (new segment), never a long stretch of timestamps ahead of their arrival."""
    _, out, tl = run(3, events=[TS.Event("pause", 30.0, 2.0, "late", drain=1.01)], dur=300)
    check_invariants(out)
    rep = tl.report()
    assert len(rep["forward_jumps"]) == 1 and len(rep["rebases"]) >= 1
    res = [r for r in out["results"] if r.rebase is not None]
    assert res and all(r.uncertain and r.segment >= 1 for r in res)


def test_T15_one_huge_backlog_chunk_does_not_decide_early():
    """A chunk with more than C·fs samples arrives 4 s late, then a small one 0.1 s later. A rule counting
    samples would decide at once; C is ARRIVAL time, so the timeline must still be waiting."""
    tl = OnlineTimeline(TimelineConfig(FS_NOM))
    p = 1 / FS_NOM
    for i in range(40):                                                # 10 s steady
        r = 100 + (np.arange(64) + i * 64) * p
        tl.push(r, r[-1] + 0.02)
    last = 100 + 40 * 64 * p
    big = np.full(3 * 256, last + 4.0)                                 # 768 samples (> 2 s · 256) at once
    tl.push(big, last + 4.02)
    assert tl.state == "pause_pending"
    res = tl.push(np.full(8, last + 4.1), last + 4.12)
    assert tl.state == "pause_pending" and not tl.forward_jumps and not res.rebase


# ---- T4a / T4b: clock steps through ClockBridge ------------------------------------------------------------
@pytest.mark.parametrize("delta", [2.0, -2.0])
def test_T4a_clock_step_between_chunks(delta):
    sim = TS.simulate(2, 60, events=[TS.Event("clock_step", 30.0 + 1e-9, delta)])
    # move the step exactly onto a poll boundary: everything delivered after it is in later chunks
    poll = min(c[2] for c in sim.chunks if c[2] >= 30.0)
    sim.events[0].t = poll + 1e-9
    sim.ts_unix = np.array([sim.unix_at(d) for d in sim.deliver])
    tl = OnlineTimeline(TimelineConfig(FS_NOM)); out = TS.replay(sim, tl)
    check_invariants(out)
    rep = tl.report()
    assert out["bridge"].steps == 1 and not rep["forward_jumps"] and not rep["rebases"]
    assert rep["counters"]["arrival_pauses"] == 0


@pytest.mark.parametrize("delta, frac", [(2.0, 0.2), (2.0, 0.8), (-2.0, 0.2), (-2.0, 0.8)])
def test_T4b_clock_step_inside_a_chunk(delta, frac):
    """Step at a fraction of a poll interval: the chunk mixes both epochs (minority / majority)."""
    sim0 = TS.simulate(2, 60)
    poll = min(c[2] for c in sim0.chunks if c[2] >= 30.0)
    t_step = poll - 0.02 * (1 - frac)
    sim = TS.simulate(2, 60, events=[TS.Event("clock_step", t_step, delta)])
    tl = OnlineTimeline(TimelineConfig(FS_NOM)); out = TS.replay(sim, tl)
    check_invariants(out)
    rep = tl.report()
    assert out["bridge"].steps == 1 and not rep["forward_jumps"] and not rep["rebases"]
    assert any(r == "clock_step" for *_, r in rep["uncertain_intervals"]) and tl.state == "normal"


# ---- T6 / T12 / T13 / T14 ------------------------------------------------------------------------------------
def test_T6_past_never_modified():
    sim, out, tl = run(4, events=[TS.Event("pause", 20.0, 2.0, "lost")], dur=40)
    copies = [r.t_out.copy() for r in out["results"]]
    assert all(np.array_equal(a, r.t_out) for a, r in zip(copies, out["results"]))
    assert len({id(r.t_out) for r in out["results"]}) == len(out["results"])   # every chunk a new array


def test_T12_deterministic():
    a = run(7, events=[TS.Event("pause", 20.0, 2.0, "lost")], dur=40)[1]["t_out"]
    b = run(7, events=[TS.Event("pause", 20.0, 2.0, "lost")], dur=40)[1]["t_out"]
    assert np.array_equal(a, b)


def test_T13_bad_input():
    tl = OnlineTimeline(TimelineConfig(FS_NOM))
    assert tl.push([], 1.0).t_out.size == 0
    p = 1 / FS_NOM
    r = 10 + np.arange(64) * p
    tl.push(r, r[-1] + 0.02)
    out1 = tl.push([r[-1] + p], r[-1] + p + 0.02).t_out                  # 1-sample chunk
    bad = r[-1] + p * np.arange(2, 66); bad[[3, 9]] = np.nan; bad[20] = np.inf
    out2 = tl.push(bad, bad[-1] + 0.02).t_out
    allnan = tl.push(np.full(5, np.nan), bad[-1] + 0.05).t_out
    seq = np.concatenate([out1, out2, allnan])
    assert np.all(np.diff(seq) > 0) and tl.report()["counters"]["invalid_samples"] == 8


@pytest.mark.parametrize("kw", [dict(fs_nominal=0), dict(fs_nominal=256, slew=1.0), dict(fs_nominal=256, gain=0),
                                dict(fs_nominal=256, min_fit_s=40), dict(fs_nominal=256, max_wait_s=1)])
def test_T14_config_validation(kw):
    with pytest.raises(ValueError):
        TimelineConfig(**kw)


# ---- T9: report ----------------------------------------------------------------------------------------------
def test_T9_report_quantiles_and_tails():
    tl = OnlineTimeline(TimelineConfig(FS_NOM))
    p = 1 / FS_NOM
    rng = np.random.default_rng(0)
    resid = []
    for i in range(20):
        r = 50 + (np.arange(32) + 32 * i) * p + rng.normal(0, 0.002, 32)
        res = tl.push(r, r.max() + 0.02); resid.append(r - res.t_out)
    resid = np.concatenate(resid)
    rep = tl.report()["residual_s"]
    assert rep["all"]["n"] == resid.size == rep["unflagged"]["n"] + rep["flagged"]["n"]
    for q, key in ((0.5, "p50"), (0.95, "p95"), (0.99, "p99")):
        assert abs(rep["all"][key] - np.quantile(resid, q)) <= 2e-4           # within a couple of 0.1 ms bins
    assert rep["all"]["min"] == pytest.approx(resid.min()) and rep["all"]["max"] == pytest.approx(resid.max())
    tl2 = OnlineTimeline(TimelineConfig(FS_NOM))
    tl2.push(np.arange(10) * p, 1.0); tl2._hist["unflagged"].add([5.0, -7.0])  # beyond ±2 s
    s = tl2.report()["residual_s"]["unflagged"]
    assert s["overflow"] == 1 and s["underflow"] == 1 and s["max"] == 5.0 and s["min"] == -7.0


# ---- T8: markers via ClockBridge ------------------------------------------------------------------------------
class Clocks:
    def __init__(self): self.mono_t, self.off = 100.0, 1.79e9
    def mono(self): return self.mono_t
    def unix(self): return self.mono_t + self.off


def test_T8_marker_offset_and_uncertainty():
    c = Clocks(); b = ClockBridge(c.unix, c.mono)
    for _ in range(10): c.mono_t += 0.02; b.measure()
    press = c.unix()
    off, unc = b.marker_offset(press)
    assert off == pytest.approx(-1.79e9) and not unc
    assert press + off == pytest.approx(c.mono_t)                              # maps exactly to the mono clock
    c.off -= 2.0                                                               # unix steps BACK while the label dialog is open
    for _ in range(5): c.mono_t += 0.02; b.measure()
    assert b.steps == 1
    _, unc = b.marker_offset(press)
    assert unc
    _, unc_old = b.marker_offset(press - 3600)                                 # older than the history
    assert unc_old


# ---- flags after an unrecovered jump / a rebase (codex-lsl-athena-stage2-report-review.md §2) ---------------
def chunk_flags(out):
    n, rows = 0, []
    for r in out["results"]:
        rows.append((n, r.t_out.size, r.uncertain, r.rebase)); n += r.t_out.size
    return rows


@pytest.mark.parametrize("seed", range(3))
def test_jump_chunk_and_everything_after_it_are_flagged(seed):
    _, out, tl = run(seed, events=[TS.Event("pause", 30.0, 2.0, "lost")])
    rows = chunk_flags(out)
    j = tl.forward_jumps[0][0]
    i = next(k for k, (a, n, *_) in enumerate(rows) if a <= j < a + n)
    assert rows[i][2], "the chunk that jumps must be flagged"
    assert all(f for _, _, f, _ in rows[i:]), "flag must persist after an unrecovered jump"
    assert not any(f for _, _, f, _ in rows[:i - 200])                  # long before the pause: unflagged
    rep = tl.report()
    assert rep["timing_uncertain"] == "pause_unrecovered_after_wait" and rep["counters"]["timing_uncertain_episodes"] == 1
    assert rep["residual_s"]["unflagged"]["n"] + rep["residual_s"]["flagged"]["n"] == rep["samples"]
    assert rep["residual_s"]["unflagged"]["n"] <= j                     # nothing after the jump counted as unflagged


def test_flag_persists_after_rebase():
    _, out, tl = run(3, events=[TS.Event("pause", 30.0, 2.0, "late", drain=1.01)], dur=300)
    rows = chunk_flags(out)
    i = next(k for k, r in enumerate(rows) if r[3] is not None)
    assert all(f for _, _, f, _ in rows[i:])                            # not just the rebase chunk
    assert tl.report()["timing_uncertain"] in ("rebase", "pause_unrecovered_after_wait")


def test_rate_tracking_continues_while_flagged():
    _, out, tl = run(1, events=[TS.Event("pause", 20.0, 2.0, "lost"), TS.Event("rate", 40.0, fs=256.70)], dur=120)
    assert tl.timing_uncertain is not None
    assert abs(tl.report()["fs_estimate"] - 256.70) < 0.05             # drift still followed in the flagged state


def test_only_reset_or_mark_flushed_clear_the_flag():
    _, out, tl = run(2, events=[TS.Event("pause", 20.0, 2.0, "lost")], dur=60)
    assert tl.timing_uncertain is not None
    tl.mark_flushed()
    assert tl.timing_uncertain is None
    p = 1 / FS_NOM
    t = tl.t_last + 0.02
    res = tl.push(t + np.arange(1, 9) * p, t + 9 * p + 0.02)
    assert not res.uncertain
    tl.reset()
    assert tl.timing_uncertain is None and tl.report()["counters"]["timing_uncertain_episodes"] == 0


@pytest.mark.parametrize("events", [
    [TS.Event("pause", 5.0, 0.5, "late")],                                 # burst before the first estimate
    [TS.Event("clock_step", 7.0, -2.0)],                                   # clock step before it
    [TS.Event("pause", 4.0, 0.4, "late"), TS.Event("clock_step", 8.0, 1.5)],
])
@pytest.mark.parametrize("seed", range(3))
def test_start_up_acquisition_is_not_fooled(events, seed):
    """The first period estimate is taken as is: it must not come from a disturbed start-up."""
    _, out, tl = run(seed, events=events, dur=40)
    check_invariants(out)
    fs0 = 1 / tl.period_log[0][1]
    assert abs(fs0 - TS.FS_TRUE["eeg"]) < 0.3                               # < ~0.1 % off the true rate


# ---- quality contract (codex-lsl-athena-stage2-report-round-2.md) --------------------------------------------
def test_invalid_timestamps_are_flagged():
    tl = OnlineTimeline(TimelineConfig(FS_NOM))
    p = 1 / FS_NOM
    r = 10 + np.arange(64) * p
    assert not tl.push(r, r[-1] + 0.02).uncertain
    allnan = tl.push(np.full(8, np.nan), r[-1] + 0.05)
    assert allnan.uncertain and allnan.reason == "invalid_timestamp"
    one = r[-1] + p * np.arange(1, 9); one[3] = np.nan
    res = tl.push(one, one[-1] + 0.02)
    assert res.uncertain and res.reason == "invalid_timestamp" and np.all(np.isfinite(res.t_out))
    rep = tl.report()
    assert rep["counters"]["invalid_samples"] == 9
    n = rep["residual_s"]
    assert n["unflagged"]["n"] + n["flagged"]["n"] + rep["counters"]["invalid_samples"] == rep["samples"]


SCENARIOS_FOR_CONTRACT = [
    [], [TS.Event("pause", 20.0, 2.0, "lost")], [TS.Event("pause", 20.0, 0.5, "late")],
    [TS.Event("pause", 20.0, 2.0, "late", drain=1.2)], [TS.Event("clock_step", 25.013, -2.0)],
]


@pytest.mark.parametrize("events", SCENARIOS_FOR_CONTRACT)
def test_uncertain_intervals_are_disjoint_and_match_every_result(events):
    _, out, tl = run(3, events=events, dur=50)
    iv = tl.report()["uncertain_intervals"]
    assert all(a < b for a, b, _ in iv)
    assert all(iv[i][1] <= iv[i + 1][0] for i in range(len(iv) - 1)), "intervals overlap or go back"
    flagged = np.zeros(tl.n, dtype=object)
    for a, b, reason in iv: flagged[a:b] = reason
    n = 0
    for res in out["results"]:
        k = res.t_out.size
        expect = res.reason if res.uncertain else 0
        assert all(x == expect for x in flagged[n:n + k]), "interval list disagrees with TimelineResult"
        assert res.uncertain == (res.reason is not None)
        n += k


def test_forward_jump_records_where_the_wait_started():
    _, out, tl = run(3, events=[TS.Event("pause", 30.0, 2.0, "lost")])
    (j, size, wait_start), = tl.report()["forward_jumps"]
    assert wait_start < j and abs(size - 2.0) <= G
    reasons = {r for *_, r in tl.report()["uncertain_intervals"]}
    assert {"pause_pending", "pause_unrecovered_after_wait", "timing_uncertain:pause_unrecovered_after_wait"} <= reasons
