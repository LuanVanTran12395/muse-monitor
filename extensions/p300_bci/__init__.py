"""P300 BCI (experimental) — stage A: acquisition, timing report, onset-locked epochs and ERP.

Design: debate/claude-p300-extension-proposal.md + -round-2.md (Codex review accepted). Stage B (model evaluation)
and stage C (online control) are NOT in this version. No result here reproduces the paper's 84.1 % / 81.2 %.
"""
import json
import math
import threading
import time

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

import musemonitor
from musemonitor import config as app_config
from musemonitor.core.online_timeline import ClockBridge, OnlineTimeline, TimelineConfig
from musemonitor.core.quality import contact_quality
from musemonitor.plugins.api import BaseTab, Extension
from musemonitor.plugins.cues import Cues
from musemonitor.storage.session import data_root

from . import epochs, instructions, report, schedule, session, timing
from .stimulus import StimulusWindow

def sessions_root():
    """<app data folder>/p300_bci — next to the app's own recordings ($MUSEMONITOR_DATA_DIR → <repo>/data →
    ~/MuseMonitor/data). Never inside the extension's code folder: data/ is git-ignored, so participant EEG is never
    committed or published."""
    return data_root() / "p300_bci"


STOP_REASONS = ("completed", "stopped", "disconnected", "unloaded", "window_closed", "writer_backlog", "writer_error")


class _Bridge(QtCore.QObject):
    analysed = QtCore.Signal(object)          # emitted from the analysis thread → queued to the GUI thread


