"""`musemonitor --self-check`: does this installation work, without a headset? (debate/claude-packaging-proposal.md)

Each check exercises a feature, not just an import — in a packaged app the native pieces (BrainFlow, liblsl, Qt
Multimedia plugins, OpenCV and the YuNet model) are only loaded when a feature is used, so an import-only check could
pass on a broken build. Everything is written to a temporary folder; nothing goes to the user's data folder.

Prints one line per check (OK / FAIL / SKIP) and returns 0 when every REQUIRED check passed. In a packaged app every
check is required; from source, a library that is simply not installed (OpenCV, pylsl) is a SKIP.
"""
import importlib.util
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

REQUIRED_EXTENSIONS = ("artifact_log", "band_power", "eye_interaction", "food_order", "head_motion",
                       "head_motion_plus", "hello_world", "lsl_outlet", "muse_cube", "p300_bci")


class Skip(Exception):
    """A feature whose library is not installed (from source only)."""


def _ext_module(folder, name):
    init = folder / "__init__.py"
    spec = importlib.util.spec_from_file_location(name, init, submodule_search_locations=[str(folder)])
    mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod; spec.loader.exec_module(mod)
    return mod


def check_data(ctx):
    from .storage.session import data_root
    root = data_root()
    expected = os.environ.get("MUSEMONITOR_DATA_DIR")
    if ctx["frozen"] and not expected and root != Path.home() / "MuseMonitor" / "data":
        raise AssertionError(f"data folder {root} (expected ~/MuseMonitor/data)")
    probe = Path(ctx["tmp"]) / "write_probe.txt"                 # write rights are tried in the temp folder only
    probe.write_text("ok"); probe.unlink()
    return f"data → {root}"


def check_extensions(ctx):
    from PySide6 import QtCore
    from .device.spec import athena_spec
    from .ui import main_window as mw
    mw.MainWindow.start_scan = lambda self: None                   # no Bluetooth scan
    settings = QtCore.QSettings(str(Path(ctx["tmp"]) / "settings.ini"), QtCore.QSettings.IniFormat)
    old = os.environ.get("MUSEMONITOR_DATA_DIR")
    os.environ["MUSEMONITOR_DATA_DIR"] = str(Path(ctx["tmp"]) / "data")   # extensions write nothing to the user's data
    w = mw.MainWindow(athena_spec(), settings=settings)
    try:
        status = {r.id: r.status for r in w.extensions.records}
        bad = {k: v for k, v in status.items() if v not in ("active", "not applicable")}
        missing = [e for e in REQUIRED_EXTENSIONS if e not in status]
        if bad or missing: raise AssertionError(f"not active: {bad}; missing: {missing}")
        return f"{len(status)} extensions active ({', '.join(sorted(status))})"
    finally:
        w.close()
        if old is None: os.environ.pop("MUSEMONITOR_DATA_DIR", None)
        else: os.environ["MUSEMONITOR_DATA_DIR"] = old


def check_brainflow(ctx):
    from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams
    board = BoardShim(BoardIds.SYNTHETIC_BOARD.value, BrainFlowInputParams())
    board.prepare_session()
    try:
        board.start_stream(); time.sleep(0.6)
        data = board.get_board_data()
        board.stop_stream()
    finally:
        board.release_session()
    if data.shape[1] < 10: raise AssertionError(f"only {data.shape[1]} samples")
    return f"synthetic board: {data.shape[1]} samples"


def check_ble(ctx):
    import bleak  # noqa: F401
    backend = {"darwin": "bleak.backends.corebluetooth", "win32": "bleak.backends.winrt"}.get(sys.platform,
                                                                                            "bleak.backends.bluezdbus")
    importlib.import_module(backend)
    return f"bleak + {backend.rsplit('.', 1)[1]}"


def check_multimedia(ctx):
    from PySide6 import QtMultimedia
    cams = QtMultimedia.QMediaDevices.videoInputs()                # loads the multimedia plugin; no camera needed
    return f"Qt Multimedia: {len(cams)} camera(s) listed"


def _cv2(ctx):
    try:
        import cv2
    except ImportError:
        if ctx["frozen"]: raise
        raise Skip("OpenCV not installed")
    return cv2


