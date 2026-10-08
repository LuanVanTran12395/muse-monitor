"""Calibrated 3D head pose driven by Muse S Athena's six IMU channels."""

import math
import time
from collections import deque

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from musemonitor.plugins.api import BaseTab, Extension

from . import camera


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


DEFAULT_AXES = np.array(((0., 1., 0.), (0., 0., 1.), (1., 0., 0.)))


def axes_from_motions(left_gyro, up_gyro):
    """Fit a right-handed sensor-to-head rotation from two deliberate motions.

    A left turn is positive model yaw (+Y); looking up is negative model pitch (-X).
    Roll follows from the cross product instead of an independent sign guess.
    """
    yaw = _normal(left_gyro)
    pitch = _normal(up_gyro)
    if np.linalg.norm(yaw) < 0.9 or np.linalg.norm(pitch) < 0.9:
        raise ValueError("Movement was too small to identify the IMU axis.")
    if abs(float(np.dot(yaw, pitch))) > 0.55:
        raise ValueError("Left turn and looking up used nearly the same IMU axis. Repeat both steps.")
    x_axis = _normal(-pitch + np.dot(pitch, yaw) * yaw)
    z_axis = np.cross(x_axis, yaw)
    return np.vstack((x_axis, yaw, z_axis))


class PoseTracker:
    """Gyro integration with a weak gravity correction; yaw remains relative."""

    def __init__(self, fs):
        self.fs = float(fs)
        self.axes = DEFAULT_AXES.copy()
        self.reset()

    def reset(self):
        self.q = np.array((1.0, 0.0, 0.0, 0.0))
        self.gravity = None
        self.last_ts = None
        self.samples = 0
        self.gyro_bias = np.zeros(3)
        self.recent = deque(maxlen=max(10, int(self.fs)))

    def recenter(self):
        if not self.is_still():
            return False
        recent = np.asarray(self.recent, dtype=float)
        self.gravity = _normal(np.mean(recent[:, :3], axis=0))
        self.gyro_bias = np.mean(recent[:, 3:], axis=0)
        self.q = np.array((1.0, 0.0, 0.0, 0.0))
        self.last_ts = None
        return True

    def is_still(self):
        recent = np.asarray(self.recent, dtype=float)
        if len(recent) < max(10, int(self.fs * 0.6)):
            return False
        acc, gyro = recent[:, :3], recent[:, 3:]
        return (np.all((np.linalg.norm(acc, axis=1) > 0.85) &
                       (np.linalg.norm(acc, axis=1) < 1.15)) and
                np.max(np.linalg.norm(gyro - self.gyro_bias, axis=1)) < 3.0 and
                np.max(np.linalg.norm(acc - np.mean(acc, axis=0), axis=1)) < 0.08)

    def set_calibration(self, axes, sensor_bias):
        self.axes = np.asarray(axes, dtype=float).copy()
        self.reset()
        self.gyro_bias = self.axes @ np.asarray(sensor_bias, dtype=float)

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
            acc = self.axes @ x[:3, i]
            gyro = self.axes @ x[3:6, i]
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


def _rotation_matrix(q):
    w, x, y, z = q
    return np.array(((1 - 2*(y*y + z*z), 2*(x*y - w*z), 2*(x*z + w*y)),
                     (2*(x*y + w*z), 1 - 2*(x*x + z*z), 2*(y*z - w*x)),
                     (2*(x*z - w*y), 2*(y*z + w*x), 1 - 2*(x*x + y*y))))


def pose_angles(q):
    """(yaw, pitch, roll) in degrees: yaw + = turned left, pitch + = looking up (model convention)."""
    r = _rotation_matrix(q)
    f, right = r[:, 2], r[:, 0]
    yaw = math.degrees(math.atan2(f[0], f[2]))
    pitch = math.degrees(math.atan2(f[1], math.hypot(f[0], f[2])))
    roll = math.degrees(math.asin(max(-1.0, min(1.0, -right[1]))))
    return yaw, pitch, roll


HEAD_R = np.array((0.78, 1.05, 0.85))          # head ellipsoid radii (x right, y up, z forward)
SKIN, HAIR = (214, 162, 125), (58, 40, 30)
LIPS = (150, 82, 66)


