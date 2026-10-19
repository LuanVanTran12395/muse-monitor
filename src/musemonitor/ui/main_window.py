"""Controller: wires pages ↔ device (worker/scanner) ↔ storage ↔ SignalStore."""
import time
from pathlib import Path

import numpy as np

from PySide6 import QtCore, QtGui, QtWidgets

from .. import config as C
from ..core.quality import contact_quality
from ..core.store import SignalStore
from ..core.timing import ts_vector
from ..device.scanner import BleScanner
from ..device.profiles import athena_profile, profile_for_name
from ..plugins.manager import ExtensionManager
from ..storage.events import EventWriter
from ..storage.session import RecordingSession
from .context import ViewContext
from .markers import EventMarkers
from .pages import ConnectPage, FitPage, RecordingPage
from .pages.recording_page import format_elapsed
from .panels import PanelMenus
from .plotkit import PlotRegistry
from .tabs.base import BaseTab
from .theme import THEMES, DEFAULT_THEME, apply_app_theme
from .widgets.event_dialog import ask_event_label
from .widgets.ext_status import ExtensionStatus
from .widgets.extensions_dialog import ExtensionsDialog
from .widgets.indicators import battery_html

PAGE_CONNECT, PAGE_FIT, PAGE_RECORDING = range(3)
RECORD_KEY = QtGui.QKeySequence("Ctrl+R")          # ⌘R on macOS
FIT_KEY = QtGui.QKeySequence("Ctrl+T")
RELOAD_KEY = QtGui.QKeySequence("Ctrl+Shift+R")   # edit an extension's file → ⌘⇧R runs the new code
RECENT_KEY, RECENT_MAX = "recent_sessions", 8


