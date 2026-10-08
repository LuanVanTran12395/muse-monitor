"""Controller: wires pages ↔ device (worker/scanner) ↔ storage ↔ SignalStore."""
import time
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .. import config as C
from ..core.quality import contact_quality
from ..core.store import SignalStore
from ..device.scanner import BleScanner
from ..device.profiles import athena_profile, profile_for_name
from ..plugins.manager import ExtensionManager
from ..storage.events import EventWriter
from ..storage.session import RecordingSession
from .context import ViewContext
from .markers import EventMarkers
from .pages import ConnectPage, FitPage, RecordingPage
from .plotkit import PlotRegistry
from .theme import THEMES, DEFAULT_THEME, apply_app_theme
from .widgets.event_dialog import ask_event_label
from .widgets.extensions_dialog import ExtensionsDialog
from .widgets.indicators import battery_html

PAGE_CONNECT, PAGE_FIT, PAGE_RECORDING = range(3)


class MainWindow(QtWidgets.QMainWindow):
    # User picked a device of another profile → app.py builds a new window for that profile: (profile_id, device name)
    switch_requested = QtCore.Signal(str, str)

    def __init__(self, spec, settings=None, extension_dirs=None, profile=None, profiles=None):
        """settings: QSettings (default: the user's); extension_dirs: None = default folders.
        profile: device.profiles.DeviceProfile of this window (default Muse S Athena);
        profiles: every available profile to scan for (default: only this window's profile)."""
        super().__init__()
        self.profile = profile or athena_profile()
        self.profiles = profiles or [self.profile]
        self.setWindowTitle(C.APP_NAME if self.profile.id == "muse_athena" else f"{C.APP_NAME} — {self.profile.name}")
        self.resize(1240, 860)
        self.spec = spec
        self.thread = self.worker = None
        self.scan_thread = self.scanner = None
        self.connected = self.streaming = self.recording = self.closing = False
        self.device_name = ""
        self.status = "Disconnected"
        self.last_qs = None; self.last_batt = None
        self.ev_writer = None
        self.rec_path = None
        self.session = None            # RecordingSession while recording (folder + whole-session PSD)
        self._pending_new_session = False   # New session waits for the worker / scan to stop first
        self.report_error = ""

        settings = settings if settings is not None else QtCore.QSettings(C.ORG_NAME, "MuseMonitor")
        self.ctx = ViewContext(spec=spec, store=SignalStore(spec), settings=settings,
                               plots=PlotRegistry(float(settings.value("window_sec", C.WINDOW_SEC))),
                               profile=self.profile)
        self.markers = EventMarkers(self.ctx)
        self._build_ui()
        # Extensions: loaded once the UI is ready (so add_tab/add_action work), before the theme is applied
        self.extensions = ExtensionManager(self, settings, dirs=extension_dirs)
        self.rec_page.tab_failed.connect(self.extensions.fail)
        self.extensions.load_all()
        self.apply_theme(settings.value("theme", DEFAULT_THEME))

        self._timer(C.REDRAW_MS, self.redraw)
        self._timer(C.TEXT_MS, self.update_quality, self.update_texts)   # text readouts: twice per second
        self._timer(C.ANALYSIS_MS, self.update_analysis)
        QtWidgets.QApplication.instance().installEventFilter(self)       # Space key → event
        QtCore.QTimer.singleShot(300, self.start_scan)                   # scan automatically on start-up

    def _timer(self, ms, *slots):
        t = QtCore.QTimer(self)
        for s in slots: t.timeout.connect(s)
        t.start(ms); return t

    def _build_ui(self):
        self.stack = QtWidgets.QStackedWidget(); self.setCentralWidget(self.stack)
        self.connect_page = ConnectPage(self.ctx, self.profiles)
        self.fit_page = FitPage(self.ctx)
        self.rec_page = RecordingPage(self.ctx)
        for p in (self.connect_page, self.fit_page, self.rec_page): self.stack.addWidget(p)

        self.connect_page.connect_clicked.connect(self.connect_selected)
        self.connect_page.rescan_clicked.connect(self.start_scan)
        self.fit_page.accept_clicked.connect(lambda: self.stack.setCurrentIndex(PAGE_RECORDING))
        self.fit_page.disconnect_clicked.connect(self.disconnect_device)
        self.rec_page.fit_clicked.connect(lambda: self.stack.setCurrentIndex(PAGE_FIT))
        self.rec_page.disconnect_clicked.connect(self.disconnect_device)
        self.rec_page.record_clicked.connect(self.toggle_record)

        bar = self.statusBar()
        self.theme_box = QtWidgets.QComboBox(); self.theme_box.addItems(list(THEMES))
        self.theme_box.setFocusPolicy(QtCore.Qt.NoFocus)
        self.theme_box.currentTextChanged.connect(self.apply_theme)
        bar.addPermanentWidget(QtWidgets.QLabel("Theme:")); bar.addPermanentWidget(self.theme_box)

        file_menu = self.menuBar().addMenu("File")
        self.new_action = self._menu_action(file_menu, "New session", QtGui.QKeySequence.New, self.new_session)
        self.open_action = self._menu_action(file_menu, "Open session…", QtGui.QKeySequence.Open, self.open_session_dialog)
        file_menu.addSeparator()
        self._menu_action(file_menu, "Close window", QtGui.QKeySequence.Close, self.close)

        self.ext_menu = self.menuBar().addMenu("Extensions")
        self.ext_menu_sep = self.ext_menu.addSeparator()       # extension actions are inserted above
        self.ext_menu.addAction("Check for new extensions", self.check_new_extensions)
        self.ext_menu.addAction("Manage extensions…", self.show_extensions)

    @staticmethod
    def _menu_action(menu, text, key, slot):
        act = menu.addAction(text); act.setShortcut(key); act.triggered.connect(slot)
        return act

    # ======================= File: new / open session ==========================
    def new_session(self):
        """Start over: stop recording (the report is still written), disconnect, clear data and events,
        back to Connect. Waits for the worker (or a running scan) to stop before clearing, so a late
        chunk can never land in the new session."""
        if self._pending_new_session: return
        self._new_session_note = ""
        if self.recording:
            self.stop_recording()
            self._new_session_note = self.report_error            # keep a report failure visible after the reset
        if self.connected or self.scan_thread:
            self._pending_new_session = True
            self.new_action.setEnabled(False); self.open_action.setEnabled(False)
            self.set_status("Starting a new session…")
            if self.connected: self.disconnect_device()          # → on_stopped → _reset_session
            return
        self._reset_session()

    def _reset_session(self):
        self._pending_new_session = False
        self.new_action.setEnabled(True); self.open_action.setEnabled(True)
        self.clear_buffers()
        self.markers.clear()
        self.rec_page.clear(); self.fit_page.clear()
        self.last_qs = None; self._show_quality(None)
        self.stack.setCurrentIndex(PAGE_CONNECT)
        note = getattr(self, "_new_session_note", "")
        self.set_status("New session — choose a device and connect" + (f"  •  {note}" if note else ""))

    def open_session_dialog(self):
        from .review_window import ask_open_path
        path = ask_open_path(self)
        if path: return self.open_session(path)

    def open_session(self, path, **kw):
        """Open a recording in its own review window; the live window keeps running."""
        from .review_window import open_review
        return open_review(path, self.ctx.settings, self.profiles, parent=self, **kw)

    def remove_extension_tabs(self, owner):
        self.markers.forget_plots(self.rec_page.remove_tabs(owner))

    def check_new_extensions(self):
        changed = self.extensions.refresh()
        self.statusBar().showMessage(self.extensions.summarize(changed), 8000)
        return changed

    def show_extensions(self):
        ExtensionsDialog(self.extensions, self).exec()

    def on_extension_failed(self, rec):
        self.statusBar().showMessage(f"Extension '{rec.name}' crashed and was disabled — see Extensions ▸ Manage", 10000)

    # ======================= Theme =============================================
    @QtCore.Slot(str)
    def apply_theme(self, name):
        if name not in THEMES: name = DEFAULT_THEME
        th = self.ctx.th = THEMES[name]
        if self.theme_box.currentText() != name:
            self.theme_box.blockSignals(True); self.theme_box.setCurrentText(name); self.theme_box.blockSignals(False)
        apply_app_theme(th)
        self.ctx.plots.apply_theme(th)
        self.fit_page.apply_theme(th); self.rec_page.apply_theme(th)
        self.markers.apply_theme()
        self._show_quality(self.last_qs)
        self._show_battery()
        self.ctx.settings.setValue("theme", name)
        if hasattr(self, "extensions"): self.extensions.dispatch("on_theme_changed", th)
        from .review_window import ReviewWindow
        ReviewWindow.apply_theme_all(name)

    # ======================= Timers ============================================
    def redraw(self):
        page = self.stack.currentIndex()
        if page == PAGE_FIT: self.fit_page.on_frame()
        elif page == PAGE_RECORDING:
            self.markers.place(max_age_sec=C.OPT_HIST_SEC)
            self.rec_page.on_frame()

    @QtCore.Slot()
    def update_analysis(self):
        if self.stack.currentIndex() == PAGE_RECORDING: self.rec_page.on_analysis()

    @QtCore.Slot()
    def update_texts(self):
        self.rec_page.update_texts()

    @QtCore.Slot()
    def update_quality(self):
        st, fs = self.ctx.store, self.spec.eeg.fs
        need = C.QUALITY_SEC * fs
        if st.eeg.n < need:
            if not self.connected: return
            self.last_qs = None
        else:
            self.last_qs = contact_quality(st.eeg.get(need), fs)
        self._show_quality(self.last_qs)

    def _show_quality(self, qs):
        self.fit_page.set_quality(qs); self.rec_page.set_quality(qs)

    def _show_battery(self):
        html = battery_html(self.last_batt, self.ctx.th)
        self.rec_page.set_battery_html(html); self.fit_page.set_battery_html(html)

    # ======================= Event markers (Space) =============================
    def eventFilter(self, obj, ev):
        if (ev.type() == QtCore.QEvent.KeyPress and ev.key() == QtCore.Qt.Key_Space and not ev.isAutoRepeat()
                and self.stack.currentIndex() == PAGE_RECORDING and self.isActiveWindow()
                and QtWidgets.QApplication.activeModalWidget() is None):
            fw = QtWidgets.QApplication.focusWidget()
            if not (isinstance(fw, (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit))
                    and not isinstance(fw.parent(), QtWidgets.QAbstractSpinBox)):
                self.mark_event(); return True
        return super().eventFilter(obj, ev)

    def mark_event(self):
        t = time.time()                                  # time Space was pressed, not when Done was clicked
        label = ask_event_label(self, t)
        if label: self.add_event(label, t)

    def add_event(self, label, t=None):
        """Add an event (Space key or extension): marker + _events.csv + on_event hook."""
        t = time.time() if t is None else t
        self.markers.add(t, label)
        if self.ev_writer: self.ev_writer.write(t, label)
        if self.session: self.session.add_event(t, label)
        self.rec_page.set_events_text(len(self.markers), label, saved=self.ev_writer is not None)
        self.extensions.dispatch("on_event", t, label)

    def _close_events_file(self):
        if self.ev_writer: self.ev_writer.close()
        self.ev_writer = None
        self.rec_path = None

    # ======================= Connection ===========================================
    def set_status(self, s):
        self.status = s
        self.rec_page.set_status(s); self.connect_page.set_status(s)

    def clear_buffers(self):
        self.ctx.store.clear()
        self.markers.clear()
        self.rec_page.clear()
        self.last_qs = None; self._show_quality(None)

    @QtCore.Slot()
    def start_scan(self):
        if self.scan_thread or self.connected: return
        self.connect_page.set_scanning(True)
        self.scan_thread = QtCore.QThread(self)
        self.scanner = BleScanner(self.profiles if len(self.profiles) > 1 else None)
        self.scanner.moveToThread(self.scan_thread)
        self.scan_thread.started.connect(self.scanner.run)
        self.scanner.found.connect(self.connect_page.show_devices)
        self.scanner.error.connect(self.connect_page.set_scan_message)
        self.scanner.finished.connect(self._on_scan_done)
        self.scanner.finished.connect(self.scan_thread.quit)
        self.scan_thread.finished.connect(self.scanner.deleteLater)
        self.scan_thread.start()

    @QtCore.Slot()
    def _on_scan_done(self):
        if self.scan_thread: self.scan_thread.wait(2000)
        self.scan_thread = None; self.connect_page.set_scanning(False)
        if self._pending_new_session and not self.connected: self._reset_session()

    @QtCore.Slot()
    def connect_selected(self):
        if self.connected:               # the button currently reads "Cancel"
            self.disconnect_device(); return
        serial = self.connect_page.device_name()
        if not serial or self.scan_thread: return
        self.ctx.settings.setValue("last_device", serial)
        pid = self.connect_page.selected_profile_id()
        target = (next((p for p in self.profiles if p.id == pid), None)
                  or profile_for_name(self.profiles, serial, self.profile))
        self.ctx.settings.setValue("device_profile", target.id)
        if target.id != self.profile.id:                     # different device type → new window for that profile
            self.switch_requested.emit(target.id, serial); return
        self.clear_buffers()
        self.streaming = False
        self.rec_page.set_record_enabled(False)
        self.thread = QtCore.QThread(self)
        self.worker = self.profile.make_worker(serial, self.spec)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        # Received through MainWindow slots (QObject in the GUI thread) → queued connection; connecting straight to
        # SignalStore (not a QObject) would run in the worker thread and race with the GUI.
        self.worker.data_ready.connect(self.on_data)
        self.worker.optics_ready.connect(self.on_optics)
        self.worker.imu_ready.connect(self.on_imu)
        self.worker.battery.connect(self.on_battery)
        self.worker.status.connect(self.set_status)
        self.worker.stream_started.connect(self.on_stream_started)
        self.worker.stream_stats.connect(self.rec_page.set_stream_stats)
        self.worker.stopped.connect(self.on_stopped)
        self.worker.stopped.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start()
        self.connected = True
        self.device_name = serial
        self.connect_page.set_busy(True)

    def connect_to(self, device_name):
        """Connect straight to a device by name (used after switching to another profile's window)."""
        self.connect_page.dev_name.setText(device_name)
        self.connect_page.dev_list.clearSelection()
        self.connect_selected()

    @QtCore.Slot()
    def disconnect_device(self):
        if not self.connected: return
        if self.recording: self.stop_recording()
        self.set_status("Disconnecting…")
        self.rec_page.set_disconnect_enabled(False); self.connect_page.set_cancel_enabled(False)
        self.fit_page.set_disconnect_enabled(False)
        if self.worker: self.worker.request_stop()

    @QtCore.Slot()
    def on_stream_started(self):
        self.streaming = True
        self.rec_page.set_record_enabled(True)
        self.fit_page.set_device(self.device_name)
        self.stack.setCurrentIndex(PAGE_FIT)            # connected → fit test
        self.extensions.dispatch("on_connected", self.device_name)

    # ts: vector of raw per-sample timestamps (or a scalar = last sample); seq: package_num or None.
    # v1 extension hooks still receive the LAST-SAMPLE timestamp (float) as before.
    @QtCore.Slot(object, object, object)
    def on_data(self, eeg, ts, seq=None):
        st = self.ctx.store
        st.add_eeg(eeg, ts, seq); self.extensions.dispatch("on_eeg", eeg, st.last_ts["eeg"])
        if self.session: self.session.add("eeg", eeg)

    @QtCore.Slot(object, object, object)
    def on_optics(self, optics, ts, seq=None):
        st = self.ctx.store
        st.add_optics(optics, ts, seq); self.extensions.dispatch("on_optics", optics, st.last_ts["opt"])
        if self.session: self.session.add("opt", optics)

    @QtCore.Slot(object, object, object)
    def on_imu(self, imu, ts, seq=None):
        st = self.ctx.store
        st.add_imu(imu, ts, seq); self.extensions.dispatch("on_imu", imu, st.last_ts["imu"])
        if self.session: self.session.add("imu", imu)

    @QtCore.Slot(float)
    def on_battery(self, pct):
        self.last_batt = max(0.0, min(100.0, pct)); self._show_battery()

    @QtCore.Slot()
    def on_stopped(self):
        was_recording = self.recording
        self.connected = self.streaming = self.recording = False
        if was_recording: self.extensions.dispatch("on_recording_stopped")
        self.extensions.dispatch("on_disconnected")
        self.rec_page.set_recording(False); self.rec_page.set_record_enabled(False)
        self._close_events_file()
        report = self._finish_session()                 # connection lost while recording → still write the report
        self.rec_page.set_disconnect_enabled(True); self.fit_page.set_disconnect_enabled(True)
        self.connect_page.set_busy(False)
        self.last_batt = None; self._show_battery()
        self.stack.setCurrentIndex(PAGE_CONNECT)        # back to the connect screen
        if not self.status.startswith(("Connection/stream error", "BLE connected • NO")):
            self.set_status("Disconnected")
        if report:
            self.set_status(f"{self.status} • recording saved to {report.parent.name}/ (report.html)")
        if self.thread:
            self.thread.wait(3000)
            self.thread = None; self.worker = None
        if self._pending_new_session and not self.scan_thread: self._reset_session()
        if self.closing: self.close()

    # ======================= Ghi file ==========================================
    def toggle_record(self):
        """Record straight into data/muse_<time>/ (no path prompt) and add event "0" automatically at the start."""
        if self.recording: self.stop_recording(); return
        if not self.worker: return
        try:
            self.session = RecordingSession(self.spec, device=self.device_name, profile_id=self.profile.id)
        except OSError as e:
            self.set_status(f"Cannot create session folder: {e}"); self.session = None; return
        path = str(self.session.eeg_path)
        try:
            self.ev_writer = EventWriter(path)
        except OSError as e:
            self.set_status(f"Cannot open events file: {e}"); self.ev_writer = None
        self.worker.start_recording(path)
        self.recording = True; self.rec_path = path
        self.rec_page.set_recording(True)
        self.extensions.dispatch("on_recording_started", path)
        self.add_event(C.START_EVENT_LABEL)
        self.set_status(f"Recording → {self.session.folder.parent.name}/{self.session.folder.name}/")

    def stop_recording(self):
        if self.worker: self.worker.stop_recording()
        self._close_events_file()
        was_recording, self.recording = self.recording, False
        if was_recording: self.extensions.dispatch("on_recording_stopped")    # extensions close their files before the report
        self.rec_page.set_recording(False)
        report = self._finish_session()
        if report: self.set_status(f"Saved {report.parent.parent.name}/{report.parent.name}/ — report.html")
        elif self.streaming and not self.report_error: self.set_status(f"Streaming EEG • {self.spec.eeg.fs} Hz")

    def _finish_session(self):
        """Close the recording session and write the whole-session PSD report; return the report path (or None)."""
        sess, self.session = self.session, None
        self.report_error = ""
        if sess is None: return None
        try:
            return sess.finish(self.ctx.store.health())
        except Exception as e:                          # a report error must not lose recorded data
            self.report_error = f"Recording saved to {sess.folder.name}/ but report failed: {type(e).__name__}: {e}"
            self.set_status(self.report_error)
            return None

    def closeEvent(self, event):
        # Do not close while the worker is still running (prepare/release_session may take > 2 s) → avoids
        # "QThread: Destroyed while thread is still running". Wait for stopped, then close() automatically.
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.wait(C.SCAN_SEC * 1000 + 2000)
        if self.thread and self.thread.isRunning():
            self.closing = True
            if self.recording: self.stop_recording()
            self.worker.request_stop()
            self.set_status("Closing… releasing Muse")
            event.ignore(); return
        self._close_events_file()
        self.extensions.shutdown()
        QtWidgets.QApplication.instance().removeEventFilter(self)       # the Space filter is app-wide
        event.accept()