def _on_head(u, v, outward=1.0):
    """Point on the head ellipsoid from a normalized (u, v) front-facing coordinate."""
    w = math.sqrt(max(0.0, 1.0 - u*u - v*v))
    return np.array((u, v, w)) * HEAD_R * outward


def _surface_normal(p):
    return _normal(np.asarray(p) / HEAD_R**2)


class _Mesh:
    """Faces stored as padded vertex-index rows so one numpy pass shades and sorts everything."""

    MAX = 24

    def __init__(self):
        self.verts, self.faces, self.counts = [], [], []
        self.normals, self.colors, self.cull, self.bias, self.spec, self.flat = [], [], [], [], [], []

    def add(self, points, color, normal, cull=True, bias=0.0, spec=0.12, flat=False):
        base = len(self.verts)
        self.verts.extend(np.asarray(p, dtype=float) for p in points)
        idx = list(range(base, base + len(points)))
        self.faces.append(idx + [idx[-1]] * (self.MAX - len(idx)))
        self.counts.append(len(idx))
        self.normals.append(_normal(normal)); self.colors.append(color)
        self.cull.append(cull); self.bias.append(bias); self.spec.append(spec); self.flat.append(flat)

    def freeze(self):
        self.verts = np.array(self.verts); self.faces = np.array(self.faces)
        self.counts = np.array(self.counts); self.normals = np.array(self.normals)
        self.colors = np.array(self.colors, dtype=float); self.cull = np.array(self.cull)
        self.bias = np.array(self.bias); self.spec = np.array(self.spec); self.flat = np.array(self.flat)
        self.mask = np.arange(self.MAX)[None, :] < self.counts[:, None]
        return self


def _ellipsoid(mesh, center, radii, lat_n, lon_n, color_of, spec=0.12):
    center, radii = np.asarray(center, float), np.asarray(radii, float)
    for i in range(lat_n):
        a0, a1 = -math.pi/2 + math.pi*i/lat_n, -math.pi/2 + math.pi*(i+1)/lat_n
        for j in range(lon_n):
            b0, b1 = 2*math.pi*j/lon_n, 2*math.pi*(j+1)/lon_n
            unit = [np.array((math.cos(a)*math.sin(b), math.sin(a), math.cos(a)*math.cos(b)))
                    for a, b in ((a0, b0), (a0, b1), (a1, b1), (a1, b0))]
            mid = np.mean(unit, axis=0)
            mesh.add([center + radii*p for p in unit], color_of(_normal(mid)), mid / radii, spec=spec)


def _decal(mesh, u, v, shape, color, outward=1.012, bias=0.02):
    """Flat feature (eye, brow, mouth) laid on the head surface around normalized (u, v)."""
    center = _on_head(u, v)
    n = _surface_normal(center)
    t1 = _normal(np.cross((0, 1, 0), n)); t2 = np.cross(n, t1)
    pts = [center * outward + t1*dx + t2*dy for dx, dy in shape]
    mesh.add(pts, color, n, bias=bias, spec=0.0, flat=True)


def _arc(x0, x1, y_of, thickness, n=8):
    top = [(x0 + (x1 - x0)*k/n, y_of(x0 + (x1 - x0)*k/n) + thickness/2) for k in range(n + 1)]
    bottom = [(x, y - thickness) for x, y in reversed(top)]
    return top + bottom


