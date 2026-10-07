"""UI smoke test (offscreen): feed synthetic signals, walk through tabs/themes, mark events."""
import pytest
from PySide6 import QtCore, QtTest, QtWidgets

import synthetic as S
from musemonitor.storage.events import EventWriter
from musemonitor.ui import main_window as mw
from musemonitor.ui.widgets.event_dialog import EventDialog

T0 = 1.79e9


@pytest.fixture
def window(qapp, spec, settings, monkeypatch):
    monkeypatch.setattr(mw.MainWindow, "start_scan", lambda self: None)     # no real BLE scan
    monkeypatch.setattr(mw.MainWindow, "isActiveWindow", lambda self: True)
    w = mw.MainWindow(spec, settings=settings, extension_dirs=[]); w.resize(1300, 900); w.show()
    w.connected = True
    sec = 90
    fs, ofs, ifs = spec.eeg.fs, spec.optics.fs, spec.imu.fs
    e, o, m = S.eeg(fs, sec), S.optics(ofs, sec), S.imu(ifs, sec)
    for k in range(sec):                                # feed one second at a time like a real stream
        w.on_data(e[:, k * fs:(k + 1) * fs], T0 + k + 1)
        w.on_optics(o[:, k * ofs:(k + 1) * ofs], T0 + k + 1)
        w.on_imu(m[:, k * ifs:(k + 1) * ifs], T0 + k + 1)
    w.stack.setCurrentIndex(mw.PAGE_RECORDING)
    yield w
    w.connected = False; w.close()


def test_all_tabs_and_themes_render(window):
    rp = window.rec_page
    rp.range_spin.setValue(20)
    for theme in ("Light", "Dark"):
        window.apply_theme(theme)
        for i in range(rp.tabs.count()):
            rp.tabs.setCurrentIndex(i); window.update_analysis(); window.redraw(); window.update_texts()
    window.update_quality()
    assert [q for q, *_ in window.last_qs] == ["Good"] * 4
    ppg = rp.tab_list[2]; ppg.tiles_t = 0
    rp.tabs.setCurrentIndex(2); window.update_analysis()
    assert ppg.tiles["hr"].text() == "75"
    assert rp.tab_list[1].levels is not None                  # spectrogram computed


def test_space_marks_event_and_saves_when_recording(window, monkeypatch, tmp_path):
    monkeypatch.setattr(mw, "ask_event_label", lambda parent, t: "blink")
    monkeypatch.setattr(mw.time, "time", lambda: T0 + 85)
    window.ev_writer = EventWriter(tmp_path / "rec.csv")
    rp = window.rec_page
    rp.record_btn.setEnabled(True); rp.record_btn.setFocus()
    QtTest.QTest.keyClick(rp.record_btn, QtCore.Qt.Key_Space)    # Space on the button: opens the event prompt, does not press it
    assert not window.recording
    assert len(window.markers) == 1
    line, tg = window.markers.events[0][2][0]
    assert line.value() == pytest.approx(-5) and line.isVisible()
    window._close_events_file()
    assert (tmp_path / "rec_events.csv").read_text().splitlines()[1].endswith(",blink")
    assert "blink" in rp.ev_label.text() and "not saved" not in rp.ev_label.text()


@pytest.mark.parametrize("key, accepted", [(QtCore.Qt.Key_Return, 1), (QtCore.Qt.Key_Escape, 0)])
def test_event_dialog_keys(qapp, key, accepted):
    d = EventDialog(None, T0); d.show()
    QtTest.QTest.keyClicks(d.edit, "eyes closed"); QtTest.QTest.keyClick(d.edit, key)
    assert d.result() == accepted and d.label() == "eyes closed"


def test_event_dialog_empty_label_not_accepted(qapp):
    d = EventDialog(None, T0); d.show()
    QtTest.QTest.keyClick(d.edit, QtCore.Qt.Key_Return)
    assert d.isVisible() and not d.done_btn.isEnabled()
    d.reject()


