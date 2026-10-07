"""Render README screenshots from SYNTHETIC data (no headset needed) into docs/screenshots/.

    PYTHONPATH=src ~/.venvs/musemonitor/bin/python tools/make_screenshots.py
    QT_QPA_PLATFORM=offscreen PYTHONPATH=src ... tools/make_screenshots.py     # headless

Uses a temporary QSettings, so the user's real settings are never touched.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import musemonitor  # noqa: F401 — loads numpy/scipy/brainflow before PySide6
import numpy as np
from PySide6 import QtCore, QtWidgets

from musemonitor.device.spec import athena_spec
from musemonitor.plugins.loader import PROJECT_DIR
from musemonitor.ui import main_window as mw
from musemonitor.ui.style import apply_app_style

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
T0 = 1.79e9
SEC = 120


def pink(rng, n, scale):
    """1/f noise, roughly like resting EEG background."""
    f = np.fft.rfftfreq(n); f[0] = f[1]
    x = np.fft.irfft((rng.standard_normal(f.size) + 1j * rng.standard_normal(f.size)) / np.sqrt(f), n)
    return scale * x / x.std()


def eeg(fs, sec, rng):
    """TP9, AF7, AF8, TP10: 1/f background + waxing/waning alpha (stronger at TP9/TP10) + a few blinks on AF7/AF8."""
    n = fs * sec; t = np.arange(n) / fs
    env = 0.6 + 0.4 * np.sin(2 * np.pi * t / 17) ** 2
    out = []
    for k, a in enumerate((14, 6, 6, 14)):
        x = pink(rng, n, 8) + a * env * np.sin(2 * np.pi * 10.2 * t + k) + 2 * np.sin(2 * np.pi * 50 * t)
        if k in (1, 2):
            for tb in np.arange(3.0, sec, 7.3):
                x += 120 * np.exp(-0.5 * ((t - tb) / 0.09) ** 2)
        out.append(x)
    return np.vstack(out)


def optics(fs, sec, rng):
    """16 optical channels with a pulse whose rate drifts 68–80 bpm, plus slow haemodynamic waves."""
    n = int(fs * sec); t = np.arange(n) / fs
    beats, tb = [], 0.4
    while tb < sec:
        beats.append(tb); tb += 60 / (74 + 6 * np.sin(2 * np.pi * tb / 40)) + 0.02 * rng.standard_normal()
    pulse = sum(np.exp(-0.5 * ((t - b) / 0.08) ** 2) for b in beats)
    x = np.empty((16, n))
    for c in range(16):
        x[c] = 2e5 - (800 + 60 * c) * pulse + 40 * np.sin(2 * np.pi * 0.03 * t + c) + 25 * rng.standard_normal(n)
    return x


def imu(fs, sec, rng):
    n = int(fs * sec); t = np.arange(n) / fs
    acc = np.array([[-0.15], [0.05], [0.98]]) + 0.02 * np.sin(2 * np.pi * 0.2 * t) + 0.005 * rng.standard_normal((3, n))
    gyr = 2 * np.sin(2 * np.pi * 0.2 * t + np.arange(3)[:, None]) + 0.3 * rng.standard_normal((3, n))
    return np.vstack([acc, gyr])


def settle(app, w, rounds=3):
    for _ in range(rounds):
        w.update_analysis(); w.redraw(); w.update_texts(); w.update_quality()
        app.processEvents()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    app = QtWidgets.QApplication(sys.argv)
    apply_app_style(app)
    tmp = tempfile.TemporaryDirectory()
    settings = QtCore.QSettings(str(Path(tmp.name) / "settings.ini"), QtCore.QSettings.IniFormat)
    mw.MainWindow.start_scan = lambda self: None                     # no real BLE scan
    spec = athena_spec()
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[PROJECT_DIR])
    w.resize(1400, 900); w.show(); app.processEvents()

    def shot(name):
        app.processEvents()
        w.grab().save(str(a.out / name)); print("saved", a.out / name)

    w.apply_theme("Light")
    w.connect_page.show_devices([("MuseS-EDAA", "00:00:00:00:00:00", -58)])
    shot("connect.png")

    rng = np.random.default_rng(7)
    fs, ofs, ifs = spec.eeg.fs, spec.optics.fs, spec.imu.fs
    e, o, m = eeg(fs, SEC, rng), optics(ofs, SEC, rng), imu(ifs, SEC, rng)
    w.connected = True; w.device_name = "MuseS-EDAA"; w.on_stream_started()
    for k in range(SEC):
        w.on_data(e[:, k * fs:(k + 1) * fs], T0 + k + 1)
        w.on_optics(o[:, k * ofs:(k + 1) * ofs], T0 + k + 1)
        w.on_imu(m[:, k * ifs:(k + 1) * ifs], T0 + k + 1)
    w.on_battery(82)
    w.set_status(f"Streaming EEG • {fs} Hz  (synthetic data)")
    w.rec_page.set_stream_stats(256.0, SEC * fs)
    for label, dt in (("eyes closed", -52), ("blink", -9.7)):
        w.add_event(label, T0 + SEC + dt)
    settle(app, w); shot("fit_test.png")

    w.stack.setCurrentIndex(mw.PAGE_RECORDING)
    rp = w.rec_page
    rp.range_spin.setValue(10)
    shots = [(0, "signals", 10), (1, "psd", 30), (2, "ppg_hrv", 60)]
    shots += [(i, "ext_" + t.owner, 30) for i, t in enumerate(rp.tab_list) if t.owner in ("band_power", "eye_interaction")]
    for theme in ("Light", "Dark"):
        w.apply_theme(theme)
        for i, name, span in shots:
            if theme == "Dark" and name != "signals": continue
            rp.range_spin.setValue(span); rp.tabs.setCurrentIndex(i)
            settle(app, w); shot(f"{name}{'_dark' if theme == 'Dark' else ''}.png")
    w.connected = False; w.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
