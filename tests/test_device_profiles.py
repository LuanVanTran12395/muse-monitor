"""Device profiles: Athena (built in) + optional ``musemonitor_*`` device libraries.

The tests create a small device library on the fly (``musemonitor_demo``: 2 EEG channels Fp1/Fp2,
3 optical channels, no IMU) whose worker streams synthetic data — no BLE, no hardware."""
import csv
import sys
import textwrap
import time

import numpy as np
import pytest
from PySide6 import QtWidgets

from musemonitor.device.profiles import athena_profile, discover_profiles
from musemonitor.ui import main_window as mw

T0 = 1.79e9

DEMO_LIB = '''
"""Synthetic two-channel headset used by the tests."""
import threading
import time

import numpy as np
from PySide6 import QtCore

from musemonitor.device.profiles import DeviceProfile
from musemonitor.device.spec import DeviceSpec, StreamSpec

EEG_FS, OPT_FS = 250, 100


def demo_spec():
    return DeviceSpec(
        board_id=None,
        eeg=StreamSpec(preset=None, fs=EEG_FS, rows=[0, 1], ts_row=None, names=["Fp1", "Fp2"]),
        optics=StreamSpec(preset=None, fs=OPT_FS, rows=[0, 1, 2], ts_row=None, names=["PPG", "NIR760", "NIR850"]),
        imu=StreamSpec(preset=None, fs=52, rows=[], ts_row=None, names=[]),
        battery_row=None, n_acc=0)


class DemoWorker(QtCore.QObject):
    status = QtCore.Signal(str)
    data_ready = QtCore.Signal(object, object, object)
    optics_ready = QtCore.Signal(object, object, object)
    imu_ready = QtCore.Signal(object, object, object)
    battery = QtCore.Signal(float)
    stream_started = QtCore.Signal()
    stream_stats = QtCore.Signal(float, int)
    stopped = QtCore.Signal()

    def __init__(self, device, spec):
        super().__init__()
        self.device, self.spec, self._stop = device, spec, threading.Event()

    def request_stop(self): self._stop.set()
    def start_recording(self, path): pass
    def stop_recording(self): pass

    @QtCore.Slot()
    def run(self):
        self.stream_started.emit()
        k, t = 25, 1.79e9
        while not self._stop.is_set():
            ts = t + np.arange(1, k + 1) / EEG_FS; t = ts[-1]
            self.data_ready.emit(50 * np.sin(2 * np.pi * 10 * ts)[None, :].repeat(2, 0), ts, None)
            self.optics_ready.emit(np.full((3, 10), 2e5), t - np.arange(10)[::-1] / OPT_FS, None)
            time.sleep(0.005)
        self.stopped.emit()


def _profile():
    return DeviceProfile(
        id="demo", name="Demo 2ch", make_spec=demo_spec, make_worker=DemoWorker,
        matches=lambda n: (n or "").startswith("DEMO-"),
        electrode_positions={"Fp1": (-0.2, -0.75), "Fp2": (0.2, -0.75)},
        fnirs=dict(pair=(1, 2), labels=("fNIRS  λ 760 nm:", "λ 850 nm:"),
                   ext=((1486.6, 3843.7), (1058.0, 691.3)), dpf=6.0, dist=3.0),
        note="Synthetic test device")


DEVICE_PROFILE = _profile
'''


@pytest.fixture
def demo_lib(tmp_path, monkeypatch):
    pkg = tmp_path / "lib" / "musemonitor_demo"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(textwrap.dedent(DEMO_LIB))
    monkeypatch.syspath_prepend(str(tmp_path / "lib"))
    yield
    sys.modules.pop("musemonitor_demo", None)


def demo_profile():
    return next(p for p in discover_profiles() if p.id == "demo")


def test_discovery_finds_device_library(demo_lib):
    assert [p.id for p in discover_profiles()] == ["muse_athena", "demo"]


def test_without_libraries_only_athena():
    assert [p.id for p in discover_profiles()] == ["muse_athena"]


