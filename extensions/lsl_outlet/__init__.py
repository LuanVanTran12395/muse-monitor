"""LSL Outlet — streams live Muse S Athena EEG, your event markers and a timing-quality stream to Lab
Streaming Layer, for LabRecorder or any LSL inlet.

Streams (while started, see Extensions ▸ LSL Outlet):

    MuseMonitor-Athena-EEG       type EEG      4 ch float32, µV, nominal 256 Hz, one timestamp per sample
    MuseMonitor-Athena-Markers   type Markers  1 ch string: the label of each event (Space key / extensions)
    MuseMonitor-Athena-Quality   type Quality  1 ch string: one JSON line per timing-state change
                                               (schema "musemonitor.quality/1", see QUALITY EVENTS below)

Timestamps: BrainFlow's host-receive time of every sample is mapped to LSL's clock and smoothed by
``musemonitor.core.online_timeline.OnlineTimeline`` (strictly increasing, rate tracked from the host
timestamps). They are an ESTIMATE from host receive times, not calibrated against an external stimulus;
the Quality stream says which samples the algorithm flagged. The EEG outlet's timestamps never go back:
after a backward re-anchoring (rebase) the samples that would go back are dropped and counted (the CSV
keeps every sample); a drop episode longer than ``MAX_REBASE_DROP_S`` closes the EEG outlet.

The timeline follows the DEVICE CONNECTION, not the outlets: it runs on every EEG chunk while connected,
so stopping and restarting the streams keeps its flags (a stop/start does not empty the BLE/BrainFlow
buffer). Only a disconnect resets it.

QUALITY EVENTS — LSL timestamp = local_clock() when emitted (never decreasing); every record has
``v, event, seq, segment``; ``input_sample_index`` counts every EEG sample the timeline received in this
connection (dropped ones included), ``published_sample_index`` counts the samples of the current EEG outlet.

    open          streams started; current state (inherited=true: the timeline already ran in this connection)
    status        the same snapshot again: when the Quality stream gets its first consumer (an inlet only
                  receives what is sent after it connects, so a recorder never sees ``open``) and every
                  STATUS_EVERY_S; ``reason`` = the state of the latest sample, until the next ``state``
    state         the flag reason changed (null = unflagged); effective_eeg_ts = LSL time of the first sample
                  in the new state if it was published, else null
    rebase        timeline re-anchored; timeline_ts = the new time of its first sample (maybe never published)
    resume        publishing again after a drop episode; first_published_eeg_ts, dropped
    eeg_closed    EEG outlet closed (code "rebase_drop_limit"); Markers and Quality keep running
    marker_uncertain  a marker whose clock offset is uncertain (system clock stepped around it)
    guard_drop    samples dropped outside a drop episode (should never happen; a bug if it does)
    close         streams stopped (stop / disconnect / app closed); counters

Not done here: optics and IMU outlets, auto-start, replaying review windows. Needs ``pip install pylsl``
(``pip install -e .[lsl]``); without it the extension stays loaded and Start explains what is missing.
"""
import hashlib
import json
import math
import time
from collections import deque
from dataclasses import asdict

import numpy as np

from musemonitor import __version__
from musemonitor.core.online_timeline import ClockBridge, OnlineTimeline, TimelineConfig
from musemonitor.plugins.api import Extension

PREFIX = "MuseMonitor-Athena"
QUALITY_SCHEMA = "musemonitor.quality/1"
MAX_REBASE_DROP_S = 2.0          # trial value: one drop episode may drop at most ceil(this × fs_nominal) samples
STATUS_EVERY_S = 5.0             # Quality snapshot period (and when a consumer connects)
LINGER_S = 1.0                   # keep closed outlets alive this long: liblsl drops what is pushed right before destroy
COST_KEEP = 100_000              # hook timings kept for the status report (≈ 80 min of EEG chunks)
TIMING_NOTE = "estimated from host receive timestamps; not calibrated against an external stimulus"


def load_pylsl():
    """(pylsl, None) or (None, reason). Also loads the native liblsl and reads its clock once."""
    try:
        import pylsl
        pylsl.local_clock()
    except Exception as e:                               # ImportError, OSError/RuntimeError from liblsl…
        return None, f"{type(e).__name__}: {e}"
    return pylsl, None


