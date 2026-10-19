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
    monkeypatch.setattr(mw, "ask_event_label", lambda parent, t, last="": "blink")
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


# ---- V1–V3 (User_Analysis UX review): recording visibility, confirmations, fast event marking -------------
def start_recording(window, tmp_path, monkeypatch):
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path))
    window.worker, window.streaming, window.device_name = FakeWorker(), True, "MuseS-TEST"
    window.rec_page.set_record_enabled(True)
    window.toggle_record()


def test_recording_state_is_visible_on_button_and_title(window, tmp_path, monkeypatch):
    rp = window.rec_page
    assert rp.record_btn.text() == rp.START_TEXT and not rp.record_btn.styleSheet()
    start_recording(window, tmp_path, monkeypatch)
    assert rp.record_btn.text().startswith("■ Stop recording · 0:0")
    assert window.ctx.th["q"]["Bad"] in rp.record_btn.styleSheet()
    assert window.windowTitle().startswith("● REC 0:0")
    rp.rec_t0 -= 3725; window.update_texts()                  # 1 h 2 min 5 s later
    assert rp.record_btn.text().endswith("1:02:05") and "● REC 1:02:05" in window.windowTitle()
    window.apply_theme("Light")                               # the red follows the theme
    assert window.ctx.th["q"]["Bad"] in rp.record_btn.styleSheet()
    window.toggle_record()
    assert rp.record_btn.text() == rp.START_TEXT and not rp.record_btn.styleSheet()
    assert window.windowTitle() == window.base_title


def test_disconnect_is_away_from_record_button(window):
    controls = window.rec_page.layout().itemAt(0).layout()
    widgets = [controls.itemAt(i).widget() for i in range(controls.count()) if controls.itemAt(i).widget()]
    rp = window.rec_page
    assert widgets[0] is rp.record_btn and widgets[-1] is rp.disc_btn


@pytest.mark.parametrize("entry, action", [("user_disconnect", "disconnect_device"),
                                           ("user_new_session", "new_session"), ("user_close", "close")])
def test_user_actions_ask_before_stopping_a_recording(window, tmp_path, monkeypatch, entry, action):
    calls, answer = [], [False]
    monkeypatch.setattr(window, action, lambda: calls.append(action))
    getattr(window, entry)()
    assert calls == [action]                                 # not recording: no dialog, goes straight on
    start_recording(window, tmp_path, monkeypatch)
    monkeypatch.setattr(window, "confirm_stop_recording", lambda what: (calls.append("ask"), answer[0])[1])
    calls.clear()
    getattr(window, entry)()
    assert calls == ["ask"] and window.recording             # "Keep recording" → nothing happens
    answer[0] = True; calls.clear()
    getattr(window, entry)()
    assert calls == ["ask", action]
    monkeypatch.undo(); window.toggle_record()


def test_confirm_defaults_to_keep_recording(window, tmp_path, monkeypatch):
    assert window.confirm_stop_recording("Disconnecting")    # not recording: no dialog
    start_recording(window, tmp_path, monkeypatch)
    seen = []

    def press(key):
        box = QtWidgets.QApplication.activeModalWidget()
        seen.append(box.text()); QtTest.QTest.keyClick(box, key)
    for key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Escape):
        QtCore.QTimer.singleShot(50, lambda k=key: press(k))
        assert not window.confirm_stop_recording("Disconnecting")
    assert "will stop it" in seen[0] and window.recording
    window.toggle_record()


def test_digit_keys_mark_quick_events_but_not_while_typing(window, monkeypatch):
    monkeypatch.setattr(mw, "ask_event_label", lambda *a, **k: pytest.fail("1–9 must not open the prompt"))
    rp = window.rec_page
    rp.tabs.setFocus()
    QtTest.QTest.keyClick(rp.tabs, QtCore.Qt.Key_3)
    QtTest.QTest.keyClick(rp.tabs, QtCore.Qt.Key_7, QtCore.Qt.KeypadModifier)
    QtTest.QTest.keyClick(rp.tabs, QtCore.Qt.Key_0)            # 0 is reserved for the start event
    QtTest.QTest.keyClick(rp.tabs, QtCore.Qt.Key_2, QtCore.Qt.ControlModifier)
    assert [e[1] for e in window.markers.events] == ["3", "7"]
    rp.range_spin.setFocus(); rp.range_spin.lineEdit().selectAll()
    QtTest.QTest.keyClicks(rp.range_spin.lineEdit(), "25")     # typing a time range never marks
    assert len(window.markers) == 2 and rp.range_spin.lineEdit().text().startswith("25")


