"""Extension API 3 (debate/lsl-athena-proposal.md, stage 1): per-sample timestamp hooks for live data.

on_eeg_samples / on_optics_samples / on_imu_samples receive (x, ts_raw) with ts_raw = exactly the vector the
worker delivered and the CSV records. API 1/2 hooks are unchanged; review windows never call the new hooks."""
import csv
import textwrap

import numpy as np
import pytest

import synthetic as S
from musemonitor.device.profiles import athena_profile
from musemonitor.plugins.api import API_VERSION, Extension
from musemonitor.storage.reader import inspect, load, locate
from musemonitor.storage.recording import Recorder
from musemonitor.ui import main_window as mw
from musemonitor.ui.review_window import ReviewWindow
from test_review import host_ts, write_session

T0 = 1.79e9

SAMPLES = '''
from musemonitor.plugins.api import Extension

class Samples(Extension):
    requires_api = {api}
    supports_review = True
    def activate(self, app): self.calls = []
    def on_eeg(self, x, ts): self.calls.append(("eeg", x.shape[1], ts))
    def on_eeg_samples(self, x, ts_raw): self.calls.append(("eeg_samples", x.copy(), ts_raw))
    def on_optics_samples(self, x, ts_raw): self.calls.append(("opt_samples", x.copy(), ts_raw))
    def on_imu_samples(self, x, ts_raw): self.calls.append(("imu_samples", x.copy(), ts_raw))

EXTENSION = Samples
'''

OLD_ONLY = '''
from musemonitor.plugins.api import Extension

class OldOnly(Extension):
    def activate(self, app): self.calls = []
    def on_eeg(self, x, ts): self.calls.append((x.shape[1], ts))

EXTENSION = OldOnly
'''

BROKEN = '''
from musemonitor.plugins.api import Extension

class Broken(Extension):
    def on_eeg_samples(self, x, ts_raw): raise RuntimeError("boom")

EXTENSION = Broken
'''


def write(d, name, body):
    (d / name).write_text(textwrap.dedent(body), encoding="utf-8")


@pytest.fixture
def window(qapp, spec, settings, monkeypatch, tmp_path):
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    d = tmp_path / "exts"; d.mkdir()
    write(d, "samples.py", SAMPLES.format(api=3))
    write(d, "old_only.py", OLD_ONLY)
    write(d, "broken.py", BROKEN)
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(d)])
    yield w
    w.close()


def inst(w, ext_id):
    return next(r for r in w.extensions.records if r.id == ext_id).instance


def test_version_and_requires_api(qapp, spec, settings, monkeypatch, tmp_path):
    assert API_VERSION == 3
    for h in ("on_eeg_samples", "on_optics_samples", "on_imu_samples"):
        assert hasattr(Extension, h)
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    d = tmp_path / "v"; d.mkdir()
    write(d, "needs3.py", SAMPLES.format(api=3)); write(d, "needs4.py", SAMPLES.format(api=4))
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(d)])
    st = {r.id: r.status for r in w.extensions.records}
    assert st == {"needs3": "active", "needs4": "incompatible"}
    w.close()


def test_per_sample_timestamps_are_exactly_what_the_worker_delivered(window, spec):
    fs = spec.eeg.fs
    x = S.eeg(fs, 2)
    ts = host_ts(x.shape[1], 256.87, start=T0)                         # packets share a timestamp, like Athena
    for i in range(0, x.shape[1], 37):
        window.on_data(x[:, i:i + 37], ts[i:i + 37])
    got = [c for c in inst(window, "samples").calls if c[0] == "eeg_samples"]
    assert np.array_equal(np.concatenate([c[2] for c in got]), ts)     # bit-for-bit, duplicates kept
    assert np.array_equal(np.concatenate([c[1] for c in got], axis=1), x)
    assert all(c[2].dtype == np.float64 and len(c[2]) == c[1].shape[1] for c in got)