def test_broken_library_is_skipped(tmp_path, monkeypatch):
    pkg = tmp_path / "musemonitor_broken"; pkg.mkdir()
    (pkg / "__init__.py").write_text("raise RuntimeError('boom')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        assert [p.id for p in discover_profiles()] == ["muse_athena"]
    finally:
        sys.modules.pop("musemonitor_broken", None)


@pytest.fixture
def make(qapp, settings, monkeypatch):
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    made = []

    def build(profile, profiles=None, ext_dirs=()):
        w = mw.MainWindow(profile.make_spec(), settings=settings, profile=profile, profiles=profiles,
                          extension_dirs=[str(d) for d in ext_dirs])
        w.resize(1200, 860); w.show(); made.append(w)
        return w
    yield build
    for w in made: w.connected = False; w.close()


class FakeWorker:
    def __init__(self): self.calls = []
    def start_recording(self, path): self.calls.append(("start", path))
    def stop_recording(self): self.calls.append(("stop",))


def test_window_is_configured_for_the_device(demo_lib, make, tmp_path, monkeypatch):
    import synthetic as S
    from musemonitor.plugins.loader import PROJECT_DIR
    w = make(demo_profile(), ext_dirs=[PROJECT_DIR])
    st = {r.id: r.status for r in w.extensions.records}
    assert st["eye_interaction"] == "not applicable" and st["head_motion_plus"] == "not applicable"
    assert st["band_power"] == "active" and st["hello_world"] == "active"
    assert "Demo 2ch" in w.windowTitle()
    assert set(w.fit_page.head.pos) >= {"Fp1", "Fp2"} and set(w.fit_page.head.q) == {"Fp1", "Fp2"}
    ppg = w.rec_page.tab_list[2]
    assert ppg.fn_ch1.currentText() == "NIR760" and ppg.fn_ch2.currentText() == "NIR850"
    fs, ofs = w.spec.eeg.fs, w.spec.optics.fs
    eeg, opt = S.eeg(fs, 30, n_ch=2), S.optics(ofs, 30, n_ch=3)
    for k in range(30):
        w.on_data(eeg[:, k * fs:(k + 1) * fs], T0 + k + 1)
        w.on_optics(opt[:, k * ofs:(k + 1) * ofs], T0 + k + 1)
    w.stack.setCurrentIndex(mw.PAGE_RECORDING)
    for th in ("Light", "Dark"):
        w.apply_theme(th)
        for i in range(w.rec_page.tabs.count()):
            w.rec_page.tabs.setCurrentIndex(i); w.update_analysis(); w.redraw(); w.update_texts()
    w.update_quality()
    assert [q for q, *_ in w.last_qs] == ["Good", "Good"]
    # record: CSV columns follow the device spec, no _imu.csv, report works
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path))
    w.worker, w.streaming, w.device_name = FakeWorker(), True, "DEMO-01"
    w.toggle_record(); folder = w.session.folder
    from musemonitor.storage.recording import Recorder
    Recorder(w.rec_path, w.spec).close()                     # what a device worker creates
    w.on_data(S.eeg(fs, 10, n_ch=2), T0 + 40)
    w.toggle_record()
    stamp = folder.name[5:]
    assert next(csv.reader(open(folder / f"muse_eeg_{stamp}.csv"))) == ["timestamp", "Fp1", "Fp2"]
    assert not (folder / f"muse_eeg_{stamp}_imu.csv").exists()
    html = (folder / "report.html").read_text()
    assert "Fp1" in html and "IMU power" not in html
    w.worker = None; w.streaming = False


def test_choosing_another_device_type_requests_its_window(demo_lib, make):
    w = make(athena_profile(), profiles=[athena_profile(), demo_profile()])
    w.connect_page.show_devices([("MuseS-EDAA", "a", -44, "muse_athena"), ("DEMO-01", "b", -50, "demo")])
    assert "[Demo 2ch]" in w.connect_page.dev_list.item(1).text()
    w.connect_page.dev_list.setCurrentRow(1); w.connect_page.dev_list.item(1).setSelected(True)
    got = []
    w.switch_requested.connect(lambda pid, dev: got.append((pid, dev)))
    w.connect_selected()
    assert got == [("demo", "DEMO-01")] and w.worker is None and not w.connected


def test_window_manager_switches_and_connects(demo_lib, qapp, settings, monkeypatch):
    from musemonitor.app import WindowManager
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)
    connected = []
    monkeypatch.setattr(mw.MainWindow, "connect_to", lambda self, name: connected.append((self.profile.id, name)))
    m = WindowManager([athena_profile(), demo_profile()], settings=settings, window_kwargs=dict(extension_dirs=[]))
    first = m.open()
    assert first.profile.id == "muse_athena"
    first.switch_requested.emit("demo", "DEMO-01")
    for _ in range(3): qapp.processEvents()
    assert m.window is not first and m.window.profile.id == "demo" and m.window.spec.eeg.n == 2
    assert connected == [("demo", "DEMO-01")] and not first.isVisible()
    settings.setValue("device_profile", "demo")
    m.window.close()
    m2 = WindowManager([athena_profile()], settings=settings, window_kwargs=dict(extension_dirs=[]))
    assert m2.open().profile.id == "muse_athena"                         # library gone → Athena
    m2.window.close()


def test_device_worker_streams_into_the_app(demo_lib, make):
    """The library's own worker runs in its thread and feeds the store through the usual signals."""
    w = make(demo_profile())
    w.connect_to("DEMO-01")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and w.ctx.store.eeg.n < 600:
        QtWidgets.QApplication.processEvents(); time.sleep(0.01)
    assert w.streaming and w.ctx.store.eeg.n >= 600 and w.ctx.store.opt.n > 0
    assert np.abs(w.ctx.store.eeg.get()).max() == pytest.approx(50, abs=1)
    w.disconnect_device()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and w.connected:
        QtWidgets.QApplication.processEvents(); time.sleep(0.01)
    assert not w.connected