def test_space_prompt_is_prefilled_with_the_last_label(window, monkeypatch):
    seen = []
    monkeypatch.setattr(mw, "ask_event_label", lambda parent, t, last="": (seen.append(last), "blink")[1])
    window.mark_event(); window.add_event("0"); window.mark_event()
    assert seen == ["", "blink"]                              # the automatic start event "0" is not remembered


def test_event_dialog_prefill_return_repeats_typing_replaces(qapp):
    d = EventDialog(None, T0, "stimulus A"); d.show()
    assert d.done_btn.isEnabled() and d.edit.selectedText() == "stimulus A"
    QtTest.QTest.keyClick(d.edit, QtCore.Qt.Key_Return)
    assert d.result() == 1 and d.label() == "stimulus A"
    d = EventDialog(None, T0, "stimulus A"); d.show()
    QtTest.QTest.keyClicks(d.edit, "B"); QtTest.QTest.keyClick(d.edit, QtCore.Qt.Key_Return)
    assert d.label() == "B"


# ---- V4–V7 (User_Analysis UX review) ------------------------------------------------------------------
GOOD = [("Good", 8.0, 2.0)] * 4


def test_details_row_hidden_by_default_and_remembered(window):
    rp = window.rec_page
    assert not rp.details.isVisible() and rp.details_btn.text() == "Details ▾"
    assert rp.ev_label.isVisible() and rp.health_label.parent() is not rp.details
    rp.details_btn.click()
    assert rp.details.isVisible() and rp.rate_label.isVisible() and rp.last_label.isVisible()
    assert str(window.ctx.settings.value("show_details")).lower() == "true"
    from musemonitor.ui.pages.recording_page import RecordingPage
    again = RecordingPage(window.ctx); again.show()
    assert again.details_btn.isChecked() and again.details.isVisible()
    again.close(); rp.details_btn.click()


def test_timing_shown_in_plain_words(window, monkeypatch):
    rp = window.rec_page
    ok = {k: dict(effective_fs=256.0, backsteps=0, seq_anomalies=0, seq_deltas={}) for k in ("eeg", "opt", "imu")}
    monkeypatch.setattr(window.ctx.store, "health", lambda: ok)
    rp._update_health()
    assert "OK" in rp.health_label.text()
    bad = {**ok, "eeg": dict(ok["eeg"], backsteps=3), "imu": dict(ok["imu"], seq_anomalies=1)}
    monkeypatch.setattr(window.ctx.store, "health", lambda: bad)
    rp._update_health()
    text, tip = rp.health_label.text(), rp.health_label.toolTip()
    assert "⚠ 2 issues" in text and "↓" not in text and "seq?" not in text
    assert "EEG: timestamp went backwards 3×" in tip and "IMU: packet counter jumped 1×" in tip


def test_channel_quality_label_has_units_and_names(window):
    from musemonitor.ui.widgets.indicators import quality_html
    html = quality_html("TP9", ("Good", 8.2, 2.4), window.ctx.th)
    assert "signal 8 µV" in html and "50 Hz noise 2 µV" in html and "50Hz" not in html


def test_connect_page_single_device_is_ready_to_connect(qapp, spec, settings):
    from musemonitor.ui.context import ViewContext
    from musemonitor.ui.pages import ConnectPage
    from musemonitor.ui.plotkit import PlotRegistry
    from musemonitor.core.store import SignalStore
    ctx = ViewContext(spec=spec, store=SignalStore(spec), settings=settings, plots=PlotRegistry(8.0))
    page = ConnectPage(ctx); page.show()
    assert not page.conn_btn.isEnabled() and not page.dev_list.styleSheet()   # palette-driven: follows the theme
    page.set_scanning(True)
    assert page.scan_busy.isVisible() and not page.scan_btn.isEnabled()
    page.show_devices([("MuseS-EDAA", "addr", -58)])
    page.set_scanning(False)
    assert not page.scan_busy.isVisible()
    assert page.device_name() == "MuseS-EDAA" and page.conn_btn.isEnabled()
    page.dev_name.clear(); page.dev_list.clearSelection()
    page.show_devices([("MuseS-A", "a", -50), ("MuseS-B", "b", -60)])
    assert not page.dev_list.selectedItems() and not page.conn_btn.isEnabled()   # two: the user picks
    page.close()


