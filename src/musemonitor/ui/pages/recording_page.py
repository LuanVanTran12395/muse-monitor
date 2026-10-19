import time

from PySide6 import QtCore, QtWidgets

from ... import config as C
from ..tabs import PpgTab, PsdTab, SignalsTab


def format_elapsed(sec):
    """3:07 / 1:02:03 — recording duration on the record button and in the window title."""
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class RecordingPage(QtWidgets.QWidget):
    """Screen 3: control bar + analysis tabs.

    Adding a tab: subclass ``tabs.base.BaseTab`` and add it to TAB_CLASSES."""
    TAB_CLASSES = (SignalsTab, PsdTab, PpgTab)
    START_TEXT = "● Start recording"

    fit_clicked = QtCore.Signal()
    disconnect_clicked = QtCore.Signal()
    record_clicked = QtCore.Signal()
    open_saved = QtCore.Signal(str)                  # "report" | "folder" of the last saved recording
    tab_failed = QtCore.Signal(str, object, str)     # (extension id, exception, where it failed)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        sp = ctx.spec
        outer = QtWidgets.QVBoxLayout(self)
        controls = QtWidgets.QHBoxLayout()
        self.fit_btn = QtWidgets.QPushButton("◀ Fit-test"); self.fit_btn.clicked.connect(self.fit_clicked)
        self.disc_btn = QtWidgets.QPushButton("Disconnect"); self.disc_btn.clicked.connect(self.disconnect_clicked)
        self.disc_btn.setToolTip("Disconnect the headset (asks first while recording)")
        self.record_btn = QtWidgets.QPushButton(self.START_TEXT); self.record_btn.setEnabled(False)
        self.record_btn.setMinimumWidth(190)                # room for "■ Stop recording · 1:02:03" without reflowing
        self.record_btn.clicked.connect(self.record_clicked)
        self.rec_t0 = None                                  # monotonic start of the current recording, None = not recording
        self.review = False                                 # set_review_mode() → True
        self.filtered = QtWidgets.QCheckBox(f"Filtered {C.BAND_HZ[0]}–{C.BAND_HZ[1]} Hz"); self.filtered.setChecked(True)
        self.notch = QtWidgets.QCheckBox(f"{C.NOTCH_HZ:.0f} Hz notch"); self.notch.setChecked(True)
        self.fixed_scale = QtWidgets.QCheckBox(f"Fixed ±{C.EEG_FIXED_UV} µV"); self.fixed_scale.setChecked(True)
        self.range_spin = QtWidgets.QDoubleSpinBox()
        self.range_spin.setRange(1, C.MAX_WINDOW_SEC); self.range_spin.setDecimals(0); self.range_spin.setSingleStep(1)
        self.range_spin.setSuffix(" s"); self.range_spin.setValue(ctx.window_sec)
        self.range_spin.setToolTip("Time range shown on every time-domain plot — type a number and press Enter")
        self.range_spin.setKeyboardTracking(False)      # apply on Enter/focus-out, not on every keystroke
        self.status_label = QtWidgets.QLabel("Disconnected")
        self.batt_label = QtWidgets.QLabel("🔋 —")
        self.batt_label.setToolTip("Muse battery (BrainFlow ancillary preset)")
        # Record first (primary action); Disconnect at the far right, away from it, so one is not hit for the other
        for w in (self.record_btn, self.fit_btn, self.filtered, self.notch, self.fixed_scale):
            controls.addWidget(w)
        controls.addSpacing(10); controls.addWidget(QtWidgets.QLabel("Time range:")); controls.addWidget(self.range_spin)
        controls.addStretch(); controls.addWidget(self.batt_label); controls.addSpacing(12); controls.addWidget(self.status_label)
        controls.addSpacing(16); controls.addWidget(self.disc_btn)
        outer.addLayout(controls)
        for w, name in ((self.record_btn, "Start or stop recording"), (self.fit_btn, "Back to fit-test"),
                        (self.disc_btn, "Disconnect headset"), (self.range_spin, "Time range in seconds"),
                        (self.batt_label, "Headset battery"), (self.status_label, "Connection status")):
            w.setAccessibleName(name)                    # screen readers (VoiceOver) announce these

        # Row 1: what the user acts on (events, timing verdict). Row 2 (Details): raw telemetry, hidden by default
        stats = QtWidgets.QHBoxLayout()
        self.rate_label = QtWidgets.QLabel()
        self.count_label = QtWidgets.QLabel()
        self.ev_label = QtWidgets.QLabel()
        self.last_label = QtWidgets.QLabel()
        self.health_label = QtWidgets.QLabel()
        self.details_btn = QtWidgets.QToolButton(); self.details_btn.setCheckable(True)
        self.details_btn.setAutoRaise(True); self.details_btn.setFocusPolicy(QtCore.Qt.NoFocus)
        self.details_btn.setToolTip("Show stream details: sample rate, samples received, latest values")
        self.saved_label = QtWidgets.QLabel(); self.saved_label.hide()        # after Stop: open report / folder
        self.saved_label.linkActivated.connect(self.open_saved)
        self.clock_label = QtWidgets.QLabel()
        self.clock_label.setToolTip("Wall-clock time at the right edge of the plots (now) — to match a lab notebook")
        stats.addWidget(self.ev_label); stats.addSpacing(16); stats.addWidget(self.health_label)
        stats.addSpacing(16); stats.addWidget(self.saved_label)
        stats.addStretch(); stats.addWidget(self.clock_label); stats.addSpacing(12); stats.addWidget(self.details_btn)
        outer.addLayout(stats)
        self.details = QtWidgets.QWidget()
        drow = QtWidgets.QHBoxLayout(self.details); drow.setContentsMargins(0, 0, 0, 0)
        for w in (self.rate_label, self.count_label): drow.addWidget(w); drow.addSpacing(16)
        drow.addStretch(); drow.addWidget(self.last_label)
        outer.addWidget(self.details)
        self.details_btn.toggled.connect(self._details_toggled)
        shown = str(ctx.settings.value("show_details", False)).lower() in ("true", "1")
        self.details_btn.setChecked(shown); self._details_toggled(shown)

        self.tabs = QtWidgets.QTabWidget()
        self.tab_list = [cls(ctx) for cls in self.TAB_CLASSES]
        for tab in self.tab_list: self.tabs.addTab(tab, tab.title)
        self.signals_tab = self.tab_list[0]
        self.tabs.currentChanged.connect(lambda _: self.on_analysis())
        outer.addWidget(self.tabs, 1)

        note = getattr(ctx.profile, "note", "") or (
            f"Research prototype • Athena p1041 • EEG {sp.eeg.fs} Hz + raw optics/PPG {sp.optics.fs} Hz + IMU {sp.imu.fs} Hz. "
            "Optical channel → wavelength mapping is not verified; treat HbO/HbR as exploratory.")
        self.note_label = ctx.plots.muted_label(note)
        outer.addWidget(self.note_label)

        self.fixed_scale.toggled.connect(self.signals_tab.apply_scale)
        self.filtered.toggled.connect(self._filter_changed); self.notch.toggled.connect(self._filter_changed)
        self.range_spin.valueChanged.connect(self._range_changed)
        self.clear()

    def current_tab(self):
        return self.tabs.currentWidget()

    # ---- extension tabs ---------------------------------------------------------
    def add_tab(self, tab, owner=None):
        """Add a tab at runtime (extension). ``owner`` = extension id → an error in the tab disables only that tab."""
        tab.owner = owner
        self.tab_list.append(tab); self.tabs.addTab(tab, tab.title)
        self.ctx.plots.apply_theme(self.ctx.th)            # newly created plots follow the current theme too
        self._call(tab, "apply_theme", self.ctx.th)
        self._call(tab, "clear")
        return tab

    def set_tab_shown(self, tab, on):
        """Show or hide an extension tab (panel); hiding the selected tab selects Signals."""
        i = self.tabs.indexOf(tab)
        if i < 0: return
        if not on and self.tabs.currentIndex() == i: self.tabs.setCurrentIndex(0)
        self.tabs.setTabVisible(i, bool(on))

    def remove_tabs(self, owner):
        """Remove every tab of an extension; return the set of PlotItems removed with them."""
        gone = set()
        for tab in [t for t in self.tab_list if t.owner == owner]:
            self.tabs.removeTab(self.tabs.indexOf(tab))
            self.tab_list.remove(tab)
            gone |= self.ctx.plots.forget_under(tab)
            tab.setParent(None); tab.deleteLater()
        return gone

    def _call(self, tab, method, *args):
        if tab.owner is None: return getattr(tab, method)(*args)     # built-in tab: do not hide errors
        if tab.failed: return
        try:
            return getattr(tab, method)(*args)
        except BaseException as e:
            tab.failed = True
            self.tabs.setTabEnabled(self.tabs.indexOf(tab), False)
            self.tab_failed.emit(tab.owner, e, f"tab.{method}")

    # ---- internal controls ------------------------------------------------------
    def _details_toggled(self, on):
        self.details.setVisible(on)
        self.details_btn.setText("Details ▴" if on else "Details ▾")
        self.ctx.settings.setValue("show_details", bool(on))

    def _filter_changed(self):
        self.ctx.store.set_filter(self.notch.isChecked(), self.filtered.isChecked())
        for tab in self.tab_list: self._call(tab, "on_view_changed")

    def _range_changed(self, sec):
        self.ctx.plots.set_time_range(sec)
        self.ctx.settings.setValue("window_sec", float(sec))
        for tab in self.tab_list: self._call(tab, "on_view_changed")
        self.on_analysis()

    # ---- hooks from MainWindow timers -------------------------------------------
    def on_frame(self):
        self._call(self.current_tab(), "on_frame")

    def on_analysis(self):
        if self.isVisible(): self._call(self.current_tab(), "on_analysis")

    def update_texts(self):
        e = self.ctx.store.latest["eeg"]
        if e is not None:
            self.last_label.setText("Latest: " + "  ".join(f"{n} {v:.1f} µV" for n, v in zip(self.ctx.spec.eeg.names, e)))
        for tab in self.tab_list: self._call(tab, "update_texts")
        self._update_health()
        self._update_record_text()
        if not self.review: self.clock_label.setText("🕒 " + time.strftime("%H:%M:%S"))

    def _update_health(self):
        """Effective rate (fitted from raw timestamps) + timing / package_num anomaly counts per stream."""
        h = self.ctx.store.health()
        names = {"eeg": "EEG", "opt": "Optics", "imu": "IMU"}
        if all(v["effective_fs"] is None for v in h.values()):
            self.health_label.setText(""); self.health_label.setToolTip(""); return
        issues = []                     # plain words on screen; the exact counts are in the tooltip
        for k, v in h.items():
            if v["backsteps"]: issues.append(f"{names[k]}: timestamp went backwards {v['backsteps']}×")
            if v["seq_anomalies"]: issues.append(f"{names[k]}: packet counter jumped {v['seq_anomalies']}×")
        c = self.ctx.th["q"]["Fair" if issues else "Good"]
        verdict = (f"⚠ {len(issues)} issue{'s' if len(issues) > 1 else ''} — hover for details" if issues else "OK")
        self.health_label.setText(f"Timing: <span style='color:{c}'>{verdict}</span>")
        rows = []
        for k, v in h.items():
            fs = f"{v['effective_fs']:.2f} Hz" if v["effective_fs"] else "—"
            rows.append(f"{names[k]}: {fs} measured · {v['backsteps']} timestamp backsteps · "
                        f"{v['seq_anomalies']} package_num steps ∉ {{0,1}} · Δ histogram {v['seq_deltas']}")
        self.health_label.setToolTip("Raw timestamps are never modified.\n"
                                     + ("\n".join(issues) + "\n" if issues else "")
                                     + "A packet counter jump is not necessarily packet loss (rule under verification).\n\n"
                                     + "\n".join(rows))

    # ---- state driven by the controller ------------------------------------
    def set_status(self, text):
        self.status_label.setText(text)

    def set_battery_html(self, html):
        self.batt_label.setText(html)

    def set_stream_stats(self, rate, total):
        self.rate_label.setText(f"EEG rate: {rate:.1f} samples/s (target {self.ctx.spec.eeg.fs})")
        self.count_label.setText(f"Received: {total:,} samples")

    def set_saved(self, folder_name, has_report=True):
        """'Saved <folder> — Open report · Open folder' after a recording; None hides it."""
        if not folder_name: self.saved_label.hide(); return
        links = ([f"<a href='report'>Open report</a>"] if has_report else []) + ["<a href='folder'>Open folder</a>"]
        self.saved_label.setText(f"Saved {folder_name}/ — " + " · ".join(links))
        self.saved_label.setVisible(self.rec_t0 is None)

    def set_recording(self, on):
        """Recording state must be visible from across the room: red button + elapsed time while recording."""
        self.rec_t0 = time.monotonic() if on else None
        if on: self.saved_label.hide()
        self._style_record_btn()
        self._update_record_text()

    def recording_elapsed(self):
        """Seconds since Start recording, or None when not recording."""
        return None if self.rec_t0 is None else time.monotonic() - self.rec_t0

    def _update_record_text(self):
        sec = self.recording_elapsed()
        self.record_btn.setText(self.START_TEXT if sec is None else f"■ Stop recording · {format_elapsed(sec)}")

    def _style_record_btn(self):
        if self.rec_t0 is None: self.record_btn.setStyleSheet(""); return
        self.record_btn.setStyleSheet(f"QPushButton{{background:{self.ctx.th['q']['Bad']};color:white;"
                                      "font-weight:bold;border:none;border-radius:4px;padding:4px 10px}")

    def set_record_enabled(self, on):
        self.record_btn.setEnabled(on)

    def set_disconnect_enabled(self, on):
        self.disc_btn.setEnabled(on)

    def set_events_text(self, n, last=None, saved=True):
        if last is None: self.ev_label.setText(f"Events: {n}  ·  Space = mark with label  ·  1–9 = quick mark")
        else: self.ev_label.setText(f"Events: {n}  ·  last: “{last}”" + ("" if saved else " (not recording — not saved)"))

    def set_quality(self, qs):
        self.signals_tab.set_quality(qs)

    def set_review_mode(self, note):
        """Reviewing a recorded session: hide the live-only controls, show what is being reviewed."""
        self.review = True
        for w in (self.fit_btn, self.disc_btn, self.record_btn, self.batt_label, self.rate_label, self.count_label,
                  self.clock_label, self.saved_label):
            w.hide()
        self.note_label.setText(note)

    def apply_theme(self, th):
        self._style_record_btn()
        for tab in self.tab_list: self._call(tab, "apply_theme", th)

    def clear(self):
        self.count_label.setText("Received: 0 samples")
        self.rate_label.setText("EEG rate: — samples/s")
        self.last_label.setText("Latest: —")
        self.health_label.setText("")
        self.set_events_text(0)
        for tab in self.tab_list: self._call(tab, "clear")
