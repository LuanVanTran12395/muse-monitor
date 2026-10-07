"""Camera reference for "facing the screen" (3D Head Motion Plus).

Privacy: the camera is OFF by default and only starts after the user ticks the option, confirms
the in-app consent dialog and macOS grants camera access. Frames are processed in memory, a few
times per second, at low resolution; nothing is saved to disk or sent anywhere.

Capture uses Qt Multimedia with an explicitly chosen camera (by device id, so a nearby iPhone used as
Continuity Camera is not picked by accident). Detection uses OpenCV's YuNet face detector (models/face_detection_yunet_2023mar.onnx, MIT
licence) which returns 5 landmarks (eyes, nose tip, mouth corners). The face counts as "facing the
screen" when the nose sits centred between the eyes (yaw), at a normal height between eyes and mouth
(pitch) and the eye line is level (roll). Because the webcam sits at the screen, facing the camera ≈
looking straight at the screen.
"""
import math
import time
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui

MODEL = Path(__file__).with_name("models") / "face_detection_yunet_2023mar.onnx"
PROCESS_HZ = 6                 # frames analysed per second
DETECT_WIDTH = 320             # analysis resolution (px)

# thresholds for "facing the screen"
MAX_YAW_RATIO = 0.12           # |nose x − eye midpoint x| / eye distance
PITCH_RANGE = (0.40, 0.70)     # (nose y − eye y) / (mouth y − eye y) — coarse; IMU gravity keeps pitch anyway
MAX_ROLL_DEG = 12.0
MIN_SCORE = 0.80
MIN_FACE_FRAC = 0.12           # face width / frame width (too far → unreliable)


def availability():
    """(ok, reason) — whether camera facing detection can run in this environment."""
    try:
        import cv2
    except ImportError:
        return False, "OpenCV is not installed: ~/.venvs/musemonitor/bin/pip install opencv-python-headless"
    if not hasattr(cv2, "FaceDetectorYN"):
        return False, "This OpenCV build has no FaceDetectorYN (needs OpenCV ≥ 4.8)."
    if not MODEL.exists():
        return False, f"Face model missing: {MODEL.name}"
    return True, ""


def facing_from_face(row, frame_width):
    """YuNet row → dict(facing, yaw_ratio, pitch_ratio, roll_deg, reason). Pure function (testable).

    Row layout: x, y, w, h, right_eye(x,y), left_eye(x,y), nose(x,y), mouth_right(x,y), mouth_left(x,y), score.
    "right eye" is the person's right eye (left side of a non-mirrored image)."""
    x, y, w, h = row[:4]
    eye_r, eye_l, nose = np.array(row[4:6]), np.array(row[6:8]), np.array(row[8:10])
    mouth = (np.array(row[10:12]) + np.array(row[12:14])) / 2
    score = float(row[14])
    eye_mid = (eye_r + eye_l) / 2
    eye_dist = float(np.linalg.norm(eye_l - eye_r))
    out = dict(facing=False, yaw_ratio=float("nan"), pitch_ratio=float("nan"), roll_deg=float("nan"),
               score=score, reason="")
    if eye_dist < 1e-6 or mouth[1] - eye_mid[1] < 1e-6:
        out["reason"] = "landmarks unclear"; return out
    out["yaw_ratio"] = float((nose[0] - eye_mid[0]) / eye_dist)
    out["pitch_ratio"] = float((nose[1] - eye_mid[1]) / (mouth[1] - eye_mid[1]))
    out["roll_deg"] = math.degrees(math.atan2(eye_l[1] - eye_r[1], eye_l[0] - eye_r[0]))
    if score < MIN_SCORE: out["reason"] = "face unclear"
    elif w / frame_width < MIN_FACE_FRAC: out["reason"] = "too far from camera"
    elif abs(out["yaw_ratio"]) > MAX_YAW_RATIO: out["reason"] = "turned left/right"
    elif not PITCH_RANGE[0] <= out["pitch_ratio"] <= PITCH_RANGE[1]: out["reason"] = "looking up/down"
    elif abs(out["roll_deg"]) > MAX_ROLL_DEG: out["reason"] = "head tilted"
    else: out["facing"], out["reason"] = True, "facing the screen"
    return out