def test_accept_with_bad_contact_asks_and_good_contact_does_not(window, monkeypatch):
    fp = window.fit_page
    window.stack.setCurrentIndex(mw.PAGE_FIT)
    asked, answer = [], [False]
    monkeypatch.setattr(fp, "confirm_weak_contact", lambda weak: (asked.append(weak), answer[0])[1])
    fp.set_quality([("Bad", 90.0, 30.0), ("Fair", 30.0, 5.0)] + GOOD[:2])
    fp.accept_btn.click()
    assert asked == [[("TP9", "Bad")]] and window.stack.currentIndex() == mw.PAGE_FIT and fp.accepted is None
    answer[0] = True; fp.accept_btn.click()
    assert window.stack.currentIndex() == mw.PAGE_RECORDING
    assert fp.accepted["channels"]["TP9"]["level"] == "Bad" and fp.accepted["all_good"] is False
    asked.clear(); window.stack.setCurrentIndex(mw.PAGE_FIT)
    fp.set_quality(GOOD); fp.accept_btn.click()
    assert asked == [] and fp.accepted["all_good"] is True                  # all Good: straight through
    fp.set_quality(None)
    assert fp.weak_channels() == [(n, "—") for n in window.spec.eeg.names]   # nothing measured yet counts as weak


def test_fit_test_quality_is_saved_in_session_json(window, tmp_path, monkeypatch):
    import json
    fp = window.fit_page
    fp.set_quality(GOOD); fp.accept_btn.click()
    start_recording(window, tmp_path, monkeypatch)
    meta = json.loads((window.session.folder / "session.json").read_text())
    window.toggle_record()
    assert meta["schema"] == 1 and meta["fit_test"]["all_good"] is True and meta["fit_test"]["accepted"] is True
    assert meta["fit_test"]["channels"]["AF7"] == dict(level="Good", signal_rms_uv=8.0, mains_rms_uv=2.0)
    fp.set_device("MuseS-OTHER")
    assert fp.accepted is None                                              # a new stream needs a new fit-test


@pytest.mark.parametrize("theme", ["Dark", "Light"])
def test_text_on_quality_colours_is_readable(theme):
    from musemonitor.ui.theme import THEMES, contrast_ratio, text_on
    for level, fill in THEMES[theme]["q"].items():
        assert contrast_ratio(fill, text_on(fill)) >= 4.5, (theme, level, fill)


def test_signal_plot_labels_and_legends_readable(window):
    st = window.rec_page.signals_tab
    assert "Optical Δ" in st.opt_plot.getPlotItem().getAxis("left").labelText
    for pw in (st.acc_plot, st.gyr_plot):
        assert pw.getPlotItem().legend.columnCount == 3                     # x y z in one row
    assert all(lg.opts["brush"].color().alpha() == 210 for lg in window.ctx.plots.legends)   # every legend has a backing


def test_head_map_renders_levels_on_pills(qapp):
    from musemonitor.ui.widgets.head_map import HeadWidget
    h = HeadWidget(["TP9", "AF7", "AF8", "TP10"]); h.resize(400, 420); h.show()
    h.set_quality({"TP9": "Good", "AF7": "Fair", "AF8": "Bad", "TP10": "No signal"})
    img = h.grab().toImage()
    assert not img.isNull() and img.width() >= 400
    h.close()


# ---- V8–V13 (User_Analysis UX review) -----------------------------------------------------------------
def test_record_and_fit_shortcuts(window, tmp_path, monkeypatch):
    rp = window.rec_page
    assert window.record_action.shortcut() == mw.RECORD_KEY and window.fit_action.shortcut() == mw.FIT_KEY
    assert mw._native(mw.RECORD_KEY) in rp.record_btn.toolTip()
    window.record_action.trigger()                            # not streaming yet: explains instead of failing
    assert not window.recording and "Connect a device" in window.statusBar().currentMessage()
    monkeypatch.setenv("MUSEMONITOR_DATA_DIR", str(tmp_path))
    window.worker, window.streaming, window.device_name = FakeWorker(), True, "MuseS-TEST"
    rp.set_record_enabled(True); window.stack.setCurrentIndex(mw.PAGE_FIT)
    window.record_action.trigger()
    assert window.recording and window.stack.currentIndex() == mw.PAGE_RECORDING
    assert window.record_action.text() == "Stop recording"
    window.fit_action.trigger()
    assert window.stack.currentIndex() == mw.PAGE_FIT and window.recording   # fit-test while recording keeps recording
    window.record_action.trigger()
    assert not window.recording and window.record_action.text() == "Start recording"


def test_theme_lives_in_view_menu(window):
    assert not hasattr(window, "theme_box")
    view = next(a.menu() for a in window.menuBar().actions() if a.text() == "View")
    theme = next(a.menu() for a in view.actions() if a.text() == "Theme")
    acts = {a.text(): a for a in theme.actions()}
    acts["Light"].trigger()
    assert window.ctx.th is mw.THEMES["Light"] and acts["Light"].isChecked() and not acts["Dark"].isChecked()
    window.apply_theme("Dark")
    assert acts["Dark"].isChecked() and window.ctx.settings.value("theme") == "Dark"