def build_head_mesh():
    m = _Mesh()

    def head_color(p):
        u, v, w = p
        line = 0.46 + 0.30*w if w > -0.30 else min(0.46 + 0.30*w, -0.48)    # hairline: high at the forehead, low at the nape
        t = min(1.0, max(0.0, (v - line) / 0.18 + 0.5))                     # soft colour transition over ~0.18
        return tuple(a + (b - a)*t for a, b in zip(SKIN, HAIR))
    _ellipsoid(m, (0, 0, 0), HEAD_R, 22, 36, head_color)
    for side in (-1, 1):                                                       # ears
        _ellipsoid(m, (side*0.78, -0.02, -0.03), (0.07, 0.19, 0.12), 8, 12,
                   lambda p: tuple(c*0.86 for c in SKIN))
    # neck: short open cylinder under the skull
    seg = 24
    for j in range(seg):
        b0, b1 = 2*math.pi*j/seg, 2*math.pi*(j+1)/seg
        for y0, y1 in ((-0.70, -1.05), (-1.05, -1.45)):
            ring = [(math.sin(b)*0.36, y, -0.08 + math.cos(b)*0.33) for b, y in ((b0, y0), (b1, y0), (b1, y1), (b0, y1))]
            mid = (b0 + b1) / 2
            m.add(ring, tuple(c*0.84 for c in SKIN), (math.sin(mid), 0, math.cos(mid)))
    # nose: small pyramid so it is foreshortened and hidden correctly
    top, tip = np.array((0, 0.10, 0.845)), np.array((0, -0.15, 0.975))
    left, right, base = np.array((-0.10, -0.20, 0.815)), np.array((0.10, -0.20, 0.815)), np.array((0, -0.23, 0.86))
    inside = np.array((0, -0.10, 0.80))
    for tri in ((top, left, tip), (top, tip, right), (left, base, tip), (base, right, tip)):
        n = np.cross(tri[1] - tri[0], tri[2] - tri[0])
        if np.dot(n, np.mean(tri, axis=0) - inside) < 0: n = -n            # outward-facing normal
        m.add(tri, tuple(c*0.92 for c in SKIN), n, spec=0.05)
    # face features
    eye = [(0.068*math.cos(k*math.pi/7), 0.046*math.sin(k*math.pi/7)) for k in range(14)]
    for side in (-1, 1):
        _decal(m, side*0.34, 0.12, eye, (43, 29, 22))
        _decal(m, side*0.34, 0.27, _arc(-0.10, 0.10, lambda x: -1.6*x*x, 0.026), HAIR)            # brow
    _decal(m, 0.0, -0.47, _arc(-0.16, 0.16, lambda x: 0.9*x*x, 0.03, n=10), LIPS)               # mouth
    return m.freeze()


class HeadCanvas(QtWidgets.QWidget):
    """Software-rendered shaded 3D head (painter's algorithm), so the extension needs no OpenGL."""

    LIGHT = _normal((-0.35, 0.55, 0.9))
    HALF = _normal(_normal((-0.35, 0.55, 0.9)) + np.array((0, 0, 1.0)))
    CAMERA = 4.5

    def __init__(self, tracker):
        super().__init__()
        self.tracker = tracker
        self.theme = None
        self.mesh = build_head_mesh()
        self.setMinimumSize(360, 330)

    def set_theme(self, theme):
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        th = self.theme or {"base": "#0d1117", "fg": "#e6edf3", "muted": "#8b949e"}
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        base = QtGui.QColor(th["base"])
        dark = base.lightness() < 128
        center = QtCore.QPointF(self.width()/2, self.height()/2 - 18)
        scale = min(self.width()/3.6, self.height()/4.3)
        bg = QtGui.QRadialGradient(center, max(self.width(), self.height()) * 0.7)
        bg.setColorAt(0, base.lighter(165) if dark else base.darker(104))
        bg.setColorAt(1, base)
        painter.fillRect(self.rect(), bg)
        floor = QtCore.QPointF(center.x(), center.y() + scale*1.62)                 # soft shadow under the neck
        shadow = QtGui.QRadialGradient(floor, scale*0.9)
        shadow.setColorAt(0, QtGui.QColor(0, 0, 0, 90 if dark else 45)); shadow.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
        painter.setPen(QtCore.Qt.NoPen); painter.setBrush(shadow)
        painter.drawEllipse(floor, scale*0.95, scale*0.2)

        m = self.mesh
        rot = _rotation_matrix(self.tracker.q)
        world = m.verts @ rot.T
        persp = self.CAMERA / (self.CAMERA - world[:, 2])
        sx = center.x() + world[:, 0]*scale*persp
        sy = center.y() - world[:, 1]*scale*persp
        normals = m.normals @ rot.T
        facing = normals[:, 2]
        visible = ~m.cull | (facing > -0.02)
        visible &= ~m.flat | (facing > 0.22)                                       # features only on the near side
        zf = np.where(m.mask, world[m.faces, 2], 0.0)
        depth = zf.sum(axis=1) / m.counts + m.bias
        lambert = np.clip(normals @ self.LIGHT, 0, 1)
        spec = np.clip(normals @ self.HALF, 0, 1) ** 28 * m.spec
        shade = np.where(m.flat, 0.85 + 0.15*lambert, 0.42 + 0.62*lambert)
        rgb = np.clip(m.colors * shade[:, None] + 255*spec[:, None], 0, 255).astype(int)
        order = np.argsort(depth)
        for i in order[visible[order]]:
            idx = m.faces[i, :m.counts[i]]
            poly = QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in zip(sx[idx], sy[idx])])
            color = QtGui.QColor(*rgb[i])
            painter.setPen(QtGui.QPen(color, 0.9))                                  # closes hairline seams
            painter.setBrush(color)
            painter.drawPolygon(poly)

        yaw, pitch, roll = (round(a) + 0 for a in pose_angles(self.tracker.q))     # + 0: never show "-0"
        painter.setPen(QtGui.QColor(th["fg"]))
        painter.drawText(QtCore.QRectF(0, self.height()-44, self.width(), 20), QtCore.Qt.AlignCenter,
                         f"yaw {yaw:+d}°   pitch {pitch:+d}°   roll {roll:+d}°")
        painter.setPen(QtGui.QColor(th["muted"]))
        painter.drawText(QtCore.QRectF(0, self.height()-24, self.width(), 18), QtCore.Qt.AlignCenter,
                         "relative pose · yaw may drift")
        painter.end()