def source_base(board_id, device_name):
    """Stable per device on one machine. Two headsets with the SAME BLE name give the same id."""
    return "musemonitor-athena-" + hashlib.sha256(f"{board_id}:{device_name}".encode()).hexdigest()[:12]


def _info(lsl, name, type_, names, units, ch_type, srate, fmt, source_id, desc):
    info = lsl.StreamInfo(name, type_, len(names), srate, fmt, source_id)
    d = info.desc()
    for k, v in desc.get("acquisition", {}).items(): d.append_child_value(k, str(v))
    timing = d.append_child("timing")
    for k, v in desc.get("timing", {}).items():
        if isinstance(v, dict):
            node = timing.append_child(k)
            for kk, vv in v.items(): node.append_child_value(kk, str(vv))
        else:
            timing.append_child_value(k, str(v))
    for k, v in desc.get("extra", {}).items(): d.append_child_value(k, str(v))
    chns = d.append_child("channels")
    for n in names:
        ch = chns.append_child("channel")
        ch.append_child_value("label", n)
        if units: ch.append_child_value("unit", units)
        if ch_type: ch.append_child_value("type", ch_type)
    return info


class Bundle:
    """The three outlets of one Start…Stop, with the EEG outlet's own counters."""
    def __init__(self, lsl, eeg, markers, quality):
        self.lsl, self.eeg, self.markers, self.quality = lsl, eeg, markers, quality
        self.received = self.published = self.rebase_dropped = self.guard_dropped = 0
        self.markers_sent = 0
        self.had_consumers = False
        self.next_status = math.inf

    def eeg_counters(self):
        return dict(received=self.received, published=self.published,
                    rebase_dropped=self.rebase_dropped, guard_dropped=self.guard_dropped)


