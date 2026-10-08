"""Live 3D head pose driven by Muse S Athena's six IMU channels."""

import math
from collections import deque

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from musemonitor.plugins.api import BaseTab, Extension


def _normal(v):
    length = float(np.linalg.norm(v))
    return np.asarray(v, dtype=float) / length if length > 1e-12 else np.zeros(3)


def _multiply(a, b):
    w, x, y, z = a
    v, i, j, k = b
    return np.array((w*v-x*i-y*j-z*k, w*i+x*v+y*k-z*j,
                     w*j-x*k+y*v+z*i, w*k+x*j-y*i+z*v), dtype=float)


def _rotate(q, point):
    vector = np.asarray(point, dtype=float)
    qv = q[1:]
    t = 2.0 * np.cross(qv, vector)
    return vector + q[0] * t + np.cross(qv, t)


def _step(q, gyro_dps, dt):
    radians = np.deg2rad(gyro_dps) * dt
    angle = float(np.linalg.norm(radians))
    if angle < 1e-12:
        return q
    half = angle / 2.0
    delta = np.r_[math.cos(half), _normal(radians) * math.sin(half)]
    return _multiply(q, delta) / np.linalg.norm(q)


def _athena_to_head(vector):
    """Athena sensor axes -> model axes (right, up, forward).

    The headset rests with gravity on sensor -Z. On the model, gravity is -Y.
    User motion checks identify sensor Z as yaw and sensor Y as pitch.
    This cyclic permutation keeps the coordinate system right-handed.
    """
    return np.asarray(vector, dtype=float)[[1, 2, 0]]


class PoseTracker:
    """Gyro integration with a weak gravity correction; yaw remains relative."""

    def __init__(self, fs):
        self.fs = float(fs)
        self.reset()

    def reset(self):
        self.q = np.array((1.0, 0.0, 0.0, 0.0))
        self.gravity = None
        self.last_ts = None
        self.samples = 0
        self.gyro_bias = np.zeros(3)
        self.recent = deque(maxlen=max(10, int(self.fs)))

    def recenter(self):
        recent = np.asarray(self.recent, dtype=float)
        if len(recent):
            self.gravity = _normal(np.mean(recent[:, :3], axis=0))
            # Estimate offset only while still; do not learn deliberate slow turns as bias.
            if len(recent) >= self.fs / 2 and np.max(np.linalg.norm(recent[:, 3:], axis=1)) < 2.0:
                self.gyro_bias = np.mean(recent[:, 3:], axis=0)
        self.q = np.array((1.0, 0.0, 0.0, 0.0))
        self.last_ts = None

    def add(self, block, ts):
        x = np.asarray(block, dtype=float)
        if x.ndim != 2 or x.shape[0] < 6 or x.shape[1] == 0:
            return
        n = x.shape[1]
        dt = 1.0 / self.fs
        if self.last_ts is not None and np.isfinite(ts):
            elapsed = float(ts) - self.last_ts
            if 0 < elapsed < 0.25:
                dt = min(0.04, elapsed / n)
        if np.isfinite(ts):
            self.last_ts = float(ts)
        for i in range(n):
            acc = _athena_to_head(x[:3, i])
            gyro = _athena_to_head(x[3:6, i])
            if not (np.all(np.isfinite(acc)) and np.all(np.isfinite(gyro))):
                continue
            self.recent.append(np.r_[acc, gyro])
            strength = float(np.linalg.norm(acc))
            if self.gravity is None and 0.7 < strength < 1.3:
                self.gravity = _normal(acc)
            self.q = _step(self.q, gyro - self.gyro_bias, dt)
            # Dynamic acceleration is not a reliable tilt reference.
            if self.gravity is not None and 0.85 < strength < 1.15:
                measured = _rotate(self.q, acc / strength)
                error = np.cross(measured, self.gravity)
                magnitude = float(np.linalg.norm(error))
                if magnitude > 1e-10:
                    correction = np.r_[math.cos(0.012*magnitude/2),
                                       _normal(error) * math.sin(0.012*magnitude/2)]
                    self.q = _multiply(correction, self.q)
                    self.q /= np.linalg.norm(self.q)
            self.samples += 1