def test_same_values_as_the_csv(window, spec, tmp_path):
    """The vector a v3 hook receives is the one Recorder writes — compared after a CSV round trip."""
    fs = spec.eeg.fs
    x = S.eeg(fs, 1); ts = host_ts(x.shape[1], 256.87, start=T0)
    rec = Recorder(tmp_path / "rec.csv", spec)
    for i in range(0, x.shape[1], 64):
        window.on_data(x[:, i:i + 64], ts[i:i + 64]); rec.write("eeg", ts[i:i + 64], x[:, i:i + 64], None)
    rec.close()
    csv_ts = np.array([float(r[0]) for r in list(csv.reader(open(tmp_path / "rec.csv")))[1:]])
    hook_ts = np.concatenate([c[2] for c in inst(window, "samples").calls if c[0] == "eeg_samples"])
    assert np.array_equal(hook_ts, csv_ts)


def test_old_hooks_unchanged_and_called_first(window, spec):
    fs = spec.eeg.fs
    x = S.eeg(fs, 1); ts = T0 + np.arange(1, fs + 1) / fs
    window.on_data(x, ts)
    calls = inst(window, "samples").calls
    assert [c[0] for c in calls] == ["eeg", "eeg_samples"]
    assert calls[0][2] == ts[-1] and isinstance(calls[0][2], float)       # API 1: last-sample float
    assert inst(window, "old_only").calls == [(fs, ts[-1])]


def test_all_three_streams(window, spec):
    o, m = S.optics(spec.optics.fs, 1), S.imu(spec.imu.fs, 1)
    to = T0 + np.arange(o.shape[1]) / spec.optics.fs
    tm = T0 + np.arange(m.shape[1]) / spec.imu.fs
    tm[10] = tm[9] - 0.0003                                               # IMU timestamps can step back: passed as is
    window.on_optics(o, to); window.on_imu(m, tm)
    calls = {c[0]: c for c in inst(window, "samples").calls}
    assert np.array_equal(calls["opt_samples"][2], to) and np.array_equal(calls["opt_samples"][1], o)
    assert np.array_equal(calls["imu_samples"][2], tm) and np.array_equal(calls["imu_samples"][1], m)


def test_scalar_timestamp_from_an_old_worker_is_expanded(window, spec):
    fs = spec.eeg.fs
    x = S.eeg(fs, 1)
    window.on_data(x[:, :50], T0)
    ts = next(c[2] for c in inst(window, "samples").calls if c[0] == "eeg_samples")
    assert len(ts) == 50 and ts[-1] == T0 and np.allclose(np.diff(ts), 1 / fs)


def test_no_cost_when_no_extension_uses_v3(qapp, spec, settings, monkeypatch, tmp_path):
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    d = tmp_path / "old"; d.mkdir(); write(d, "old_only.py", OLD_ONLY)
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[str(d)])
    assert not w.extensions.wants("on_eeg_samples")
    monkeypatch.setattr(mw, "ts_vector", lambda *a: pytest.fail("timestamps prepared with no v3 listener"))
    w.on_data(S.eeg(spec.eeg.fs, 1), T0 + np.arange(spec.eeg.fs) / spec.eeg.fs)
    assert len(inst(w, "old_only").calls) == 1
    w.close()


def test_error_in_v3_hook_is_isolated(window, spec):
    fs = spec.eeg.fs
    window.on_data(S.eeg(fs, 1), T0 + np.arange(fs) / fs)
    rec = next(r for r in window.extensions.records if r.id == "broken")
    assert rec.status == "error" and "on_eeg_samples" in rec.error
    window.on_data(S.eeg(fs, 1), T0 + 1 + np.arange(fs) / fs)            # others keep receiving data
    assert sum(1 for c in inst(window, "samples").calls if c[0] == "eeg_samples") == 2


def test_review_windows_never_call_v3_hooks(qapp, spec, settings, tmp_path):
    d = tmp_path / "exts"; d.mkdir()
    write(d, "samples.py", SAMPLES.format(api=3))
    folder, _ = write_session(spec, tmp_path / "s", sec=10, events=())
    sess = load(inspect(locate(folder), [athena_profile()]))
    w = ReviewWindow(sess, settings, profile=athena_profile(), extension_dirs=[str(d)], replay=False)
    w.start_replay(); w.replay.run(); w._replay_finished()
    kinds = {c[0] for c in inst(w, "samples").calls}
    assert kinds == {"eeg"}                                               # replay uses the API 1 hooks only
    w.close()
