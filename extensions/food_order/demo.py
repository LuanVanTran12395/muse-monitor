"""Camera and demo video for the kiosk — reusing head_motion_plus's camera module read-only (via _reuse):
CameraController (chosen camera by id, macOS permission, YuNet face landmarks), facing_from_face and FacingGate
(recenter only when facing the screen AND the head is still for 1 s, at most every 5 s).

    CameraLink     starts / stops that controller; emits the facing result, and a smooth mirrored preview for the
                   kiosk's demo layout (the controller's own preview is 6 frames/s for detection only)
    DemoRecorder   writes the kiosk window (camera, head, eyes and UI together) to an MP4 file, frame by frame

Privacy (as in head_motion_plus): the camera is off by default; it starts only after the in-app consent and macOS
permission; frames are analysed in memory. The demo video is written only when the user presses Record, to the
app's data folder (git-ignored), and contains the camera image. No sound is recorded.
"""
import time

import numpy as np
from PySide6 import QtCore, QtGui

PREVIEW_HZ = 20
PREVIEW_W = 640


class CameraLink(QtCore.QObject):
    result = QtCore.Signal(object)         # head_motion_plus facing dict (+ "face")
    frame = QtCore.Signal(object)          # QImage, mirrored, ~PREVIEW_HZ
    error = QtCore.Signal(str)
    running_changed = QtCore.Signal(bool)

    def __init__(self, camera_module, parent=None):
        super().__init__(parent)
        self.m = camera_module
        self.ctrl = camera_module.CameraController(self)
        self.ctrl.result.connect(self.result)
        self.ctrl.error.connect(self.error)
        self.ctrl.running_changed.connect(self._running)
        self._next = 0.0
        self._sink = None

    @property
    def running(self):
        return self.ctrl.running

    @property
    def device_name(self):
        return self.ctrl.device_name

    def start(self, device_id=None):
        self.ctrl.start(device_id)

    def stop(self):
        self._detach()
        self.ctrl.stop()

    def _running(self, on):
        if on and self.ctrl.sink is not None and self._sink is None:
            self._sink = self.ctrl.sink
            self._sink.videoFrameChanged.connect(self._on_frame)         # every frame, for a smooth preview
        if not on: self._detach()
        self.running_changed.emit(on)

    def _detach(self):
        if self._sink is not None:
            try: self._sink.videoFrameChanged.disconnect(self._on_frame)
            except (RuntimeError, TypeError): pass
            self._sink = None

    def _on_frame(self, video_frame):
        now = time.monotonic()
        if now < self._next: return
        self._next = now + 1.0 / PREVIEW_HZ
        img = video_frame.toImage()
        if img.isNull(): return
        img = img.scaledToWidth(PREVIEW_W, QtCore.Qt.SmoothTransformation).mirrored(True, False)
        self.frame.emit(img.convertToFormat(QtGui.QImage.Format_RGB32))


def facing_caption(res, lang="vi"):
    """head_motion_plus's reason, in the kiosk's language."""
    from .text import t
    if res is None: return t("cam.starting", lang)
    if not res.get("face"): return t("cam.noface", lang)
    key = "cam." + str(res.get("reason", ""))
    text = t(key, lang)
    return res.get("reason", "") if text == key else text


class DemoRecorder(QtCore.QObject):
    """Grabs a widget at ``fps`` and writes an MP4 (OpenCV, mp4v). The frame size is fixed at start; later frames
    are scaled to it if the window is resized."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.writer = None
        self.widget = None
        self.path = None
        self.size = None
        self.started = None
        self.frames = 0
        self.timer = QtCore.QTimer(self); self.timer.timeout.connect(self._grab)

    @property
    def active(self):
        return self.writer is not None

    def seconds(self):
        return 0.0 if self.started is None else time.monotonic() - self.started

    def start(self, widget, path, fps=15):
        import cv2
        if self.active: return False
        img = widget.grab().toImage()
        w, h = img.width() // 2 * 2, img.height() // 2 * 2                 # even sizes for the codec
        self.writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), float(fps), (w, h))
        if not self.writer.isOpened():
            self.writer = None; return False
        self.widget, self.path, self.size, self.frames = widget, path, (w, h), 0
        self.started = time.monotonic()
        self.timer.start(int(1000 / fps))
        self._grab()
        return True

    def _grab(self):
        if self.writer is None or self.widget is None: return
        img = self.widget.grab().toImage()
        if (img.width(), img.height()) != self.size:
            img = img.scaled(self.size[0], self.size[1], QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
        img = img.convertToFormat(QtGui.QImage.Format_RGB888)
        w, h = img.width(), img.height()
        arr = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h, w, 3)
        self.writer.write(np.ascontiguousarray(arr[:, :, ::-1]))           # RGB → BGR
        self.frames += 1

    def stop(self):
        self.timer.stop()
        if self.writer is not None: self.writer.release()
        path, self.writer, self.widget, self.started = self.path, None, None, None
        return path
