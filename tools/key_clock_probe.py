"""B2 probe: which clock do real key-press timestamps use, and how late does the app handle a key?

Run on the real machine with the real keyboard (synthetic QTest keys carry timestamp 0, so CI cannot answer this):

    ~/.venvs/musemonitor/bin/python tools/key_clock_probe.py            # idle
    ~/.venvs/musemonitor/bin/python tools/key_clock_probe.py --busy 40  # GUI thread busy 40 ms every 50 ms

Press keys (about 30), then close the window. For each press it prints
    QKeyEvent.timestamp() (ms) · time.monotonic() when handled · delay = handled − pressed
and at the end the delay statistics. Reading the result (debate/claude-b2-event-clock-research.md §3):
- delays between 0 and a few tens of ms  → the key clock shares time.monotonic()'s base (expected on macOS:
  NSEvent.timestamp = time awake since boot = mach_absolute_time = time.monotonic());
- negative, or seconds / hours                → different base on this platform: the app must not use it.
"""
import argparse
import statistics
import sys
import time

from PySide6 import QtCore, QtWidgets


def key_delay(key_ms, mono_now):
    """Seconds between the key press (QKeyEvent.timestamp(), ms) and now (time.monotonic())."""
    return mono_now - key_ms / 1000.0


class Probe(QtWidgets.QLabel):
    def __init__(self, busy_ms):
        super().__init__("Press keys here (about 30), then close the window.")
        self.setMinimumSize(520, 120); self.setAlignment(QtCore.Qt.AlignCenter)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.delays = []
        if busy_ms:                                  # simulate a GUI thread busy redrawing plots
            t = QtCore.QTimer(self); t.timeout.connect(lambda: time.sleep(busy_ms / 1000)); t.start(50)

    def keyPressEvent(self, ev):
        mono = time.monotonic()
        if ev.isAutoRepeat(): return
        d = key_delay(ev.timestamp(), mono)
        self.delays.append(d)
        print(f"key {ev.text()!r:6} timestamp {ev.timestamp():>12} ms   monotonic {mono:14.4f} s   delay {d * 1000:9.1f} ms")
        self.setText(f"{len(self.delays)} keys · last delay {d * 1000:.1f} ms")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--busy", type=float, default=0, help="keep the GUI thread busy this many ms every 50 ms")
    a = ap.parse_args(argv)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    print(f"Qt {QtCore.qVersion()} · platform {app.platformName()} · monotonic: "
          f"{time.get_clock_info('monotonic').implementation}")
    w = Probe(a.busy); w.setWindowTitle("Key clock probe"); w.show(); w.activateWindow(); w.setFocus()
    app.exec()
    d = [x * 1000 for x in w.delays]
    if not d: print("no keys pressed"); return 1
    print(f"\n{len(d)} keys · delay ms: min {min(d):.1f} · median {statistics.median(d):.1f} · max {max(d):.1f}")
    same_base = all(-1.0 <= x <= 2000.0 for x in d)          # 1 ms slack: timestamp() is truncated to whole ms
    print("verdict:", "key timestamps share time.monotonic()'s base — usable" if same_base
          else "key timestamps are NOT on time.monotonic()'s base here — do not use them")
    return 0 if same_base else 2


if __name__ == "__main__":
    sys.exit(main())