class Monitor:
    """One device connection: clock bridge + timeline (always running) and, while started, the outlets.
    Pure Python/numpy (no Qt): the extension feeds it; tests drive it directly with simulated clocks."""

    def __init__(self, lsl, fs, names, source, monitoring_since="connect", unix_clock=time.time,
                 mono_clock=None, max_drop_s=MAX_REBASE_DROP_S):
        self.lsl, self.fs, self.names, self.source = lsl, float(fs), list(names), source
        self.mono = mono_clock or lsl.local_clock
        self.bridge = ClockBridge(unix_clock, self.mono)
        self.cfg = TimelineConfig(fs_nominal=self.fs)
        self.timeline = OnlineTimeline(self.cfg)
        self.monitoring_since = monitoring_since
        self.max_drop = int(math.ceil(max_drop_s * self.fs))
        self.watermark = -math.inf          # last EEG timestamp published by ANY outlet of this connection
        self.reason = None                  # flag reason of the last chunk
        self.episode = None                 # drop episode after a backward rebase: dict(start, dropped)
        self.bundle = None
        self.seq = 0
        self.last_q = -math.inf
        self.messages = []                  # for the UI (eeg closed…), drained by the extension
        self.totals = dict(timeline_samples=0, published=0, rebase_dropped=0, guard_dropped=0,
                           monitored_while_eeg_off=0, markers=0, markers_uncertain=0, eeg_outlets=0,
                           drop_episodes=0, eeg_closed=0)
        self.cost = deque(maxlen=COST_KEEP)          # (seconds, eeg outlet open)

    # ---- outlets ----------------------------------------------------------------------------------
    @property
    def running(self):
        return self.bundle is not None

    def open(self):
        if self.bundle is not None: return
        lsl, s = self.lsl, self.source
        desc = dict(
            acquisition=dict(manufacturer="Interaxon", model="Muse S Athena", software=f"MuseMonitor {__version__}"),
            timing=dict(clock_policy="host_receive_smoothed", note=TIMING_NOTE,
                        quality_stream=f"{PREFIX}-Quality", monitoring_since=self.monitoring_since,
                        max_rebase_drop_samples=self.max_drop, timeline=asdict(self.cfg)),
            extra=dict(source_id_note="hash of board id + BLE name: two headsets with the same name share it"))
        eeg = lsl.StreamOutlet(_info(lsl, f"{PREFIX}-EEG", "EEG", self.names, "microvolts", "EEG", self.fs,
                                     "float32", s + "-eeg", dict(desc, extra=dict(desc["extra"], reference="Fpz (manufacturer documentation, not verified)"))))
        markers = lsl.StreamOutlet(_info(lsl, f"{PREFIX}-Markers", "Markers", ["label"], None, None, 0.0,
                                         "string", s + "-markers", desc))
        quality = lsl.StreamOutlet(_info(lsl, f"{PREFIX}-Quality", "Quality", ["event"], None, None, 0.0,
                                         "string", s + "-quality", dict(desc, extra=dict(desc["extra"], schema=QUALITY_SCHEMA))))
        self.bundle = Bundle(lsl, eeg, markers, quality)
        self.totals["eeg_outlets"] += 1
        self._emit("open", inherited=self.timeline.n > 0, **self._snapshot(), timeline=asdict(self.cfg), max_rebase_drop_samples=self.max_drop,
                   software=f"MuseMonitor {__version__}")
        self.bundle.next_status = float(self.mono()) + STATUS_EVERY_S

    def _snapshot(self):
        tl = self.timeline
        return dict(monitoring_since=self.monitoring_since, reason=self.reason,
                    timing_uncertain=bool(tl.timing_uncertain), next_input_index=tl.n,
                    drop_episode=self.episode is not None, eeg_open=self.bundle.eeg is not None)

    def _maybe_status(self):
        """Re-send the state when the Quality stream gets its first consumer, and every STATUS_EVERY_S."""
        b = self.bundle
        if b is None: return
        now = float(self.mono())
        if not b.had_consumers and b.quality.have_consumers():
            b.had_consumers = True; why = "consumer_connected"
        elif now >= b.next_status:
            why = "periodic"
        else:
            return
        self._emit("status", why=why, **self._snapshot())
        b.next_status = now + STATUS_EVERY_S

    def close(self, why):
        """Stop the outlets. Returns the closed Bundle: the caller keeps it alive for LINGER_S, otherwise the
        ``close`` record is lost (liblsl drops what was pushed right before an outlet is destroyed)."""
        b = self.bundle
        if b is None: return None
        self._emit("close", why=why, eeg=b.eeg_counters() if b.eeg is not None else None,
                   markers=b.markers_sent, connection=dict(self.totals), cost_ms=self.cost_summary())
        self.bundle = None
        return b

    def _close_eeg(self, code, detail):
        b = self.bundle
        self._emit("eeg_closed", code=code, detail=detail, eeg=b.eeg_counters())
        b.eeg = None
        self.totals["eeg_closed"] += 1
        self.messages.append(f"EEG outlet closed: {detail}")

    def _emit(self, event, **fields):
        b = self.bundle
        if b is None: return
        self.seq += 1
        rec = dict(v=1, event=event, seq=self.seq, segment=self.timeline.segment, **fields)
        ts = max(float(self.mono()), self.last_q + 1e-6)
        self.last_q = ts
        b.quality.push_sample([json.dumps(rec, separators=(",", ":"))], ts)

    # ---- data ---------------------------------------------------------------------------------------
    def push_eeg(self, x, ts_raw):
        t0 = time.perf_counter()
        tl = self.timeline
        offset, mono, stepped = self.bridge.measure()
        first = tl.n
        res = tl.push(np.asarray(ts_raw, dtype=float) + offset, mono, uncertain="clock_step" if stepped else None)
        t = res.t_out
        k = t.size
        if k == 0: return res
        self.totals["timeline_samples"] += k
        b = self.bundle
        eeg_on = b is not None and b.eeg is not None

        events = []
        if res.rebase is not None and t[0] <= self.watermark and self.episode is None:
            self.episode = dict(start=res.rebase.index, dropped=0)
            self.totals["drop_episodes"] += 1
        if res.rebase is not None:
            events.append(("rebase", dict(input_sample_index=res.rebase.index, shift_s=res.rebase.shift_s,
                                          rebase_reason=res.rebase.reason, timeline_ts=float(t[0]),
                                          dropping=self.episode is not None)))

        published_from = None                         # index in this chunk of the first published sample
        if eeg_on:
            b.received += k
            n_drop = int(np.searchsorted(t, self.watermark, side="right"))   # t is strictly increasing
            if n_drop:
                if self.episode is not None:
                    self.episode["dropped"] += n_drop; b.rebase_dropped += n_drop
                    self.totals["rebase_dropped"] += n_drop
                else:
                    b.guard_dropped += n_drop; self.totals["guard_dropped"] += n_drop
                    events.append(("guard_drop", dict(n=n_drop, input_sample_index=first)))
            if n_drop < k:
                published_from = n_drop
                pub_index = b.published
                b.eeg.push_chunk(np.ascontiguousarray(np.asarray(x, dtype=np.float32)[:, n_drop:].T),
                                 timestamp=[float(v) for v in t[n_drop:]])
                b.published += k - n_drop; self.totals["published"] += k - n_drop
                self.watermark = float(t[-1])
                if self.episode is not None:
                    events.append(("resume", dict(dropped=self.episode["dropped"], first_input_index=first + n_drop,
                                                  first_published_index=pub_index,
                                                  first_published_eeg_ts=float(t[n_drop]))))
                    self.episode = None
        else:
            self.totals["monitored_while_eeg_off"] += k
            if self.episode is not None and t[-1] > self.watermark:
                self.episode = None                   # caught up while nothing was published

        if res.reason != self.reason:
            eff = float(t[0]) if published_from == 0 else None
            events.insert(len([e for e in events if e[0] == "rebase"]),
                          ("state", dict(reason=res.reason, prev=self.reason, input_sample_index=first,
                                         timing_uncertain=bool(tl.timing_uncertain), effective_eeg_ts=eff)))
            self.reason = res.reason
        for ev, fields in events: self._emit(ev, **fields)

        if eeg_on and self.episode is not None and self.episode["dropped"] > self.max_drop:
            self._close_eeg("rebase_drop_limit",
                            f"a backward re-anchoring needed more than {self.max_drop} dropped samples "
                            f"({MAX_REBASE_DROP_S:g} s); stop and start again once timestamps have caught up, "
                            f"or reconnect the device")
        self._maybe_status()
        self.cost.append((time.perf_counter() - t0, eeg_on))
        return res

    def marker(self, t_unix, label):
        b = self.bundle
        if b is None: return None
        if not self.bridge.history: self.bridge.measure()
        offset, uncertain = self.bridge.marker_offset(t_unix)
        ts = float(t_unix) + offset
        b.markers.push_sample([str(label)], ts)
        b.markers_sent += 1; self.totals["markers"] += 1
        if uncertain:
            self.totals["markers_uncertain"] += 1
            self._emit("marker_uncertain", label=str(label), marker_ts=ts)
        return ts

    # ---- report -------------------------------------------------------------------------------------
    def cost_summary(self):
        out = {}
        for key, sel in (("eeg_outlet_open", True), ("eeg_outlet_off", False)):
            v = np.array([c for c, on in self.cost if on == sel]) * 1e3
            out[key] = None if v.size == 0 else dict(n=int(v.size), p50=round(float(np.percentile(v, 50)), 3),
                                                     p99=round(float(np.percentile(v, 99)), 3),
                                                     max=round(float(v.max()), 3))
        return out