def test_checkbox_indicator_aligned_with_label_and_clickable(qapp):
    """Checkbox indicator aligned with the label's cap-height centre, does not jump when toggled, still clickable."""
    from PySide6 import QtWidgets
    QS = QtWidgets.QStyle
    cb = QtWidgets.QCheckBox("Filtered 1–40 Hz"); cb.adjustSize(); cb.show()
    centers = []
    for checked in (True, False):
        cb.setChecked(checked)
        opt = QtWidgets.QStyleOptionButton(); cb.initStyleOption(opt)
        ind = cb.style().subElementRect(QS.SE_CheckBoxIndicator, opt, cb)
        fm = cb.fontMetrics()
        cap_center = (cb.height() - fm.height()) / 2 + fm.ascent() - fm.capHeight() / 2
        assert abs((ind.top() + ind.height() / 2) - cap_center) <= 0.5 + 1e-9
        assert cb.rect().contains(ind)
        centers.append(ind.center())
    assert centers[0] == centers[1]                       # does not jump when toggled
    QtTest.QTest.mouseClick(cb, QtCore.Qt.LeftButton, pos=centers[0])
    assert cb.isChecked()                                 # clicking the centre of the box still toggles it
    cb.close()


def test_time_axis_follows_only_the_time_range_input(window):
    """The x axis of time plots changes only through the Time range box; mouse/menu cannot move it."""
    rp = window.rec_page
    rp.range_spin.setValue(15)
    timed = window.ctx.plots.time_plots
    assert timed and all(p.getViewBox().state["mouseEnabled"] == [False, True] for p in timed)  # y still adjustable
    p = rp.signals_tab.plots[0]
    p.getViewBox().scaleBy(x=0.5)                 # like a mouse zoom
    p.getViewBox().translateBy(x=3)               # like a mouse drag
    p.autoRange()                                 # like "View All" / the A button
    for q in timed:
        lo, hi = q.getViewBox().viewRange()[0]
        assert lo == pytest.approx(-15) and hi == pytest.approx(0)
    assert not rp.range_spin.keyboardTracking()   # typed numbers apply on Enter / focus-out
    fit = window.fit_page.graphics.getItem(0, 1)
    fit.getViewBox().scaleBy(x=0.5)
    assert fit.getViewBox().viewRange()[0] == pytest.approx([-4, 0])


class FakeWorker:
    def __init__(self): self.calls = []
    def start_recording(self, path): self.calls.append(("start", path))
    def stop_recording(self): self.calls.append(("stop",))


def test_record_saves_session_folder_with_start_event_and_report(window, tmp_path, monkeypatch):
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path))
    window.worker, window.streaming, window.device_name = FakeWorker(), True, "MuseS-TEST"
    window.toggle_record()                                   # Start: no file dialog any more
    folder = window.session.folder
    assert folder.parent == tmp_path and folder.name.startswith("muse_")
    assert window.worker.calls == [("start", str(folder / f"muse_eeg_{folder.name[5:]}.csv"))]
    events = (folder / f"muse_eeg_{folder.name[5:]}_events.csv").read_text().splitlines()
    assert events[1].endswith(",0")                          # event "0" added automatically at start
    assert window.markers.events[-1][1] == "0"
    import synthetic as S
    sp = window.spec
    window.on_data(S.eeg(sp.eeg.fs, 10), T0 + 100)           # data while recording → whole-session PSD
    window.toggle_record()                                   # Stop: no end event
    assert window.worker.calls[-1] == ("stop",) and window.session is None
    assert (folder / "report.html").exists(), window.rec_page.status_label.text()
    assert len((folder / f"muse_eeg_{folder.name[5:]}_events.csv").read_text().splitlines()) == 2
    assert "EEG power spectral density" in (folder / "report.html").read_text()
    assert (folder / "psd_eeg.csv").exists()
    assert "report.html" in window.rec_page.status_label.text()
    window.worker = None; window.streaming = False