class HeadMotionPlusTab(BaseTab):
    title = "3D head +"

    def __init__(self, ctx, ext):
        super().__init__(ctx)
        self.ext = ext
        layout = QtWidgets.QVBoxLayout(self)
        controls = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("Waiting for Athena IMU…")
        self.recenter_button = QtWidgets.QPushButton("Recenter head")
        self.recenter_button.clicked.connect(self.recenter)
        controls.addWidget(self.status)
        controls.addStretch()
        controls.addWidget(self.recenter_button)
        layout.addLayout(controls)
        self.canvas = HeadCanvas(ext.tracker)
        layout.addWidget(self.canvas, 1)
        calibration = QtWidgets.QHBoxLayout()
        self.neutral_button = QtWidgets.QPushButton("1 · Hold still")
        self.left_button = QtWidgets.QPushButton("2 · Turn left")
        self.up_button = QtWidgets.QPushButton("3 · Look up")
        for button, kind in ((self.neutral_button, "neutral"),
                             (self.left_button, "left"), (self.up_button, "up")):
            button.clicked.connect(lambda _=False, k=kind: self.begin_capture(k))
            calibration.addWidget(button)
        calibration.addStretch()
        layout.addLayout(calibration)
        self.calibration_info = ctx.plots.muted_label(
            "Optional calibration: hold still, turn left once, then look up once. "
            "Return to center between steps. Click a step, wait for GO, move once and hold.")
        layout.addWidget(self.calibration_info)
        self.note = ctx.plots.muted_label(
            "Relative orientation only. Keep still before Recenter. Yaw has no compass reference.")
        layout.addWidget(self.note)
        self._build_camera_row(layout)
        self.capture_kind = None
        self.capture_rows = []
        self.neutral_bias = None
        self.left_vector = None
        self.capture_generation = 0

    # ---- camera reference: "facing the screen" (optional, off by default) --------------------
    def _build_camera_row(self, layout):
        box = QtWidgets.QGroupBox("Camera reference (optional)")
        row = QtWidgets.QHBoxLayout(box)
        col = QtWidgets.QVBoxLayout()
        self.cam_check = QtWidgets.QCheckBox("Use the computer camera to detect when I face the screen")
        self.cam_check.setToolTip("Off by default. Asks for your permission every time it is turned on. "
                                  "Frames are analysed in memory only — never saved or sent.")
        self.cam_auto = QtWidgets.QCheckBox("Auto-recenter when I face the screen and hold still (corrects yaw drift)")
        self.cam_auto.setChecked(True); self.cam_auto.setEnabled(False)
        self.cam_status = QtWidgets.QLabel("Camera off.")
        pick = QtWidgets.QHBoxLayout()
        self.cam_select = QtWidgets.QComboBox()
        self.cam_select.setToolTip("Which camera to use. The Mac's built-in camera is preferred over an "
                                   "iPhone/iPad Continuity Camera; your choice is remembered.")
        pick.addWidget(QtWidgets.QLabel("Camera:")); pick.addWidget(self.cam_select, 1)
        col.addWidget(self.cam_check); col.addLayout(pick); col.addWidget(self.cam_auto); col.addWidget(self.cam_status)
        row.addLayout(col, 1)
        self.cam_live = QtWidgets.QLabel("● Camera on"); self.cam_live.setStyleSheet("color:#f85149;font-weight:600")
        self.cam_preview = QtWidgets.QLabel(); self.cam_preview.setFixedSize(160, 120)
        self.cam_preview.setAlignment(QtCore.Qt.AlignCenter)
        pv = QtWidgets.QVBoxLayout(); pv.addWidget(self.cam_live); pv.addWidget(self.cam_preview)
        row.addLayout(pv)
        self.cam_live.hide(); self.cam_preview.hide()
        box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        layout.addWidget(box)
        ok, why = camera.availability()
        if not ok:
            self.cam_check.setEnabled(False); self.cam_status.setText(why)
        self.cam = camera.CameraController(self)
        self.cam.result.connect(self._camera_result)
        self.cam.preview.connect(self._camera_preview)
        self.cam.error.connect(self._camera_error)
        self.cam.running_changed.connect(self._camera_running)
        self.cam_gate = camera.FacingGate()
        self.cam_last = None
        self.cam_check.toggled.connect(self._camera_toggled)
        self.refresh_cameras()
        self.cam_select.currentIndexChanged.connect(self._camera_selected)
        if ok:
            from PySide6 import QtMultimedia
            self._media = QtMultimedia.QMediaDevices(self)                # iPhone comes / goes
            self._media.videoInputsChanged.connect(self.refresh_cameras)

    def _saved_camera(self):
        app = getattr(self.ext, "app", None)
        return app.setting("camera_id", "") if app is not None else ""

    def refresh_cameras(self):
        """Fill the camera list; keep the current choice if still connected, else the preferred one."""
        try:
            cams = camera.list_cameras()
        except Exception:
            cams = []
        current = self.cam_select.currentData() or self._saved_camera()
        choice = camera.preferred_camera(cams, current)
        self.cam_select.blockSignals(True)
        self.cam_select.clear()
        for cid, name in cams:
            self.cam_select.addItem(name, cid)
        if choice is not None: self.cam_select.setCurrentIndex(self.cam_select.findData(choice))
        self.cam_select.setEnabled(bool(cams))
        self.cam_select.blockSignals(False)
        if not cams and self.cam_check.isEnabled(): self.cam_status.setText("No camera found.")

    def _camera_selected(self, _index):
        cid = self.cam_select.currentData()
        app = getattr(self.ext, "app", None)
        if cid and app is not None: app.set_setting("camera_id", cid)
        if self.cam.running:                                                # switch camera live
            self.cam.stop(); self.cam.start(cid)

    def _set_cam_check(self, on):
        self.cam_check.blockSignals(True); self.cam_check.setChecked(on); self.cam_check.blockSignals(False)

    def _camera_toggled(self, on):
        if not on:
            self.stop_camera("Camera off."); return
        if not self._ask_camera_consent():
            self._set_cam_check(False); self.cam_status.setText("Camera not enabled — permission not given."); return
        if self._os_camera_permission() == "denied":
            self._set_cam_check(False)
            self.cam_status.setText("Camera access is blocked by macOS. Allow it in System Settings › Privacy & "
                                    "Security › Camera for the app running Muse Monitor, then try again.")
            return
        self.cam_gate.reset(); self.cam_last = None
        self.cam.start(self.cam_select.currentData())
        self.cam_status.setText("Starting camera… macOS may ask for permission.")

    def _ask_camera_consent(self):
        """In-app consent, asked every time the camera is turned on."""
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setWindowTitle("Use camera?")
        box.setText("Allow Muse Monitor to use the computer camera?")
        box.setInformativeText(
            "The camera is used only to detect when you look straight at the screen, so the 3D head can "
            "use that as its forward direction.\n\nFrames are analysed in memory a few times per second "
            "and are never saved or sent anywhere. A preview and a red “● Camera on” mark are shown while "
            "it runs. You can turn it off at any time.")
        allow = box.addButton("Allow camera", QtWidgets.QMessageBox.AcceptRole)
        box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is allow

    @staticmethod
    def _os_camera_permission():
        """'granted' | 'denied' | 'undetermined' | 'unknown' (macOS permission, checked without prompting)."""
        perm_cls = getattr(QtCore, "QCameraPermission", None)
        app = QtWidgets.QApplication.instance()
        if perm_cls is None or app is None: return "unknown"
        try:
            st = app.checkPermission(perm_cls())
        except Exception:
            return "unknown"
        return {QtCore.Qt.PermissionStatus.Granted: "granted", QtCore.Qt.PermissionStatus.Denied: "denied"}.get(
            st, "undetermined")

    def stop_camera(self, message=None):
        self.cam.stop()
        self._set_cam_check(False)
        self.cam_preview.clear(); self.cam_preview.hide(); self.cam_live.hide()
        self.cam_auto.setEnabled(False)
        self.cam_last = None
        if message: self.cam_status.setText(message)

    def _camera_running(self, running):
        self.cam_live.setVisible(running); self.cam_preview.setVisible(running)
        self.cam_auto.setEnabled(running)
        if running: self.cam_status.setText(f"Camera on ({self.cam.device_name}) — look straight at the screen.")

    def _camera_error(self, message):
        self.stop_camera(message)

    def _camera_preview(self, rgb):
        img = camera.rgb_to_qimage(rgb)
        self.cam_preview.setPixmap(QtGui.QPixmap.fromImage(img).scaled(
            self.cam_preview.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def _camera_result(self, res):
        self.cam_last = res
        still = self.ext.tracker.is_still()
        if self.cam_gate.update(res.get("facing", False), still, time.monotonic()) and self.cam_auto.isChecked():
            if self.ext.tracker.recenter():
                self.calibration_info.setText("Auto-recentered: you are facing the screen.")
                self.canvas.update()

    def _camera_text(self):
        res = self.cam_last
        if res is None: return "Camera on — waiting for the first frame…"
        if not res.get("face"): return "Camera: no face in view."
        mark = "✓" if res["facing"] else "·"
        return f"Camera {mark} {res['reason']}"

    def begin_capture(self, kind):
        if not self.ext.tracker.samples:
            self.calibration_info.setText("Connect Athena and wait for IMU samples first.")
            return
        if kind != "neutral" and self.neutral_bias is None:
            self.calibration_info.setText("Complete step 1 while holding still first.")
            return
        if kind == "up" and self.left_vector is None:
            self.calibration_info.setText("Complete step 2, the left turn, first.")
            return
        self.capture_generation += 1
        generation = self.capture_generation
        self.capture_kind = None
        self.capture_rows = []
        instruction = {"neutral": "keep still", "left": "turn your head LEFT once",
                       "up": "look UP once"}[kind]
        self.calibration_info.setText(f"Get ready: {instruction}. GO in 1 second…")
        QtCore.QTimer.singleShot(1000, lambda: self._start_capture(kind, generation))

    def _start_capture(self, kind, generation):
        if generation != self.capture_generation:
            return
        self.capture_kind = kind
        self.calibration_info.setText(f"GO: {kind} · capture in progress…")

    def collect(self, block):
        if self.capture_kind is None:
            return
        x = np.asarray(block, dtype=float)
        if x.ndim != 2 or x.shape[0] < 6:
            return
        self.capture_rows.extend(x[:6].T)
        needed = int(self.ext.tracker.fs * (1.5 if self.capture_kind != "neutral" else 1.0))
        if len(self.capture_rows) >= needed:
            kind = self.capture_kind
            self.capture_kind = None
            self._finish_capture(kind, np.asarray(self.capture_rows[:needed]))
            self.capture_rows = []

    def _finish_capture(self, kind, rows):
        acc, gyro = rows[:, :3], rows[:, 3:]
        if not np.all(np.isfinite(rows)):
            self.calibration_info.setText("IMU contained invalid samples. Repeat this step.")
            return
        if kind == "neutral":
            gyro_bias = np.mean(gyro, axis=0)
            if (np.max(np.linalg.norm(gyro - gyro_bias, axis=1)) > 3.0 or
                    np.max(np.linalg.norm(acc - np.mean(acc, axis=0), axis=1)) > 0.08 or
                    not 0.85 < np.linalg.norm(np.mean(acc, axis=0)) < 1.15):
                self.calibration_info.setText("Head moved during step 1. Hold still and repeat.")
                return
            self.neutral_bias = gyro_bias
            self.left_vector = None
            self.calibration_info.setText("Step 1 done. Face forward, then click step 2 and turn LEFT on GO.")
            return
        motion = np.sum(gyro - self.neutral_bias, axis=0) / self.ext.tracker.fs
        if np.linalg.norm(motion) < 12.0:
            self.calibration_info.setText("Movement was too small or you returned during capture. Repeat this step.")
            return
        if kind == "left":
            self.left_vector = motion
            self.calibration_info.setText("Step 2 done. Face forward, then click step 3 and look UP on GO.")
            return
        try:
            axes = axes_from_motions(self.left_vector, motion)
        except ValueError as exc:
            self.calibration_info.setText(str(exc))
            return
        self.ext.tracker.set_calibration(axes, self.neutral_bias)
        self.calibration_info.setText(
            "Calibration complete. Face forward, hold still for one second, then press Recenter head.")

    def recenter(self):
        if self.ext.tracker.recenter():
            self.calibration_info.setText("Recentered. Current head pose is forward.")
            self.canvas.update()
        else:
            self.calibration_info.setText("Hold your head still for about one second, then try Recenter again.")

    def on_frame(self):
        self.canvas.update()

    def update_texts(self):
        n = self.ext.tracker.samples
        if not n:
            state = "waiting"
        elif time.monotonic() - self.ext.last_imu_at > 1.0:
            state = "no recent IMU"
        elif self.ext.tracker.is_still():
            state = "stable"
        else:
            state = "moving"
        self.status.setText(f"IMU: {n:,} samples · {self.ext.tracker.fs:g} Hz · {state}")
        if self.cam.running: self.cam_status.setText(self._camera_text())

    def apply_theme(self, th):
        self.canvas.set_theme(th)

    def clear(self):
        self.capture_generation += 1
        self.capture_kind = None
        self.capture_rows = []
        self.neutral_bias = None
        self.left_vector = None
        self.ext.tracker.axes = DEFAULT_AXES.copy()
        self.ext.tracker.reset()
        self.status.setText("Waiting for Athena IMU…")
        self.calibration_info.setText(
            "Optional calibration: hold still, turn left once, then look up once. "
            "Return to center between steps. Click a step, wait for GO, move once and hold.")
        self.canvas.update()


class HeadMotionPlus(Extension):
    id = "head_motion_plus"
    name = "3D Head Motion Plus"
    category = "Motion"          # panels go to HCI/BCI ▸ Motion
    version = "1.0.0"
    description = ("3D head pose with guided Athena IMU calibration and signal status. Optional: use the "
                   "computer camera (off by default, asks permission) to detect facing the screen.")

    @classmethod
    def supports(cls, spec):
        return spec.imu.n >= 6                    # needs accelerometer + gyroscope

    def activate(self, app):
        self.tracker = PoseTracker(app.spec.imu.fs)
        self.last_imu_at = 0.0
        self.tab = app.add_tab(HeadMotionPlusTab(app.view, self))

    def on_imu(self, x, ts):
        self.last_imu_at = time.monotonic()
        self.tracker.add(x, ts)
        self.tab.collect(x)

    def on_disconnected(self):
        self.tab.clear()

    def deactivate(self):
        self.tab.stop_camera("Camera off.")   # never leave the camera running after unload / app close


EXTENSION = HeadMotionPlus