class FacingGate:
    """Decides when to recenter: facing the screen AND head still for ``hold_sec``, at most once per
    ``cooldown_sec``. Pure state machine (no camera, no Qt)."""

    def __init__(self, hold_sec=1.0, cooldown_sec=5.0):
        self.hold_sec, self.cooldown_sec = hold_sec, cooldown_sec
        self.since = None
        self.last_fire = -math.inf

    def reset(self):
        self.since = None

    def update(self, facing, still, t):
        if not (facing and still):
            self.since = None; return False
        if self.since is None: self.since = t
        if t - self.since >= self.hold_sec and t - self.last_fire >= self.cooldown_sec:
            self.last_fire, self.since = t, None
            return True
        return False


CONTINUITY_HINTS = ("iphone", "ipad", "continuity", "desk view")


def list_cameras():
    """[(id, name)] of connected cameras, as macOS / Qt Multimedia reports them."""
    from PySide6 import QtMultimedia
    return [(bytes(d.id()).decode(errors="replace"), d.description())
            for d in QtMultimedia.QMediaDevices.videoInputs()]


def preferred_camera(cameras, saved_id=None):
    """The user's saved choice if still connected; otherwise the first built-in / USB camera, NOT an
    iPhone/iPad Continuity Camera (macOS may put those first and make them the default)."""
    ids = [cid for cid, _ in cameras]
    if saved_id and saved_id in ids: return saved_id
    for cid, name in cameras:
        if not any(h in name.lower() for h in CONTINUITY_HINTS): return cid
    return ids[0] if ids else None


def analyse_frame(detector, bgr):
    """Run YuNet on a small BGR frame → (result dict, mirrored RGB preview with the face drawn)."""
    import cv2
    detector.setInputSize((bgr.shape[1], bgr.shape[0]))
    _, faces = detector.detect(bgr)
    res = dict(face=False, facing=False, reason="no face")
    if faces is not None and len(faces):
        best = max(faces, key=lambda f: f[2] * f[3])
        res = dict(face=True, **facing_from_face(best, bgr.shape[1]))
        color = (80, 200, 120) if res["facing"] else (60, 160, 255)
        x, y, fw, fh = best[:4].astype(int)
        cv2.rectangle(bgr, (x, y), (x + fw, y + fh), color, 2)
        for k in range(5):
            cv2.circle(bgr, (int(best[4 + 2*k]), int(best[5 + 2*k])), 2, color, -1)
    return res, cv2.cvtColor(cv2.flip(bgr, 1), cv2.COLOR_BGR2RGB)


def _qt_permission():
    perm_cls = getattr(QtCore, "QCameraPermission", None)
    app = QtCore.QCoreApplication.instance()
    if perm_cls is None or app is None: return "granted"           # platform without permissions
    st = app.checkPermission(perm_cls())
    return {QtCore.Qt.PermissionStatus.Granted: "granted",
            QtCore.Qt.PermissionStatus.Denied: "denied"}.get(st, "undetermined")


def _trigger_os_prompt():
    """Qt cannot show the macOS camera prompt for a non-bundled Python (no Info.plist), but
    AVFoundation via OpenCV can: open + release once; the answer is then visible to Qt."""
    import cv2
    cap = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)
    cap.release()