class P300Tab(BaseTab):
    title = "P300 (experimental)"

    def __init__(self, ctx, ext):
        super().__init__(ctx)
        self.ext = ext
        v = QtWidgets.QVBoxLayout(self)
        self.status = {}
        grid = QtWidgets.QGridLayout()
        for i, key in enumerate(("Stream", "EEG timing", "Contact", "Session", "Timing so far")):
            lab = QtWidgets.QLabel(f"<b>{key}:</b>"); val = QtWidgets.QLabel("—"); val.setWordWrap(True)
            grid.addWidget(lab, i, 0, QtCore.Qt.AlignTop); grid.addWidget(val, i, 1)
            self.status[key] = val
        grid.setColumnStretch(1, 1); grid.setRowStretch(5, 1)          # rows packed at the top
        top = QtWidgets.QHBoxLayout(); top.addLayout(grid, 3)

        box = QtWidgets.QGroupBox("Session"); form = QtWidgets.QFormLayout(box)
        self.subject = QtWidgets.QLineEdit(); self.subject.setPlaceholderText("e.g. S01 (required)")
        self.subject.setValidator(QtGui.QRegularExpressionValidator(QtCore.QRegularExpression(session.SUBJECT_RE)))
        self.subject.setToolTip("Who is recorded: a code, not a name (letters, digits, - and _, up to 32). Saved in "
                                "config.json, the report and the folder name <date_time>_<ID>.")
        form.addRow("Subject ID", self.subject)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem("EEG only (no keys)", "eeg_only")
        self.mode.addItem("Response-assisted (Space recorded, reported apart)", "response_assisted")
        def spin(lo, hi, val, suffix, step=1):
            s = QtWidgets.QSpinBox(); s.setRange(lo, hi); s.setValue(val); s.setSuffix(suffix); s.setSingleStep(step)
            return s
        d = schedule.Config()
        self.soa = spin(300, 2000, int(d.soa_s * 1000), " ms", 10)
        self.flash = spin(50, 1950, int(d.flash_s * 1000), " ms", 10)
        self.reps = spin(1, 30, d.repetitions, "")
        self.trials = spin(1, 100, d.trials_per_block, "")
        self.blocks = spin(1, 20, d.blocks, "")
        self.rest = spin(0, 600, int(d.rest_s), " s")
        self.cue = spin(200, 5000, int(d.cue_s * 1000), " ms", 100)
        self.seed = spin(0, 2_000_000_000, d.seed, "")
        self.preset = QtWidgets.QComboBox()
        for name, p in epochs.PRESETS.items(): self.preset.addItem(name, name); self.preset.setItemData(
            self.preset.count() - 1, p.note, QtCore.Qt.ToolTipRole)
        self.preset.setCurrentIndex(self.preset.findData("default"))
        self.instr = QtWidgets.QCheckBox("Show step-by-step instructions first")
        self.instr.setChecked(True)
        self.instr.setToolTip("On the stimulus window, before anything is recorded: the task, an example, what to "
                              "avoid, breaks. The participant moves on with Space / → / click (← goes back).")
        self.lang = QtWidgets.QComboBox()
        for code, name in instructions.LANGUAGES.items(): self.lang.addItem(name, code)
        self.countdown = spin(0, 10, 5, " s")
        self.sound = QtWidgets.QCheckBox("Beep at session start, block start and end")
        self.sound.setChecked(True)
        self.sound.setToolTip("Short tones on the participant's side: start of the session and of each block "
                              "(high beep), end (two rising tones; one low tone if the session was interrupted). "
                              "Played only when no cell is flashing; each one is logged with its time.")
        self.countdown.setToolTip("Large countdown on the stimulus window before the first trial (0 = none)")
        for label, w in (("Mode", self.mode), ("Stimulus interval", self.soa), ("Flash", self.flash),
                         ("Repetitions per trial", self.reps), ("Trials per block", self.trials),
                         ("Blocks", self.blocks), ("Rest between blocks", self.rest), ("Cue", self.cue),
                         ("Random seed", self.seed), ("ERP preset", self.preset), ("Instructions", self.instr),
                         ("Instruction language", self.lang), ("Countdown", self.countdown), ("Sound", self.sound)):
            form.addRow(label, w)
        top.addWidget(box, 2)
        v.addLayout(top)

        row = QtWidgets.QHBoxLayout()
        self.window_btn = QtWidgets.QPushButton("Open stimulus window")
        self.start_btn = QtWidgets.QPushButton("▶ Start")
        self.stop_btn = QtWidgets.QPushButton("■ Stop"); self.stop_btn.setEnabled(False)
        self.analyse_btn = QtWidgets.QPushButton("Analyse session…")
        self.folder_btn = QtWidgets.QPushButton("Open folder"); self.folder_btn.setEnabled(False)
        self.report_btn = QtWidgets.QPushButton("Open report"); self.report_btn.setEnabled(False)
        self.report_btn.setToolTip("report.html of the last analysed session: P300 / ERP, good epochs, electrodes, "
                                   "timing deviations (written automatically after each session)")
        for b in (self.window_btn, self.start_btn, self.stop_btn, self.analyse_btn, self.folder_btn, self.report_btn):
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        self.window_btn.clicked.connect(ext.show_window)
        self.start_btn.clicked.connect(ext.start)
        self.stop_btn.clicked.connect(lambda: ext.stop("stopped"))
        self.analyse_btn.clicked.connect(self._pick_session)
        self.folder_btn.clicked.connect(ext.open_folder)
        self.report_btn.clicked.connect(ext.open_report)

        self.plot = ctx.plots.widget(pg.PlotWidget())
        self.plot.setMinimumHeight(220)
        item = ctx.plots.plot(self.plot.getPlotItem(), timed=False)
        item.setLabel("bottom", "Time from onset", units="s"); item.setLabel("left", "µV")
        item.addLegend(offset=(5, 5))
        self.curves = {"target": item.plot(name="target"), "nontarget": item.plot(name="non-target")}
        self.plot.setAccessibleName("ERP of the last analysed session")
        v.addWidget(self.plot, 1)
        self.summary = QtWidgets.QLabel("No session analysed yet."); self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        v.addWidget(ctx.plots.muted_label(
            "Stage A — acquisition and ERP only (no classifier, no online control). Onsets are Qt paint times; "
            "the delay until pixels appear and the fixed Bluetooth delay are NOT measured. EEG times are "
            "host-receive estimates. Synthetic tests are not evidence that this works on a person."))

    def read_config(self):
        return schedule.Config(
            soa_s=self.soa.value() / 1000, flash_s=self.flash.value() / 1000, repetitions=self.reps.value(),
            trials_per_block=self.trials.value(), blocks=self.blocks.value(), rest_s=float(self.rest.value()),
            cue_s=self.cue.value() / 1000, seed=int(self.seed.value()), mode=self.mode.currentData())

    def write_config(self, cfg):
        self.soa.setValue(int(round(cfg.soa_s * 1000))); self.flash.setValue(int(round(cfg.flash_s * 1000)))
        self.reps.setValue(cfg.repetitions); self.trials.setValue(cfg.trials_per_block); self.blocks.setValue(cfg.blocks)
        self.rest.setValue(int(cfg.rest_s)); self.cue.setValue(int(round(cfg.cue_s * 1000))); self.seed.setValue(cfg.seed)
        self.mode.setCurrentIndex(max(0, self.mode.findData(cfg.mode)))

    def set_running(self, running):
        for w in (self.subject, self.mode, self.soa, self.flash, self.reps, self.trials, self.blocks, self.rest, self.cue, self.seed,
                  self.preset, self.analyse_btn, self.instr, self.lang, self.countdown, self.sound):
            w.setEnabled(not running)
        self.stop_btn.setEnabled(running)

    def _pick_session(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "P300 session folder", str(sessions_root()))
        if folder: self.ext.analyse(folder)

    def show_analysis(self, res):
        if "error" in res:
            self.summary.setText(f"Analysis failed: {res['error']}"); return
        for name, curve in self.curves.items():
            mean, _, n = res["erp"][name]
            curve.setData(res["times"], mean[0]) if n else curve.clear()
        c = res["counts"]
        rejected = ", ".join(f"{k} {v}" for k, v in c.items() if k != "kept" and v)
        flags = ([f"INCOMPLETE ({res['stop_reason']})"] if res["incomplete"] else []) + \
                ([f"mode: {res['mode']} — not EEG-only"] if res["mode"] == "response_assisted" else [])
        self.summary.setText(
            f"{res['folder']}: preset {res['preset']['name']}, timeline {res['timeline']} · target epochs "
            f"{res['erp']['target'][2]}, non-target {res['erp']['nontarget'][2]} · rejected: {rejected or 'none'}"
            + (" · " + " · ".join(flags) if flags else "")
            + (" · report.html written" if res.get("report") else
               (f" · report failed: {res['report_error']}" if res.get("report_error") else "")))

    def update_texts(self):                       # twice per second, even when hidden
        ext = self.ext
        if ext.writer is not None and ext.writer.error: ext.stop("writer_error")
        for k, v in ext.status_texts().items(): self.status[k].setText(v)
        blockers = ext.blockers() if ext.phase == "idle" else []
        self.start_btn.setEnabled(ext.phase == "idle" and not blockers)
        self.start_btn.setToolTip("\n".join(blockers) or "Start a session")

    def apply_theme(self, th):
        self.curves["target"].setPen(pg.mkPen(th["hr"], width=2))
        self.curves["nontarget"].setPen(pg.mkPen(th["hbr"], width=2))

    def clear(self):
        pass