class LslOutlet(Extension):
    name = "LSL Outlet"
    version = "0.1.0"
    description = "Streams live EEG, markers and a timing-quality stream to Lab Streaming Layer (LabRecorder)."
    requires_api = 3
    supports_review = False

    @classmethod
    def supports(cls, spec):
        from brainflow.board_shim import BoardIds
        return spec.board_id == BoardIds.MUSE_S_ATHENA_BOARD.value

    def activate(self, app):
        self.monitor = None
        self.wanted = False                   # the user pressed Start (applies at the next connection too)
        self.lsl_error = None
        self.device_name = None
        self._closing = []                    # closed bundles kept alive for LINGER_S
        self._mid_connection = app.is_streaming   # loaded while a device is already streaming (catch-up)
        self.toggle_action = app.add_action("Start LSL streams", self.toggle)
        app.add_action("LSL status…", self.show_report)

    def deactivate(self):
        b = self.monitor.close("app_closed") if self.monitor is not None else None
        self.monitor = None
        if b is not None and b.quality.have_consumers(): time.sleep(min(LINGER_S, 0.5))   # let `close` go out
        self._closing.clear()

    def _linger(self, bundle):
        if bundle is None: return
        from PySide6 import QtCore
        self._closing.append(bundle)
        QtCore.QTimer.singleShot(int(LINGER_S * 1000),
                                 lambda: self._closing.remove(bundle) if bundle in self._closing else None)

    # ---- device lifecycle --------------------------------------------------------------------------
    def on_connected(self, device_name):
        since = "extension_enabled_mid_connection" if self._mid_connection else "connect"
        self._mid_connection = False
        self.device_name = device_name
        lsl, self.lsl_error = load_pylsl()
        if lsl is None:
            self.monitor = None
            if self.wanted: self.app.show_status(f"LSL unavailable: {self.lsl_error}")
            return
        spec = self.app.spec
        self.monitor = Monitor(lsl, spec.eeg.fs, spec.eeg.names, source_base(spec.board_id, device_name), since)
        if self.wanted: self._start_outlets()

    def on_disconnected(self):
        if self.monitor is not None: self._linger(self.monitor.close("disconnected"))
        self.monitor = None
        self._update_action()

    def on_eeg_samples(self, x, ts_raw):
        m = self.monitor
        if m is None: return
        m.push_eeg(x, ts_raw)
        if m.messages:
            self.app.show_status(m.messages[-1], 15000); m.messages.clear()

    def on_event(self, t, label):
        if self.monitor is not None: self.monitor.marker(t, label)

    # ---- actions ------------------------------------------------------------------------------------------
    def toggle(self):
        if self.wanted:
            self.wanted = False
            if self.monitor is not None: self._linger(self.monitor.close("stopped"))
            self.app.show_status("LSL streams stopped")
        else:
            lsl, err = load_pylsl()
            if lsl is None:
                self.lsl_error = err
                self.app.show_status(f"LSL unavailable — pip install pylsl ({err})", 15000)
                return
            self.wanted = True
            if self.monitor is None and self.app.is_streaming and self.device_name is not None:
                self.on_connected(self.device_name)      # pylsl became available after connecting
            elif self.monitor is not None: self._start_outlets()
            else: self.app.show_status("LSL streams will start when the device connects")
        self._update_action()

    def _start_outlets(self):
        self.monitor.open()
        self.app.show_status(f"LSL streams started: {PREFIX}-EEG / -Markers / -Quality")

    def _update_action(self):
        self.toggle_action.setText("Stop LSL streams" if self.wanted else "Start LSL streams")

    def status_text(self):
        m = self.monitor
        lines = [f"Start requested: {'yes' if self.wanted else 'no'}"]
        if self.lsl_error: lines.append(f"LSL unavailable: {self.lsl_error}")
        if m is None:
            lines.append("No device connection monitored.")
            return "\n".join(lines)
        b = m.bundle
        lines.append("Outlets: " + ("stopped" if b is None else
                                    "running" if b.eeg is not None else "Markers + Quality running, EEG closed"))
        tl = m.timeline
        lines.append(f"Monitoring since: {m.monitoring_since}; flag: {m.reason or 'none'}; "
                     f"segment {tl.segment}; estimated fs {1.0 / tl.period:.3f} Hz")
        if b is not None and b.eeg is not None: lines.append(f"EEG outlet: {b.eeg_counters()}")
        lines.append(f"Connection: {m.totals}")
        lines.append(f"Hook cost (ms): {m.cost_summary()}")
        lines.append("Extension 'Active' in Manage extensions only means loaded; this shows whether outlets run.")
        return "\n".join(lines)

    def show_report(self):
        from PySide6 import QtWidgets
        QtWidgets.QMessageBox.information(self.app.main_window, "LSL Outlet", self.status_text())


EXTENSION = LslOutlet