class CameraController(QtCore.QObject):
    """Captures the CHOSEN camera with Qt Multimedia (selected by device id, not index) and runs
    face detection a few times per second on the GUI thread. Frames never leave memory."""
    result = QtCore.Signal(object)         # dict from facing_from_face (+ "face": bool)
    preview = QtCore.Signal(object)        # small RGB numpy image with landmarks (mirrored)
    error = QtCore.Signal(str)
    running_changed = QtCore.Signal(bool)

    DENIED = ("Camera access is blocked by macOS. Allow it in System Settings › Privacy & Security › "
              "Camera for the app running Muse Monitor (Terminal / VS Code), then try again.")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.camera = self.session = self.sink = None
        self.detector = None
        self.device_name = ""
        self._next = 0.0
        self._wait = None

    @property
    def running(self):
        return self.camera is not None or self._wait is not None

    def start(self, device_id=None):
        if self.running: return
        status = _qt_permission()
        if status == "granted":
            self._open(device_id)
        elif status == "denied":
            self.error.emit(self.DENIED)
        else:                                       # ask macOS once, then wait for the answer
            import threading
            threading.Thread(target=_trigger_os_prompt, daemon=True).start()
            self._wait = QtCore.QTimer(self); self._wait.setInterval(500)
            deadline = time.monotonic() + 30
            self._wait.timeout.connect(lambda: self._poll_permission(device_id, deadline))
            self._wait.start()

    def _poll_permission(self, device_id, deadline):
        status = _qt_permission()
        if status == "undetermined" and time.monotonic() < deadline: return
        self._wait.stop(); self._wait.deleteLater(); self._wait = None
        if status == "granted": self._open(device_id)
        else: self.error.emit(self.DENIED)

    def _open(self, device_id):
        import cv2
        from PySide6 import QtMultimedia
        devices = QtMultimedia.QMediaDevices.videoInputs()
        dev = next((d for d in devices if bytes(d.id()).decode(errors="replace") == device_id), None)
        if dev is None:
            ids = [(bytes(d.id()).decode(errors="replace"), d.description()) for d in devices]
            pick = preferred_camera(ids)
            dev = next((d for d in devices if bytes(d.id()).decode(errors="replace") == pick), None)
        if dev is None:
            self.error.emit("No camera found."); return
        if self.detector is None:
            self.detector = cv2.FaceDetectorYN.create(str(MODEL), "", (DETECT_WIDTH, DETECT_WIDTH * 3 // 4), 0.7)
        self.device_name = dev.description()
        self.camera = QtMultimedia.QCamera(dev, self)
        self.session = QtMultimedia.QMediaCaptureSession(self)
        self.sink = QtMultimedia.QVideoSink(self)
        self.session.setCamera(self.camera); self.session.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._on_frame)
        self.camera.errorOccurred.connect(lambda _err, msg: self._fail(f"Camera error: {msg}"))
        self.camera.activeChanged.connect(self.running_changed)
        self._next = 0.0
        self.camera.start()

    def _on_frame(self, frame):
        now = time.monotonic()
        if now < self._next or self.camera is None: return
        self._next = now + 1.0 / PROCESS_HZ
        img = frame.toImage()
        if img.isNull(): return
        img = img.scaledToWidth(DETECT_WIDTH, QtCore.Qt.SmoothTransformation).convertToFormat(QtGui.QImage.Format_RGB888)
        w, h = img.width(), img.height()
        rgb = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h, w, 3)
        try:
            res, prev = analyse_frame(self.detector, rgb[:, :, ::-1].copy())
        except Exception as e:                                          # never crash the app
            self._fail(f"Camera error: {type(e).__name__}: {e}"); return
        self.result.emit(res)
        self.preview.emit(prev)

    def _fail(self, message):
        self.stop()
        self.error.emit(message)

    def stop(self):
        if self._wait is not None:
            self._wait.stop(); self._wait.deleteLater(); self._wait = None
        if self.camera is None: return
        cam, self.camera = self.camera, None
        try: self.sink.videoFrameChanged.disconnect(self._on_frame)
        except (RuntimeError, TypeError): pass
        cam.stop()
        for obj in (cam, self.session, self.sink): obj.deleteLater()
        self.session = self.sink = None
        self.running_changed.emit(False)


def rgb_to_qimage(rgb):
    h, w = rgb.shape[:2]
    return QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format_RGB888).copy()