class HeadCanvas(QtWidgets.QWidget):
    """Software-rendered 3D head, so the extension needs no OpenGL package."""

    def __init__(self, tracker):
        super().__init__()
        self.tracker = tracker
        self.theme = None
        self.setMinimumSize(360, 330)

    def set_theme(self, theme):
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        th = self.theme or {"base": "#0d1117", "fg": "#e6edf3", "muted": "#8b949e",
                            "border": "#30363d", "highlight": "#1f6feb"}
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor(th["base"]))
        center = QtCore.QPointF(self.width()/2, self.height()/2 + 6)
        scale = min(self.width()/3.4, self.height()/3.1)
        q = self.tracker.q

        def project(point):
            x, y, z = _rotate(q, point)
            perspective = 4.5 / (4.5 - z)
            return QtCore.QPointF(center.x() + x*scale*perspective,
                                  center.y() - y*scale*perspective), z

        skin = QtGui.QColor("#d6a27d")
        light = _normal((0.4, 0.8, 1.0))
        polygons = []
        lat_count, lon_count = 10, 18
        for lat in range(lat_count):
            a0 = -math.pi/2 + math.pi*lat/lat_count
            a1 = -math.pi/2 + math.pi*(lat+1)/lat_count
            for lon in range(lon_count):
                b0 = 2*math.pi*lon/lon_count
                b1 = 2*math.pi*(lon+1)/lon_count
                def vertex(a, b):
                    return np.array((0.78*math.cos(a)*math.sin(b),
                                     1.05*math.sin(a), 0.85*math.cos(a)*math.cos(b)))
                pts = [vertex(a0,b0), vertex(a0,b1), vertex(a1,b1), vertex(a1,b0)]
                average = np.mean(pts, axis=0)
                normal = _normal((average[0]/0.78**2, average[1]/1.05**2,
                                  average[2]/0.85**2))
                illumination = max(0.0, float(np.dot(_rotate(q, normal), light)))
                shade = skin.darker(int(150 - 43*illumination))
                projected = [project(p) for p in pts]
                polygons.append((float(np.mean([depth for _, depth in projected])),
                                 QtGui.QPolygonF([screen for screen, _ in projected]), shade))
        polygons.sort(key=lambda item: item[0])
        painter.setPen(QtCore.Qt.NoPen)
        for _, polygon, color in polygons:
            painter.setBrush(color)
            painter.drawPolygon(polygon)

        # Ears and a raised nose give an unambiguous sense of front/back rotation.
        for side in (-1, 1):
            ear, _ = project((side*0.83, -0.04, 0.02))
            painter.setBrush(QtGui.QColor("#a97457"))
            painter.drawEllipse(ear, scale*0.13, scale*0.22)
        if _rotate(q, (0, 0, 1))[2] > 0.05:
            eye_pen = QtGui.QPen(QtGui.QColor("#3b2d2a"), max(2.0, scale*0.035))
            eye_pen.setCapStyle(QtCore.Qt.RoundCap)
            painter.setPen(eye_pen)
            for side in (-1, 1):
                eye, _ = project((side*0.31, 0.24, 0.76))
                painter.drawPoint(eye)
            nose = QtGui.QPolygonF([project((0, 0.22, 0.84))[0],
                                    project((-0.11, -0.22, 0.91))[0],
                                    project((0, -0.17, 1.04))[0],
                                    project((0.11, -0.22, 0.91))[0]])
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor("#b57c5a"))
            painter.drawPolygon(nose)
            painter.setPen(eye_pen)
            a, _ = project((-0.18, -0.51, 0.70))
            b, _ = project((0.18, -0.51, 0.70))
            painter.drawLine(a, b)

        painter.setPen(QtGui.QColor(th["muted"]))
        painter.drawText(QtCore.QRectF(0, self.height()-32, self.width(), 24),
                         QtCore.Qt.AlignCenter, "Relative pose · yaw may drift")
        painter.end()


class HeadMotionTab(BaseTab):
    title = "3D head"

    def __init__(self, ctx, ext):
        super().__init__(ctx)
        self.ext = ext
        layout = QtWidgets.QVBoxLayout(self)
        controls = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("Waiting for Athena IMU…")
        self.recenter_button = QtWidgets.QPushButton("Recenter head")
        self.recenter_button.clicked.connect(self.ext.tracker.recenter)
        controls.addWidget(self.status)
        controls.addStretch()
        controls.addWidget(self.recenter_button)
        layout.addLayout(controls)
        self.canvas = HeadCanvas(ext.tracker)
        layout.addWidget(self.canvas, 1)
        self.note = ctx.plots.muted_label(
            "Move the headset while wearing it. Keep still, then press Recenter head. "
            "Gyro tracks turns; gravity stabilizes tilt. Yaw has no compass reference.")
        layout.addWidget(self.note)

    def on_frame(self):
        self.canvas.update()

    def update_texts(self):
        n = self.ext.tracker.samples
        self.status.setText(f"IMU: {n:,} samples · {self.ext.tracker.fs:g} Hz" if n else
                            "Waiting for Athena IMU…")

    def apply_theme(self, th):
        self.canvas.set_theme(th)

    def clear(self):
        self.ext.tracker.reset()
        self.status.setText("Waiting for Athena IMU…")
        self.canvas.update()


class HeadMotion(Extension):
    id = "head_motion"
    name = "3D Head Motion"
    category = "Motion"          # panels go to HCI/BCI ▸ Motion
    version = "1.0.0"
    description = "Live 3D head pose estimated from Muse S Athena accelerometer and gyroscope."

    @classmethod
    def supports(cls, spec):
        return spec.imu.n >= 6                    # needs accelerometer + gyroscope

    def activate(self, app):
        self.tracker = PoseTracker(app.spec.imu.fs)
        app.add_tab(HeadMotionTab(app.view, self))

    def on_imu(self, x, ts):
        self.tracker.add(x, ts)

    def on_disconnected(self):
        self.tracker.reset()


EXTENSION = HeadMotion
