import csv

import numpy as np

from musemonitor.core.store import SignalStore
from musemonitor.storage.events import EventWriter
from musemonitor.storage.recording import Recorder, companion_path


def _rows(path):
    with open(path, newline="") as f:
        return list(csv.reader(f))


def test_recorder_writes_three_files_with_headers(tmp_path, spec):
    path = tmp_path / "rec.csv"
    r = Recorder(path, spec)
    r.write("eeg", np.array([1.0, 2.0]), np.ones((spec.eeg.n, 2)), np.array([7.0, 8.0]))
    r.write("optics", np.array([1.0]), np.zeros((spec.optics.n, 1)))          # no seq → empty cell (nan)
    r.write("imu", np.array([1.0]), np.zeros((spec.imu.n, 1)), np.array([3.0]))
    r.close()
    eeg = _rows(path)
    # existing columns keep their position; package_num is added LAST
    assert eeg[0] == ["timestamp"] + list(spec.eeg.names) + ["package_num"] and len(eeg) == 3
    assert eeg[1][0] == "1.0" and eeg[1][-1] == "7.0" and eeg[2][-1] == "8.0"
    opt = _rows(companion_path(path, "optics"))
    assert opt[0][1] == "O1" and opt[0][-1] == "package_num" and opt[1][-1] == "nan"
    assert _rows(companion_path(path, "imu"))[0][1:] == ["acc_x", "acc_y", "acc_z", "gyro_x", "gyro_y", "gyro_z",
                                                        "package_num"]


def test_event_writer(tmp_path):
    w = EventWriter(tmp_path / "rec.csv")
    w.write(1791296644.081905, "eyes closed")
    rows = _rows(tmp_path / "rec_events.csv")        # flushed at once, readable before close
    w.close()
    assert rows == [["timestamp", "label"], ["1791296644.081905", "eyes closed"]]


def test_store_refilter_and_raw_display(spec):
    st = SignalStore(spec, max_window_sec=4, opt_hist_sec=4)
    x = np.random.default_rng(0).standard_normal((spec.eeg.n, 512)) + 100
    st.add_eeg(x, 123.0)
    assert st.last_ts["eeg"] == 123.0 and st.eeg.n == 512
    st.set_filter(notch=False, band=False)                 # raw → DC removal only
    np.testing.assert_allclose(st.eeg_display(512), x - x.mean(axis=1, keepdims=True))
    st.clear()
    assert st.eeg.n == 0 and st.last_ts["eeg"] is None


# ---- Recording session: own folder + whole-session PSD report ----------------------------------
def test_psd_accumulator_matches_scipy_welch():
    from scipy.signal import welch
    from musemonitor.core.spectral import PsdAccumulator
    x = np.random.default_rng(0).standard_normal((4, 256 * 37 + 77)) * 10 + 50
    acc = PsdAccumulator(256, 4, 4.0)
    for i in range(0, x.shape[1], 53): acc.add(x[:, i:i + 53])     # odd-sized chunks like a real stream
    f, p, n = acc.result()
    f2, p2 = welch(x, 256, nperseg=1024, noverlap=512)
    np.testing.assert_allclose(f, f2); np.testing.assert_allclose(p, p2, rtol=1e-10)
    assert n == 17 and acc.total == x.shape[1]


def test_session_folder_and_report(tmp_path, spec):
    import synthetic as S
    from musemonitor.storage.session import RecordingSession
    s = RecordingSession(spec, root=tmp_path, device="MuseS-TEST", stamp="20261007_101500")
    s2 = RecordingSession(spec, root=tmp_path, stamp="20261007_101500")         # same second → no overwrite
    assert s.folder.name == "muse_20261007_101500" and s2.folder.name == "muse_20261007_101500_2"
    assert s.eeg_path == s.folder / "muse_eeg_20261007_101500.csv"            # CSV name as before
    s.add_event(s.started, "0")
    eeg = S.eeg(spec.eeg.fs, 30)                                              # alpha 10 Hz
    for i in range(0, eeg.shape[1], 12): s.add("eeg", eeg[:, i:i + 12])
    s.add("opt", S.optics(spec.optics.fs, 40, bpm=72))
    s.add("imu", S.imu(spec.imu.fs, 20))
    report = s.finish({"eeg": {"effective_fs": 256.9, "backsteps": 0, "seq_anomalies": 0}})
    html = report.read_text()
    for part in ("EEG power spectral density", "Band power", "Optics / PPG", "IMU power", "AF7", "1e"):
        assert part in html
    assert "<svg" in html and "muse_eeg_" not in html.split("<h2>Files</h2>")[0][-200:]
    rows = list(csv.reader(open(s.folder / "psd_eeg.csv")))
    f = np.array([float(r[0]) for r in rows[1:]]); p = np.array([float(r[1]) for r in rows[1:]])
    assert rows[0][0] == "frequency_hz" and abs(f[np.argmax(p)] - 10) <= 0.25          # alpha peak
    assert {"psd_optics.csv", "psd_imu.csv"} <= {x.name for x in s.folder.iterdir()}


def test_short_session_still_reports(tmp_path, spec):
    from musemonitor.storage.session import RecordingSession
    s = RecordingSession(spec, root=tmp_path)
    s.add("eeg", np.random.default_rng(1).standard_normal((spec.eeg.n, 300)))       # < one 4 s Welch segment
    assert "EEG power spectral density" in s.finish().read_text()


def test_data_root_env_override(tmp_path, monkeypatch):
    from musemonitor.storage import session
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path / "d"))
    assert session.data_root() == tmp_path / "d"
    monkeypatch.delenv("MUSEMONITOR_DATA_DIR")
    assert session.data_root().name == "data"