class P300BCI(Extension):
    id = "p300_bci"
    name = "P300 BCI (experimental)"
    version = "0.1.0"
    requires_api = 3
    category = "Other"            # → "BCI" once appendix A of the proposal is approved
    description = ("P300 3×3 stimulus (5 commands), session recording with a timing report, onset-locked epochs and "
                   "ERP. Stage A: no classifier, no online control.")

    mono = staticmethod(time.monotonic)      # replaceable in tests
    unix = staticmethod(time.time)

    @classmethod
    def supports(cls, spec):
        return spec.eeg.n >= 2

    # ---- lifecycle -----------------------------------------------------------------------------------
    def activate(self, app):
        self.fs = float(app.spec.eeg.fs)
        self.channels = list(app.spec.eeg.names)
        self.writer = None
        self.runner = None
        self.plan = None
        self.subject_id = ""
        self.records = {}
        self.trial_rec = None
        self.window = None
        self.last_folder = None
        self.counts = dict(flashes=0, missed=0, trials=0, no_paint=0)
        self.hook_s = []
        self.phase = "idle"                  # idle | instructions | countdown | running
        self.lang = "vi"
        self.page_i = 0
        self._count = QtCore.QTimer(); self._count.setInterval(1000); self._count.timeout.connect(self._count_tick)
        self._demo = QtCore.QTimer(); self._demo.setInterval(700); self._demo.timeout.connect(self._demo_tick)
        self._rest = QtCore.QTimer(); self._rest.setInterval(200); self._rest.timeout.connect(self._rest_tick)
        self.contact_every_s = 2.0
        self.last_contact = None
        self.rest_end = None
        self.cues = Cues(enabled=str(app.setting("sound", True)).lower() in ("true", "1"))
        self._timer = QtCore.QTimer(); self._timer.setSingleShot(True)
        self._timer.setTimerType(QtCore.Qt.PreciseTimer); self._timer.timeout.connect(self._tick)
        self._bridge = _Bridge(); self._bridge.analysed.connect(self._analysed)
        self._reset_timeline()
        self.tab = app.add_tab(P300Tab(app.view, self))
        saved = app.setting("config")
        if saved:
            try: self.tab.write_config(schedule.Config(**json.loads(saved)))
            except (TypeError, ValueError): pass
        self.tab.subject.setText(str(app.setting("subject", "") or ""))
        self.tab.instr.setChecked(str(app.setting("instructions", True)).lower() in ("true", "1"))
        self.tab.lang.setCurrentIndex(max(0, self.tab.lang.findData(app.setting("language", "vi"))))
        self.tab.countdown.setValue(int(app.setting("countdown_s", 5)))
        self.tab.sound.setChecked(self.cues.enabled)

    def deactivate(self):
        self.stop("unloaded")
        self._timer.stop(); self._count.stop(); self._demo.stop(); self._rest.stop()
        if self.window is not None:
            self.window.on_closed = lambda: None; self.window.close(); self.window = None

    def on_connected(self, name):
        self._reset_timeline()

    def on_disconnected(self):
        self.stop("disconnected")
        self._reset_timeline()

    def _reset_timeline(self):
        self.bridge = ClockBridge(self.unix, self.mono)
        self.timeline = OnlineTimeline(TimelineConfig(fs_nominal=self.fs))
        self.index = 0

    # ---- EEG hook (GUI thread: keep it short) ----------------------------------------------------------------
    def on_eeg_samples(self, x, ts_raw):
        t_start = time.perf_counter()
        n = x.shape[1]
        offset, mono_now, stepped = self.bridge.measure()
        r = np.asarray(ts_raw, dtype=float) + offset
        res = self.timeline.push(r, mono_now, uncertain="clock_step" if stepped else None)
        flag = res.reason or ("uncertain" if res.uncertain else None)
        if self.writer is not None:
            ok = (self.writer.put("clock", (mono_now, mono_now - offset, offset, stepped)) and
                  self.writer.put("eeg", (self.index, np.array(ts_raw, float), r, res.t_out, res.segment, flag,
                                          np.array(x, float))))
            if not ok:
                self.index += n
                self.stop("writer_error" if self.writer.error else "writer_backlog"); return
            self.hook_s.append(time.perf_counter() - t_start)
        self.index += n

    # ---- readiness ------------------------------------------------------------------------------------------------
    def contact(self):
        st, need = self.app.store, int(app_config.QUALITY_SEC * self.fs)
        if st.eeg.n < need: return None
        return {n: q[0] for n, q in zip(self.channels, contact_quality(st.eeg.get(need), self.fs))}

    def blockers(self, cfg=None):
        """Why a session cannot start now (empty = ready)."""
        out = []
        if not self.tab.subject.hasAcceptableInput(): out.append("Enter a subject ID (e.g. S01).")
        if not self.app.is_streaming: out.append("Connect the headset and wait for the stream.")
        acquired = self.timeline.counters.get("period_acquired", 0) > 0
        if not acquired:
            out.append(f"Measuring EEG timing ({self.index / self.fs:.0f} of {self.timeline.cfg.min_fit_s:.0f} s)…")
        if self.timeline.timing_uncertain:
            out.append(f"EEG timing uncertain ({self.timeline.timing_uncertain}) — reconnect the headset.")
        preset = epochs.PRESETS[self.tab.preset.currentData()]
        missing = [c for c in preset.channels if c not in self.channels]
        if missing: out.append(f"Preset {preset.name} needs {', '.join(missing)} — not on this device.")
        q = self.contact()
        bad = [c for c in preset.channels if q and q.get(c) in ("Bad", "No signal")]
        if bad: out.append("Poor contact: " + ", ".join(f"{c} {q[c]}" for c in bad) + ".")
        out += (cfg or self.tab.read_config()).errors()
        return out

    # ---- session ----------------------------------------------------------------------------------------------------
    def show_window(self):
        if self.window is None:
            self.window = StimulusWindow(self.mono, self._painted, self._key, self._window_closed, self._click)
        self.window.show(); self.window.raise_(); self.window.activateWindow()
        return self.window

    def start(self):
        """Start button: check, then instructions (optional) → countdown (optional) → session. Nothing is recorded
        before the session begins, so reading time is not part of the data or the timing report."""
        if self.phase != "idle": return False
        cfg = self.tab.read_config()
        blockers = self.blockers(cfg)
        if blockers:
            self.app.show_status("Cannot start: " + blockers[0], 8000); return False
        self.app.set_setting("config", json.dumps(cfg.to_dict()))
        self.app.set_setting("subject", self.tab.subject.text())
        self.subject_id = self.tab.subject.text()
        self.app.set_setting("instructions", self.tab.instr.isChecked())
        self.app.set_setting("language", self.tab.lang.currentData())
        self.app.set_setting("countdown_s", self.tab.countdown.value())
        self.app.set_setting("sound", self.tab.sound.isChecked())
        self.cues.enabled = self.tab.sound.isChecked()
        self.plan = schedule.build(cfg)
        self.lang = self.tab.lang.currentData()
        self.pages = instructions.pages(self.plan, self.lang) if self.tab.instr.isChecked() else []
        self.prep = dict(instructions_shown=bool(self.pages), language=self.lang,
                         countdown_s=self.tab.countdown.value(), prepared_mono=self.mono())
        self.show_window()
        self.tab.set_running(True)
        if self.pages:
            self.phase, self.page_i = "instructions", 0
            self._show_page()
            return True
        return self._start_countdown()

    # ---- instructions and countdown (before anything is recorded) ----------------------------------------------------
    def _show_page(self):
        page = self.pages[self.page_i]
        self._demo.stop()
        if page.get("demo"):
            self.window.lit, self.window.cue = None, 1
            self._demo.start()
        self.window.show_page(page, footer=f"{self.page_i + 1} / {len(self.pages)}", index=self.page_i,
                              total=len(self.pages), nav=instructions.NAV[self.lang])

    def _demo_tick(self):
        """Example page: the target (outlined) and one other cell flash slowly, in turn — not recorded."""
        if self.window is None or self.phase != "instructions": self._demo.stop(); return
        cycle = [1, None, 5, None]
        self._demo_i = (getattr(self, "_demo_i", -1) + 1) % len(cycle)
        self.window.lit = cycle[self._demo_i]; self.window.update()

    def _next_page(self, step=1):
        if self.phase != "instructions": return
        i = self.page_i + step
        if i < 0: return
        if i >= len(self.pages):
            self._demo.stop(); self._start_countdown(); return
        self.page_i = i; self._show_page()

    def _start_countdown(self):
        n = self.tab.countdown.value()
        self.window.lit = self.window.cue = None
        if n <= 0: return self._begin()
        self.phase, self.count_left, self.count_total = "countdown", n, n
        self.window.show_countdown(n, instructions.COUNTDOWN_TEXT[self.lang], 1.0)
        self._count.start()
        return True

    def _count_tick(self):
        if self.phase != "countdown": self._count.stop(); return
        self.count_left -= 1
        if self.count_left > 0:
            self.window.show_countdown(self.count_left, instructions.COUNTDOWN_TEXT[self.lang],
                                       self.count_left / self.count_total); return
        self._count.stop()
        self._begin()

    def _click(self):
        if self.phase == "instructions": self._next_page()

    def _cancel_prep(self, reason):
        self._count.stop(); self._demo.stop()
        self.phase = "idle"
        self.tab.set_running(False)
        if self.window is not None:
            self.window.lit = self.window.cue = None
            self.window.clear_overlay()
            self.window.set_state(message=instructions.CANCELLED_TEXT.get(getattr(self, "lang", "en")))
        self.app.show_status(f"P300: cancelled before the session ({reason}) — nothing recorded", 6000)

    def _begin(self):
        """End of the countdown: check again (the stream may have changed while reading), then record."""
        cfg = self.plan.config
        blockers = self.blockers(cfg)
        if blockers:
            self._cancel_prep("not ready: " + blockers[0]); return False
        self.window.clear_overlay()
        self.phase = "running"
        folder = session.new_folder(sessions_root(), subject=self.subject_id)
        q = self.contact() or {}
        preset = epochs.PRESETS[self.tab.preset.currentData()]
        config = dict(
            subject_id=self.subject_id,
            schedule=cfg.to_dict(), mode=cfg.mode, commands=schedule.COMMANDS, flashing=list(schedule.FLASHING),
            preset=preset.to_dict(), fs=self.fs, channels=self.channels, device=dict(
                profile=getattr(self.app.view.profile, "id", None), name=getattr(self.app.main_window, "device_name", "")),
            contact_at_start=q, versions=dict(app=musemonitor.__version__, extension=self.version,
                                              numpy=np.__version__, qt=QtCore.qVersion()),
            app_recording=self.app.recording_path if self.app.is_recording else None,
            display_latency_s=None, display_latency_method=None, onset_source="painted_mono (Qt paintEvent)",
            preparation=dict(self.prep, seconds_before_session=round(self.mono() - self.prep["prepared_mono"], 3)),
            started_unix=self.unix(), planned_duration_s=self.plan.duration_s,
            notes="Stage A. EEG times are host-receive estimates; display latency and BLE delay are not measured.")
        self.writer = session.SessionWriter(folder, config, self.channels, response_keys=cfg.mode == "response_assisted")
        self.writer.put("log", f"start: subject {self.subject_id}, {len(self.plan.stims)} flashes, "
                               f"{len(self.plan.trials)} trials, mode {cfg.mode}")
        self.last_folder = folder
        self.records, self.trial_rec, self.hook_s = {}, None, []
        self.steps_at_start = self.bridge.steps                  # count clock steps of THIS session only
        self.last_contact = None; self._log_contact()             # electrode contact every 2 s → contact.csv
        self.seq_at_start = self._seq_anomalies()
        self.counts = dict(flashes=0, missed=0, trials=0, no_paint=0)
        self.show_window()
        self.window.set_state(lit=None, cue=None, message=instructions.GET_READY_TEXT[self.lang])
        self.runner = schedule.Runner(self.plan, self.mono() + 1.0)
        self.tab.set_running(True); self.tab.folder_btn.setEnabled(True)
        if self.app.is_recording: self.app.mark_event(f"p300 session start {self.subject_id}")    # one marker, not per flash
        self._beep("go", "session start")
        self._schedule_next()
        return True

    def _schedule_next(self):
        due = self.runner.next_due() if self.runner else None
        if due is None: return
        self._timer.start(max(0, int((due - self.mono()) * 1000)))

    def _tick(self):
        if self.runner is None: return
        now = self.mono()
        self._log_contact(now)
        for planned, action in self.runner.pop_due(now):
            self._do(action, planned, now)
            if self.writer is None: return                       # stopped while handling (e.g. writer full)
        if self.runner.finished: self.stop("completed"); return
        self._schedule_next()

    def _do(self, a, planned, now):
        w, cfg = self.window, self.plan.config
        if a.kind == "trial_start":
            tr = a.ref
            self.trial_rec = dict(trial=tr.trial, block=tr.block, target=tr.target, start_mono=now, aborted=False)
        elif a.kind == "cue_on":
            self.trial_rec["cue_on_mono"] = now
            w.set_state(lit=None, cue=a.ref.target,
                        message=instructions.CUE_TEXT[self.lang].format(name=schedule.COMMANDS[a.ref.target]))
        elif a.kind == "cue_off":
            hint = instructions.RESPOND_TEXT[self.lang] if cfg.mode == "response_assisted" else ""
            w.set_state(cue=None, message=hint)
        elif a.kind == "flash_on":
            st = a.ref
            late = now - planned
            rec = dict(seq=st.seq, block=st.block, trial=st.trial, rep=st.rep, cell=st.cell, is_target=st.is_target,
                       planned_mono=planned, fired_mono=now, painted_mono=None, late_ms=round(late * 1000, 3),
                       missed=late > cfg.flash_s / 2)       # kept on screen, but its epoch is rejected
            self.records[st.seq] = rec
            self.counts["flashes"] += 1; self.counts["missed"] += rec["missed"]
            w.set_state(lit=st.cell, tag=("on", st.seq))
        elif a.kind == "flash_off":
            rec = self.records.get(a.ref.seq)
            if rec is not None: rec.update(off_planned_mono=planned, off_fired_mono=now)
            w.set_state(lit=None, tag=("off", a.ref.seq))
        elif a.kind == "trial_end":
            self.trial_rec["end_mono"] = now
            self._put("trial", self.trial_rec); self.trial_rec = None
            self.counts["trials"] += 1
        elif a.kind == "rest_on":
            w.set_state(lit=None, cue=None, message="")
            self.rest_end = self.runner.t0 + a.ref[1]
            self._rest_tick(); self._rest.start()
        elif a.kind == "rest_off":
            self._rest.stop(); self.rest_end = None
            w.clear_overlay(); w.set_state(message="")
            self._beep("go", "block start")

    def _log_contact(self, now=None):
        """Contact quality of every channel over the last 2 s (same estimate as the fit-test), at most every
        ``contact_every_s`` of monotonic time — driven by the session's own ticks (schedule, break screen)."""
        if self.writer is None: return
        now = self.mono() if now is None else now
        if self.last_contact is not None and now - self.last_contact < self.contact_every_s: return
        st, need = self.app.store, int(app_config.QUALITY_SEC * self.fs)
        if st.eeg.n < need: return
        self.last_contact = now
        q = [(lvl, float(sig), float(mains)) for lvl, sig, mains in contact_quality(st.eeg.get(need), self.fs)]
        self._put("contact", (now, q))

    def _seq_anomalies(self):
        """package_num steps other than 0/1 counted by the app for EEG (None when the device has no counter) — not a
        lost-packet count (the Athena rule is unverified)."""
        try:
            return int(self.app.store.health()["eeg"]["seq_anomalies"])
        except (KeyError, TypeError, ValueError, AttributeError):
            return None

    def _rest_tick(self):
        """Break between blocks: seconds left, then the same large countdown as before the session for the last
        ``countdown`` seconds (purely visual; the schedule is unchanged)."""
        if self.rest_end is None or self.window is None: self._rest.stop(); return
        self._log_contact()
        left = self.rest_end - self.mono()
        n = self.tab.countdown.value()
        if n > 0 and left <= n:
            whole = max(1, math.ceil(left))
            self.window.show_countdown(whole, instructions.NEXT_BLOCK_TEXT[self.lang], max(0.0, left) / n)
        else:
            self.window.show_rest(max(0.0, left), instructions.REST_TITLE[self.lang], instructions.REST_HINT[self.lang])

    def _beep(self, tone, what):
        """Participant-side tone, logged with its monotonic time (it can evoke an auditory response: it is only
        played when no cell is flashing — session start, block start, end)."""
        if not self.cues.enabled: return
        t = self.mono()
        self.cues.play(tone)
        if self.writer is not None: self.writer.put("log", f"sound {tone} ({what}) at mono {t:.4f}")
        return t

    def _painted(self, tag, mono):
        kind, seq = tag
        rec = self.records.get(seq)
        if rec is None: return
        if kind == "on" and rec["painted_mono"] is None:
            rec["painted_mono"] = mono
        elif kind == "off":
            rec["off_painted_mono"] = mono
            if rec["painted_mono"] is None: self.counts["no_paint"] += 1
            self._put("stim", self.records.pop(seq))

    def _key(self, ev):
        """Instructions: Space / → / Return next, ← back, Esc cancels. During the session — eeg_only: keys are
        ignored (they never reveal the target); response_assisted: Space recorded apart."""
        if self.phase in ("instructions", "countdown") and not ev.isAutoRepeat():
            k = ev.key()
            if k == QtCore.Qt.Key_Escape: self._cancel_prep("Esc"); return
            if self.phase == "instructions":
                if k in (QtCore.Qt.Key_Space, QtCore.Qt.Key_Right, QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                    self._next_page(1)
                elif k == QtCore.Qt.Key_Left:
                    self._next_page(-1)
            return
        if self.writer is None or self.plan.config.mode != "response_assisted" or ev.isAutoRepeat(): return
        if ev.key() == QtCore.Qt.Key_Space:
            self._put("key", dict(key="space", qt_timestamp_ms=ev.timestamp(), handled_mono=self.mono(),
                                  handled_unix=self.unix()))

    def _window_closed(self):
        self.window = None
        if self.phase in ("instructions", "countdown"): self._cancel_prep("window closed"); return
        self.stop("window_closed")

    def _put(self, kind, payload):
        if self.writer is not None and not self.writer.put(kind, payload):
            self.stop("writer_error" if self.writer.error else "writer_backlog")

    def stop(self, reason):
        """End the session for ``reason`` (STOP_REASONS): files are closed by the writer thread; the GUI waits at
        most 2 s. Safe to call when no session runs."""
        if self.phase in ("instructions", "countdown"):          # nothing recorded yet: just cancel
            self._cancel_prep(reason); return None
        writer, self.writer = self.writer, None
        self.phase = "idle"
        if writer is None: return None
        self._timer.stop(); self._rest.stop(); self.rest_end = None
        self.runner = None
        now = self.mono()
        if self.cues.enabled:                                    # end of the session: heard by the participant
            self.cues.play("done" if reason == "completed" else "retry")
            writer.put("log", f"sound {'done' if reason == 'completed' else 'retry'} (session end) at mono {now:.4f}")
        for seq in sorted(self.records): writer.put("stim", self.records[seq])    # flashes without an "off" paint
        self.records = {}
        if self.trial_rec is not None:
            writer.put("trial", dict(self.trial_rec, end_mono=now, aborted=True)); self.trial_rec = None
        writer.put("log", f"stop requested: {reason}")
        tl = dict(rebases=[r.__dict__ for r in self.timeline.rebases], forward_jumps=list(self.timeline.forward_jumps),
                  counters=dict(self.timeline.counters))
        hooks, fs = list(self.hook_s), self.fs
        steps = self.bridge.steps - getattr(self, "steps_at_start", 0)
        seq_now, seq_start = self._seq_anomalies(), getattr(self, "seq_at_start", None)
        seq = None if seq_now is None or seq_start is None else seq_now - seq_start
        try: deltas = {str(k): v for k, v in self.app.store.health()["eeg"]["seq_deltas"].items()}
        except (KeyError, TypeError, AttributeError): deltas = None
        report = lambda w: timing.summarize(w.stims(), w.eeg_arrays(), fs, clock_steps=steps, timeline=tl,
                                            writer=dict(backlog_max=w.backlog_max, queue_max=session.QUEUE_MAX),
                                            hook_s=hooks, display_latency_s=None, seq_anomalies=seq,
                                            seq_deltas=deltas)
        in_time = writer.close(reason, report, timeout_s=2.0)
        if self.window is not None:
            self.window.clear_overlay()
            self.window.set_state(lit=None, cue=None, message=instructions.ENDED_TEXT[self.lang].format(reason=reason))
        self.tab.set_running(False)
        if self.app.is_recording: self.app.mark_event("p300 session end")
        self.app.show_status(f"P300 session ended: {reason}" + ("" if in_time else " (files still closing)"), 8000)
        if reason == "completed": self.analyse(writer.folder, wait=writer)
        return in_time

    # ---- analysis (background thread) ---------------------------------------------------------------------------------
    def analyse(self, folder, wait=None):
        preset = epochs.PRESETS[self.tab.preset.currentData()]
        lang = self.tab.lang.currentData()
        self.tab.summary.setText("Analysing…")

        def work():
            try:
                if wait is not None: wait.finished.wait(30)
                s = session.load(folder)
                res = epochs.analyse_session(s, preset, timing.fit_timeline)
                res.update(folder=str(folder), stop_reason=s["config"].get("stop_reason"))
                try:
                    res["report"] = str(report.write(folder, lang=lang))
                except Exception as e:                      # the ERP in the tab still shows
                    res["report_error"] = f"{type(e).__name__}: {e}"
            except Exception as e:
                res = dict(error=f"{type(e).__name__}: {e}")
            self._bridge.analysed.emit(res)
        threading.Thread(target=work, name="p300-analysis", daemon=True).start()

    def _analysed(self, res):
        self.last_report = res.get("report")
        if getattr(self, "tab", None) is not None:
            self.tab.show_analysis(res)
            self.tab.report_btn.setEnabled(bool(self.last_report))
        self.last_analysis = res

    def open_report(self):
        if getattr(self, "last_report", None):
            from PySide6 import QtGui
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.last_report))

    def open_folder(self):
        if self.last_folder:
            from PySide6 import QtGui
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.last_folder)))

    # ---- status (twice per second, from the tab) ------------------------------------------------------------------------
    def status_texts(self):
        q = self.contact()
        preset = epochs.PRESETS[self.tab.preset.currentData()]
        tl = self.timeline
        if tl.timing_uncertain: timing_txt = f"uncertain ({tl.timing_uncertain}) — reconnect"
        elif tl.counters.get("period_acquired", 0): timing_txt = f"ready · {1 / tl.period:.2f} Hz measured"
        else: timing_txt = f"measuring ({self.index / self.fs:.0f} / {tl.cfg.min_fit_s:.0f} s)"
        if self.phase == "instructions":
            sess = f"{self.subject_id}: instructions on the stimulus window (page {self.page_i + 1}/{len(self.pages)}) — nothing recorded yet"
        elif self.phase == "countdown":
            sess = f"{self.subject_id}: countdown {self.count_left} s — nothing recorded yet"
        elif self.writer is not None:
            done = self.counts
            sess = (f"running · trial {done['trials'] + 1}/{len(self.plan.trials)} · flash {done['flashes']}/"
                    f"{len(self.plan.stims)} · {self.writer.folder.name}")
        else:
            sess = "idle" + (f" · last: {self.last_folder.name}" if self.last_folder else "")
        late = timing.dist([r for r in self.hook_s[-200:]]) if self.hook_s else None
        unpainted = self.counts.get("no_paint", 0)
        warn = (f" · ⚠ {unpainted} flashes not painted — keep the stimulus window visible" if unpainted else "")
        timing_so_far = (f"missed {self.counts['missed']} of {self.counts['flashes']} flashes{warn} · writer backlog "
                         f"{self.writer.q.qsize() if self.writer else 0} · EEG hook p95 "
                         f"{late['p95'] if late else '—'} ms")
        return {"Stream": "streaming" if self.app.is_streaming else "not connected",
                "EEG timing": timing_txt,
                "Contact": ", ".join(f"{c} {q.get(c, '—')}" for c in preset.channels) if q else "—",
                "Session": sess, "Timing so far": timing_so_far}


EXTENSION = P300BCI
