"""Raw timestamps, anomalies and the display axis (core.timing) — simulates what was measured on
a real Athena recording on 2026-10-06 22:15: effective fs 256.87 Hz, many samples sharing one ts, IMU ts stepping back."""
import numpy as np
import pytest

from musemonitor.core.timing import StreamClock, ts_vector


def host_timestamps(n, fs_true, t0=1.79e9, burst_max=5, seed=0):
    """Host-receive style timestamps: samples arrive in packets, the whole packet shares the ts of its last sample."""
    rng = np.random.default_rng(seed)
    true_t = t0 + np.arange(n) / fs_true
    ts = np.empty(n); i = 0
    while i < n:
        k = int(rng.integers(1, burst_max + 1))
        ts[i:i + k] = true_t[min(i + k, n) - 1] + 0.004 * rng.random()   # random receive delay ≤ 4 ms
        i += k
    return true_t, ts


def feed(clock, ts, seq=None, chunk=37):
    for i in range(0, len(ts), chunk):
        clock.add(ts[i:i + chunk], None if seq is None else seq[i:i + chunk])


def test_raw_timestamps_are_kept_unchanged():
    c = StreamClock(52, 1000, 30)
    ts = np.array([1.0, 1.02, 1.01, 1.05, 1.04, 1.06])          # two backsteps
    feed(c, ts, chunk=2)
    np.testing.assert_array_equal(c.raw_ts(), ts)
    assert c.backsteps == 2


def test_backstep_across_chunk_boundary():
    c = StreamClock(52, 100, 30)
    c.add(np.array([1.0, 1.1])); c.add(np.array([1.05, 1.2]))
    assert c.backsteps == 1


def test_seq_anomalies_and_histogram():
    c = StreamClock(256, 100, 30)
    seq = np.array([10, 10, 11, 12, 12, 15, 16, 2], dtype=float)  # jump +3 and wrap −14
    feed(c, np.arange(8.0), seq, chunk=3)
    assert c.seq_anomalies == 2
    assert c.seq_deltas[3.0] == 1 and c.seq_deltas[-14.0] == 1 and c.seq_deltas[1.0] == 3 and c.seq_deltas[0.0] == 2


def test_fit_recovers_effective_rate_despite_shared_timestamps():
    fs_true = 256.87
    _, ts = host_timestamps(256 * 60, fs_true)
    c = StreamClock(256, 256 * 120, 30); feed(c, ts)
    assert c.effective_fs == pytest.approx(fs_true, rel=2e-4)
    ax = c.axis(1000)
    assert ax[-1] == 0 and np.all(np.diff(ax) > 0)                 # display axis increases monotonically


def test_marker_and_signal_share_one_time_frame():
    """An event at exactly sample j → its marker must sit exactly at sample j on the plot axis."""
    fs_true, n = 256.87, 256 * 120
    true_t, ts = host_timestamps(n, fs_true)
    c = StreamClock(256, n, 30); feed(c, ts)
    j = n - int(100 * fs_true)                                     # sample ~100 s before the last one
    x_signal = c.axis(n)[j]
    x_marker = true_t[j] - c.ref
    assert abs(x_signal - x_marker) < 0.02
    # the old way (nominal n/fs + last raw ts) is ~0.3 s off at this distance
    old_signal, old_marker = (j - n) / 256, true_t[j] - ts[-1]
    assert abs(old_signal - old_marker) > 0.3


def test_scalar_timestamp_compatibility_and_fallback():
    v = ts_vector(10.0, 4, 4)
    np.testing.assert_allclose(v, [9.25, 9.5, 9.75, 10.0])
    c = StreamClock(64, 100, 30)
    c.add(np.array([5.0]))                                         # 1 sample → nominal fs is used
    assert c.effective_fs == pytest.approx(64) and c.ref == 5.0