def check_yunet(ctx):
    import math
    import numpy as np
    from PySide6 import QtGui
    cv2 = _cv2(ctx)
    from .plugins.loader import bundled_dirs
    folder = bundled_dirs()[0] / "head_motion_plus"
    hmp = _ext_module(folder, "musemonitor_selfcheck_head")
    model = folder / "models" / "face_detection_yunet_2023mar.onnx"
    det = cv2.FaceDetectorYN.create(str(model), "", (320, 240), 0.5)
    tracker = hmp.PoseTracker(52); canvas = hmp.HeadCanvas(tracker); canvas.resize(640, 480)
    tracker.q = np.array((math.cos(0.0), 0, math.sin(0.0), 0))
    img = canvas.grab().toImage().convertToFormat(QtGui.QImage.Format_RGB888)
    w, h = img.width(), img.height()
    rgb = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h, w, 3)
    small = cv2.resize(rgb[:, :, ::-1].copy(), (320, int(h * 320 / w)))
    det.setInputSize((small.shape[1], small.shape[0]))
    _, faces = det.detect(small)
    if faces is None or not len(faces): raise AssertionError("no face found on the rendered head")
    return f"OpenCV {cv2.__version__} + YuNet: face found on the rendered head"


def check_video(ctx):
    import numpy as np
    cv2 = _cv2(ctx)
    path = str(Path(ctx["tmp"]) / "probe.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 15.0, (160, 120))
    if not writer.isOpened(): raise AssertionError("mp4 writer did not open")
    for i in range(10): writer.write(np.full((120, 160, 3), i * 20, np.uint8))
    writer.release()
    cap = cv2.VideoCapture(path); n = 0
    while cap.read()[0]: n += 1
    cap.release()
    if n < 10: raise AssertionError(f"read back {n} of 10 frames")
    return "mp4 written and read back (10 frames)"


def check_lsl(ctx):
    try:
        import pylsl
    except ImportError:
        if ctx["frozen"]: raise
        raise Skip("pylsl not installed")
    name = f"musemonitor-selfcheck-{os.getpid()}"
    outlet = pylsl.StreamOutlet(pylsl.StreamInfo(name, "Check", 1, 0, "float32", name))
    found = pylsl.resolve_byprop("name", name, timeout=5.0)
    if not found: raise AssertionError("outlet not found by the resolver")
    inlet = pylsl.StreamInlet(found[0]); inlet.open_stream(timeout=5.0)
    time.sleep(0.2)
    for _ in range(20):
        outlet.push_sample([42.0]); sample, _ = inlet.pull_sample(timeout=0.5)
        if sample: break
    if not sample or sample[0] != 42.0: raise AssertionError(f"received {sample}")
    return f"LSL loopback (liblsl {pylsl.library_version()})"


CHECKS = [("data", check_data), ("extensions", check_extensions), ("brainflow", check_brainflow),
          ("ble", check_ble), ("multimedia", check_multimedia), ("opencv+yunet", check_yunet),
          ("video", check_video), ("lsl", check_lsl)]


def run(out=print):
    """Run every check; returns the exit code (0: every required check passed)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets
    from .plugins.loader import frozen
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["musemonitor-self-check"])  # noqa: F841
    failed = 0
    with tempfile.TemporaryDirectory(prefix="musemonitor-selfcheck-") as tmp:
        ctx = dict(tmp=tmp, frozen=frozen())
        out(f"Muse Monitor self-check ({'packaged app' if ctx['frozen'] else 'from source'}, {sys.platform})")
        for name, fn in CHECKS:
            try:
                out(f"  OK    {name:<13} {fn(ctx)}")
            except Skip as e:
                out(f"  SKIP  {name:<13} {e}")
            except Exception as e:
                failed += 1
                out(f"  FAIL  {name:<13} {type(e).__name__}: {e}")
                if os.environ.get("MUSEMONITOR_SELFCHECK_TRACE"): out(traceback.format_exc())
    out("PASSED" if not failed else f"FAILED: {failed} check(s)")
    return 0 if not failed else 1
