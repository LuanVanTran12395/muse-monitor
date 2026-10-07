import threading
import time

import numpy as np
from brainflow.board_shim import BoardShim, BrainFlowInputParams
from PySide6 import QtCore

from .. import config as C
from ..storage.recording import Recorder


def _seq(d, stream):
    return d[stream.seq_row] if stream.seq_row is not None else None


class MuseWorker(QtCore.QObject):
    """Connects and reads the BrainFlow stream in its own thread; writes CSV when asked."""
    status = QtCore.Signal(str)
    # (data [channels, k], RAW per-sample timestamps [k], package_num [k] or None) — timestamps unmodified
    data_ready = QtCore.Signal(object, object, object)
    optics_ready = QtCore.Signal(object, object, object)
    imu_ready = QtCore.Signal(object, object, object)
    battery = QtCore.Signal(float)
    stream_started = QtCore.Signal()
    stream_stats = QtCore.Signal(float, int)
    stopped = QtCore.Signal()

    def __init__(self, serial, spec):
        super().__init__()
        self.serial = serial
        self.spec = spec
        self.board = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._rec_cmd = None      # ("start", path) | ("stop",)
        self.recorder = None

    # Called from the GUI thread — only set flags / commands; the worker acts on them
    def request_stop(self): self._stop.set()
    def start_recording(self, path):
        with self._lock: self._rec_cmd = ("start", path)
    def stop_recording(self):
        with self._lock: self._rec_cmd = ("stop",)

    def _handle_rec_cmd(self):
        with self._lock:
            cmd, self._rec_cmd = self._rec_cmd, None
        if cmd is None: return
        if self.recorder: self.recorder.close(); self.recorder = None
        if cmd[0] == "start":
            try: self.recorder = Recorder(cmd[1], self.spec)
            except OSError as e: self.status.emit(f"Cannot open file: {e}")

    @QtCore.Slot()
    def run(self):
        sp = self.spec
        first_packet = warned = False
        samples_since = total = 0
        stat_t0 = start_t = time.monotonic()
        try:
            self.status.emit(f"Connecting to {self.serial}…")
            params = BrainFlowInputParams()
            params.serial_number = self.serial
            params.other_info = C.OTHER_INFO
            self.board = BoardShim(sp.board_id, params)
            self.board.prepare_session()          # blocking; may take a few seconds
            if self._stop.is_set(): return        # user pressed Disconnect while scanning
            self.status.emit("BLE connected • waiting for EEG packets…")
            self.board.start_stream(C.STREAM_BUFFER)
            start_t = time.monotonic()

            while not self._stop.is_set():
                self._handle_rec_cmd()
                if self.board.get_board_data_count() > 0:
                    d = self.board.get_board_data()
                    if d.shape[1] > 0:
                        eeg, ts, seq = d[sp.eeg.rows], d[sp.eeg.ts_row], _seq(d, sp.eeg)
                        if not first_packet:
                            first_packet = True
                            self.stream_started.emit()
                            self.status.emit(f"Streaming EEG • {sp.eeg.fs} Hz")
                        samples_since += eeg.shape[1]; total += eeg.shape[1]
                        if self.recorder: self.recorder.write("eeg", ts, eeg, seq)
                        self.data_ready.emit(eeg, ts, seq)

                if sp.optics.n and self.board.get_board_data_count(sp.optics.preset) > 0:
                    od = self.board.get_board_data(preset=sp.optics.preset)
                    if od.shape[1] > 0:
                        optics, ts, seq = od[sp.optics.rows], od[sp.optics.ts_row], _seq(od, sp.optics)
                        if self.recorder: self.recorder.write("optics", ts, optics, seq)
                        self.optics_ready.emit(optics, ts, seq)
                        b = od[sp.battery_row]; b = b[np.isfinite(b) & (b > 0)]
                        if b.size: self.battery.emit(float(b[-1]))

                if sp.imu.n and self.board.get_board_data_count(sp.imu.preset) > 0:
                    ad = self.board.get_board_data(preset=sp.imu.preset)
                    if ad.shape[1] > 0:
                        imu, ts, seq = ad[sp.imu.rows], ad[sp.imu.ts_row], _seq(ad, sp.imu)
                        if self.recorder: self.recorder.write("imu", ts, imu, seq)
                        self.imu_ready.emit(imu, ts, seq)

                now = time.monotonic()
                if now - stat_t0 >= 1.0:
                    self.stream_stats.emit(samples_since / (now - stat_t0), total)
                    samples_since = 0; stat_t0 = now
                if not first_packet and not warned and now - start_t > C.NO_PACKET_WARN_SEC:
                    warned = True
                    self.status.emit("BLE connected • NO EEG packets (>5 s). Restart Muse / close Muse apps, then reconnect.")
                QtCore.QThread.msleep(C.POLL_MS)
        except Exception as e:
            self.status.emit(f"Connection/stream error: {type(e).__name__}: {e}")
        finally:
            if self.recorder: self.recorder.close(); self.recorder = None
            try:
                if self.board and self.board.is_prepared():
                    try: self.board.stop_stream()
                    except Exception: pass
                    self.board.release_session()
            except Exception:
                pass
            self.board = None
            self.stopped.emit()