def test_extension_messages_have_their_own_slot_and_expire(window, qapp):
    from musemonitor.plugins.api import ExtensionContext
    from musemonitor.ui.widgets.ext_status import ExtensionStatus
    ctx = ExtensionContext("demo", window, window.extensions)
    window.statusBar().showMessage("system message")
    ctx.show_status("hello", 0)                               # 0 used to mean "forever"
    assert window.ext_msg.text() == "🧩 demo: hello" and window.statusBar().currentMessage() == "system message"
    assert window.ext_msg._timer.isActive() and window.ext_msg._timer.interval() == ExtensionStatus.MAX_MS
    ctx.show_status("x" * 200, 10)
    assert window.ext_msg.text().endswith("…") and len(window.ext_msg.text()) == ExtensionStatus.MAX_CHARS
    assert window.ext_msg.toolTip().endswith("x" * 50)
    import time
    end = time.monotonic() + 2
    while window.ext_msg.text() and time.monotonic() < end: qapp.processEvents()
    assert window.ext_msg.text() == ""


def test_wall_clock_shown_on_live_page(window):
    window.update_texts()
    import re
    assert re.fullmatch(r"🕒 \d\d:\d\d:\d\d", window.rec_page.clock_label.text())


def test_accessible_names_and_descriptions(window):
    rp, fp = window.rec_page, window.fit_page
    assert rp.record_btn.accessibleName() and rp.disc_btn.accessibleName() and rp.range_spin.accessibleName()
    window.update_quality()
    assert "TP9 Good" in rp.signals_tab.graphics.accessibleDescription()
    assert "TP9 Good" in fp.head.accessibleDescription() and "4/4" in fp.accept_btn.accessibleDescription()
    assert window.connect_page.dev_list.accessibleName() == "Devices found"


def test_saved_recording_open_report_folder_and_recent(window, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(window, "open_path", lambda p: opened.append(p))
    rp = window.rec_page
    assert not window.open_report_action.isEnabled() and not rp.saved_label.isVisible()
    start_recording(window, tmp_path, monkeypatch)
    folder = window.session.folder
    window.toggle_record()
    assert rp.saved_label.isVisible() and folder.name in rp.saved_label.text()
    assert window.open_report_action.isEnabled() and window.open_folder_action.isEnabled()
    rp.saved_label.linkActivated.emit("report"); window.open_folder_action.trigger()
    assert opened == [folder / "report.html", folder]
    assert window.recent_sessions()[0] == str(folder)
    window._fill_recent()
    assert [a.text() for a in window.recent_menu.actions()] == [folder.name]
    start_recording(window, tmp_path, monkeypatch)
    assert not rp.saved_label.isVisible()                     # hidden while the next recording runs
    window.toggle_record()
    assert len(window.recent_sessions()) == 2 and window.recent_sessions()[0] != str(folder)


# ---- B4 edge cases: session.json "fit_test" -------------------------------------------------------------
def test_recording_without_accept_records_current_quality_unaccepted(window, tmp_path, monkeypatch):
    import json
    fp = window.fit_page
    fp.set_device("MuseS-TEST")                                  # new stream, Accept not pressed
    fp.set_quality([("Bad", float("nan"), float("inf"))] + GOOD[:3])
    start_recording(window, tmp_path, monkeypatch)               # e.g. ⌘R straight from the fit-test page
    meta = json.loads((window.session.folder / "session.json").read_text())
    window.toggle_record()
    ft = meta["fit_test"]
    assert ft["accepted"] is False and ft["all_good"] is False
    assert ft["channels"]["TP9"] == dict(level="Bad", signal_rms_uv=None, mains_rms_uv=None)   # NaN/inf → null


def test_fit_test_before_any_measurement(window):
    fp = window.fit_page
    fp.set_quality(None)
    rec = fp.quality_record(accepted=False)
    assert rec["all_good"] is False and set(c["level"] for c in rec["channels"].values()) == {"—"}


def test_unserialisable_fit_test_never_breaks_session_json(spec, tmp_path):
    import json
    from musemonitor.storage.session import RecordingSession
    s = RecordingSession(spec, root=tmp_path, fit_test={"bad": object(), "nan": float("nan")})
    meta = json.loads((s.folder / "session.json").read_text())
    assert "fit_test" not in meta and meta["fit_test_error"].startswith(("TypeError", "ValueError"))
    assert meta["schema"] == 1 and meta["streams"]["eeg"]["fs"] == spec.eeg.fs
    s2 = RecordingSession(spec, root=tmp_path, fit_test=None)
    assert "fit_test" not in json.loads((s2.folder / "session.json").read_text())   # old behaviour unchanged


def test_closed_window_stops_its_timers(window):
    timers = window._timers
    assert timers and all(t.isActive() for t in timers)
    window.connected = False; window.close()
    assert not any(t.isActive() for t in timers)          # no redraw / analysis after close (review windows may stay)