def _native(key):
    return key.toString(QtGui.QKeySequence.NativeText)


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
        self.base_title = C.APP_NAME if self.profile.id == "muse_athena" else f"{C.APP_NAME} — {self.profile.name}"
        self.setWindowTitle(self.base_title)
        self.resize(1240, 860)
        self.spec = spec
        self.thread = self.worker = None
        self.scan_thread = self.scanner = None
        self.connected = self.streaming = self.recording = self.closing = False
        self.device_name = ""
        self.status = "Disconnected"
        self.last_qs = None; self.last_batt = None
        self.ev_writer = None
        self._last_label = ""          # last event label, pre-filled (selected) in the Space prompt
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
        self.panels.announce()
        self.apply_theme(settings.value("theme", DEFAULT_THEME))

        self._timer(C.REDRAW_MS, self.redraw)
        self._timer(C.TEXT_MS, self.update_quality, self.update_texts)   # text readouts: twice per second
        self._timer(C.ANALYSIS_MS, self.update_analysis)
        QtWidgets.QApplication.instance().installEventFilter(self)       # Space key → event
        QtCore.QTimer.singleShot(300, self.start_scan)                   # scan automatically on start-up

    def _timer(self, ms, *slots):
        t = QtCore.QTimer(self)
        self._timers = getattr(self, "_timers", []) + [t]
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
        self.fit_page.disconnect_clicked.connect(self.user_disconnect)
        self.rec_page.fit_clicked.connect(lambda: self.stack.setCurrentIndex(PAGE_FIT))
        self.rec_page.disconnect_clicked.connect(self.user_disconnect)
        self.rec_page.record_clicked.connect(self.toggle_record)
        self.rec_page.open_saved.connect(self.open_last_saved)

        self.ext_msg = ExtensionStatus()                  # extension messages: their own slot, they clear themselves
        self.ctx.plots.muted.append(self.ext_msg)
        self.statusBar().addPermanentWidget(self.ext_msg)

        file_menu = self.menuBar().addMenu("File")
        self.new_action = self._menu_action(file_menu, "New session", QtGui.QKeySequence.New, self.user_new_session)
        self.open_action = self._menu_action(file_menu, "Open session…", QtGui.QKeySequence.Open, self.open_session_dialog)
        self.recent_menu = file_menu.addMenu("Open recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        file_menu.addSeparator()
        self.record_action = self._menu_action(file_menu, "Start recording", RECORD_KEY, self.shortcut_record)
        self.fit_action = self._menu_action(file_menu, "Fit-test", FIT_KEY, self.shortcut_fit)
        file_menu.addSeparator()
        self.open_folder_action = file_menu.addAction("Open last recording folder", lambda: self.open_last_saved("folder"))
        self.open_report_action = file_menu.addAction("Open last report", lambda: self.open_last_saved("report"))
        file_menu.addSeparator()
        self._menu_action(file_menu, "Close window", QtGui.QKeySequence.Close, self.user_close)
        self.rec_page.record_btn.setToolTip(f"Start / stop recording ({_native(RECORD_KEY)})")
        self.rec_page.fit_btn.setToolTip(f"Back to the fit-test ({_native(FIT_KEY)})")

        view_menu = self.menuBar().addMenu("View")             # theme: in a menu, reachable from the keyboard
        theme_menu = view_menu.addMenu("Theme")
        self.theme_group = QtGui.QActionGroup(self); self.theme_actions = {}
        for name in THEMES:
            act = theme_menu.addAction(name); act.setCheckable(True); self.theme_group.addAction(act)
            act.triggered.connect(lambda _=False, n=name: self.apply_theme(n))
            self.theme_actions[name] = act
        self.panels = PanelMenus(self, self.rec_page, self.ctx.settings, kind="live")     # Analysis, HCI/BCI
        self.last_saved = None                                 # folder of the last recording saved in this window
        self._update_saved_actions()

        self.ext_menu = self.menuBar().addMenu("Extensions")
        self.ext_menu_sep = self.ext_menu.addSeparator()       # extension actions are inserted above
        self.ext_menu.addAction("Check for new extensions", self.check_new_extensions)
        self.reload_action = self._menu_action(self.ext_menu, "Reload changed extensions", RELOAD_KEY,
                                               self.reload_changed_extensions)
        self.ext_menu.addAction("Manage extensions…", self.show_extensions)

    @staticmethod
    def _menu_action(menu, text, key, slot):
        act = menu.addAction(text); act.setShortcut(key); act.triggered.connect(slot)
        return act

    # ======================= Confirmations (user entry points only) ==============
    # Buttons, menu actions and the window's close button ask before stopping a recording. new_session(),
    # disconnect_device() and close() themselves never ask, so code (tests, extensions) keeps its behaviour.
    def confirm_stop_recording(self, action):
        """True if it is fine to go on: not recording, or the user agreed to stop the recording."""
        if not self.recording: return True
        sec = self.rec_page.recording_elapsed() or 0
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, "Recording in progress",
                                    f"Recording for {format_elapsed(sec)}. {action} will stop it.", parent=self)
        box.setInformativeText("What has been recorded so far is saved and its report is written.")
        stop = box.addButton("Stop recording", QtWidgets.QMessageBox.DestructiveRole)
        keep = box.addButton("Keep recording", QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(keep); box.setEscapeButton(keep)        # Return / Esc never stop a recording
        box.exec()
        return box.clickedButton() is stop

    def user_disconnect(self):
        if self.confirm_stop_recording("Disconnecting"): self.disconnect_device()

    def user_new_session(self):
        if self.confirm_stop_recording("A new session"): self.new_session()

    def user_close(self):
        if self.confirm_stop_recording("Closing the window"):
            self._close_confirmed = True; self.close()

    # ======================= Keyboard shortcuts (⌘R record, ⌘T fit-test) =========
    def shortcut_record(self):
        if not self.rec_page.record_btn.isEnabled():
            self.statusBar().showMessage("Connect a device and wait for the stream before recording", 5000); return
        if not self.recording: self.stack.setCurrentIndex(PAGE_RECORDING)
        self.toggle_record()

    def shortcut_fit(self):
        if self.streaming: self.stack.setCurrentIndex(PAGE_FIT)

    # ======================= Extension messages ==================================
    def show_extension_status(self, ext_id, message, ms=5000):
        """app.show_status() of an extension → its own status-bar slot (see ExtensionStatus)."""
        self.ext_msg.show_message(ext_id, message, ms)

    def clear_extension_status(self, ext_id):
        self.ext_msg.clear_owner(ext_id)

    # ======================= Saved recordings: recent / open folder / report =====
    def _remember_session(self, folder):
        self.last_saved = Path(folder)
        recent = [str(self.last_saved)] + [p for p in self.recent_sessions() if p != str(self.last_saved)]
        self.ctx.settings.setValue(RECENT_KEY, recent[:RECENT_MAX])
        self._update_saved_actions()

    def recent_sessions(self):
        v = self.ctx.settings.value(RECENT_KEY, [])
        return [v] if isinstance(v, str) else list(v or [])

    def _fill_recent(self):
        self.recent_menu.clear()
        paths = [p for p in self.recent_sessions() if Path(p).is_dir()]
        for p in paths:
            self.recent_menu.addAction(Path(p).name, lambda p=p: self.open_session(p))
        if not paths: self.recent_menu.addAction("No recent recordings").setEnabled(False)

    def _update_saved_actions(self):
        folder = self.last_saved
        report = folder / "report.html" if folder else None
        self.open_folder_action.setEnabled(bool(folder and folder.is_dir()))
        self.open_report_action.setEnabled(bool(report and report.exists()))
        self.rec_page.set_saved(folder.name if folder else None, has_report=bool(report and report.exists()))

    def open_last_saved(self, what):
        if not self.last_saved: return
        target = self.last_saved / "report.html" if what == "report" else self.last_saved
        if target.exists(): self.open_path(target)

    @staticmethod
    def open_path(path):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

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
        kw.setdefault("extension_dirs", self.extensions.dirs)
        return open_review(path, self.ctx.settings, self.profiles, parent=self, **kw)

    def remove_extension_tabs(self, owner):
        self.panels.remove_owner(owner)
        self.markers.forget_plots(self.rec_page.remove_tabs(owner))

    def check_new_extensions(self):
        changed = self.extensions.refresh()
        self.statusBar().showMessage(self.extensions.summarize(changed), 8000)
        if changed: self.panels.announce()
        return changed

    def reload_changed_extensions(self):
        """Extensions ▸ Reload changed extensions: re-import file extensions edited since they were loaded."""
        done, msg = self.extensions.reload_changed()
        self.statusBar().showMessage(msg, 10000)
        return done

    def show_extensions(self):
        ExtensionsDialog(self.extensions, self).exec()

    def on_extension_failed(self, rec):
        self.clear_extension_status(rec.id)
        self.statusBar().showMessage(f"Extension '{rec.name}' crashed and was disabled — see Extensions ▸ Manage", 10000)

    # ======================= Theme =============================================
    @QtCore.Slot(str)
    def apply_theme(self, name):
        if name not in THEMES: name = DEFAULT_THEME
        th = self.ctx.th = THEMES[name]
        self.theme_actions[name].setChecked(True)
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
        self._update_title()

    def _update_title(self):
        """'● REC 3:07 — Muse Monitor' while recording: visible in the Dock/taskbar and from any page."""
        sec = self.rec_page.recording_elapsed()
        title = self.base_title if sec is None else f"● REC {format_elapsed(sec)} — {self.base_title}"
        if self.windowTitle() != title: self.setWindowTitle(title)
        self.record_action.setText("Start recording" if sec is None else "Stop recording")

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

    # ======================= Event markers (Space, 1–9) ========================
    QUICK_KEYS = {getattr(QtCore.Qt, f"Key_{d}"): str(d) for d in range(1, 10)}    # "0" is the start-of-recording event

    def eventFilter(self, obj, ev):
        if (ev.type() == QtCore.QEvent.KeyPress and not ev.isAutoRepeat()
                and ev.key() in (QtCore.Qt.Key_Space, *self.QUICK_KEYS)
                and self.stack.currentIndex() == PAGE_RECORDING and self.isActiveWindow()
                and QtWidgets.QApplication.activeModalWidget() is None):
            # the widget the key is delivered to (first seen on its QWindow → the focus widget)
            fw = obj if isinstance(obj, QtWidgets.QWidget) else QtWidgets.QApplication.focusWidget()
            if self._tab_claims_key(fw, ev.key()): return super().eventFilter(obj, ev)
            typing =isinstance(fw, (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit))
            in_spin = isinstance(fw, QtWidgets.QAbstractSpinBox) or (fw is not None and isinstance(fw.parent(), QtWidgets.QAbstractSpinBox))
            if ev.key() == QtCore.Qt.Key_Space:
                if not (typing and not in_spin):           # a spin box ignores Space → still marks
                    self.mark_event(); return True
            elif not (typing or in_spin) and not (ev.modifiers() & ~QtCore.Qt.KeypadModifier):
                self.add_event(self.QUICK_KEYS[ev.key()]); return True     # digits typed into a field stay there
        return super().eventFilter(obj, ev)

    @staticmethod
    def _tab_claims_key(widget, key):
        """True if ``widget`` sits in a tab (BaseTab) that claims this reserved key (wants_keys / wants_all_keys)."""
        w = widget
        while w is not None:
            if isinstance(w, BaseTab): return bool(w.wants_all_keys or key in w.wants_keys)
            w = w.parentWidget()
        return False

    def mark_event(self):
        t = time.time()                                  # time Space was pressed, not when Done was clicked
        label = ask_event_label(self, t, last=self._last_label)
        if label: self.add_event(label, t)

    def add_event(self, label, t=None):
        """Add an event (Space key or extension): marker + _events.csv + on_event hook."""
        t = time.time() if t is None else t
        if label != C.START_EVENT_LABEL: self._last_label = label       # pre-filled the next time Space is pressed
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
        self._dispatch_samples("on_eeg_samples", eeg, ts, self.spec.eeg.fs)
        if self.session: self.session.add("eeg", eeg)

    @QtCore.Slot(object, object, object)
    def on_optics(self, optics, ts, seq=None):
        st = self.ctx.store
        st.add_optics(optics, ts, seq); self.extensions.dispatch("on_optics", optics, st.last_ts["opt"])
        self._dispatch_samples("on_optics_samples", optics, ts, self.spec.optics.fs)
        if self.session: self.session.add("opt", optics)

    @QtCore.Slot(object, object, object)
    def on_imu(self, imu, ts, seq=None):
        st = self.ctx.store
        st.add_imu(imu, ts, seq); self.extensions.dispatch("on_imu", imu, st.last_ts["imu"])
        self._dispatch_samples("on_imu_samples", imu, ts, self.spec.imu.fs)
        if self.session: self.session.add("imu", imu)

    def _dispatch_samples(self, hook, x, ts, fs):
        """API 3: the chunk with the per-sample timestamps the worker delivered (and the CSV records).
        A worker that sends only the last timestamp gets it expanded at the nominal rate."""
        if not self.extensions.wants(hook): return
        self.extensions.dispatch(hook, x, np.array(ts_vector(ts, x.shape[1], fs), dtype=np.float64))

    @QtCore.Slot(float)
    def on_battery(self, pct):
        self.last_batt = max(0.0, min(100.0, pct)); self._show_battery()

    @QtCore.Slot()
    def on_stopped(self):
        was_recording = self.recording
        self.connected = self.streaming = self.recording = False
        if was_recording: self.extensions.dispatch("on_recording_stopped")
        self.extensions.dispatch("on_disconnected")
        self.rec_page.set_recording(False); self.rec_page.set_record_enabled(False); self._update_title()
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
            self.session = RecordingSession(self.spec, device=self.device_name, profile_id=self.profile.id,
                                            fit_test=self.fit_page.fit_test_for_recording())
        except OSError as e:
            self.set_status(f"Cannot create session folder: {e}"); self.session = None; return
        path = str(self.session.eeg_path)
        try:
            self.ev_writer = EventWriter(path)
        except OSError as e:
            self.set_status(f"Cannot open events file: {e}"); self.ev_writer = None
        self.worker.start_recording(path)
        self.recording = True; self.rec_path = path
        self.rec_page.set_recording(True); self._update_title()
        self.extensions.dispatch("on_recording_started", path)
        self.add_event(C.START_EVENT_LABEL)
        self.set_status(f"Recording → {self.session.folder.parent.name}/{self.session.folder.name}/")

    def stop_recording(self):
        if self.worker: self.worker.stop_recording()
        self._close_events_file()
        was_recording, self.recording = self.recording, False
        if was_recording: self.extensions.dispatch("on_recording_stopped")    # extensions close their files before the report
        self.rec_page.set_recording(False); self._update_title()
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
        finally:
            self._remember_session(sess.folder)         # data is on disk either way → Open recent / Open folder

    def closeEvent(self, event):
        # The window's own close button (a spontaneous event) asks first while recording; close() from code does not
        confirmed, self._close_confirmed = getattr(self, "_close_confirmed", False), False
        if (event.spontaneous() and not confirmed and not self.closing
                and not self.confirm_stop_recording("Closing the window")):
            event.ignore(); return
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
        for t in getattr(self, "_timers", []): t.stop()                  # a closed window (review windows may stay
        event.accept()                                                   # open) must not keep redrawing
