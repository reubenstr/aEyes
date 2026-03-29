from __future__ import annotations
import math
import sys
from collections import defaultdict
from pathlib import Path
import numpy as np

"""
    Visualizer used by demo.py
"""

ROOT = Path(__file__).resolve().parent
CONTROLLER_DIR = ROOT / "controller"
if str(CONTROLLER_DIR) not in sys.path:
    sys.path.insert(0, str(CONTROLLER_DIR))

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    import pyqtgraph as pg
    import pyqtgraph.opengl as gl
except ImportError as exc:  # pragma: no cover - exercised at runtime, not import time
    raise SystemExit(
        "main.py requires PySide6 and pyqtgraph.\n"
        "Install the GUI dependencies first, for example:\n"
        "  python3 -m pip install PySide6 pyqtgraph PyOpenGL"
    ) from exc

from config import CAMERA_CONFIG, EYE_CONFIGS
from data_types import CameraConfig, Color, EyeConfig
from eye_manager import EyeManager
from face_tracker import FaceTracker
from plot import get_detections

try:
    from pyqtgraph.opengl.items.GLTextItem import GLTextItem
except Exception:  # pragma: no cover - depends on pyqtgraph version
    GLTextItem = None


TRAIL_LEN = 300
TRAIL_SEGMENTS = 6
FRAME_INTERVAL_MS = 150
NUM_FRAMES = 500
EYE_RING_POINTS = 60
STATIC_RING_RADIUS = 0.025
DYNAMIC_RING_RADIUS = 0.05

X_LIMITS = (-0.5, 3.1)
Y_LIMITS = (-2.1, 2.1)
Z_LIMITS = (-1.1, 1.1)


def color_to_rgbf(color: Color) -> tuple[float, float, float, float]:
    return (
        color.red / 255.0,
        color.green / 255.0,
        color.blue / 255.0,
        1.0,
    )


def make_line_points(start: tuple[float, float, float], end: tuple[float, float, float]) -> np.ndarray:
    return np.array([start, end], dtype=float)


def build_camera_frustum(camera_config: CameraConfig, depth: float = 3.0) -> list[np.ndarray]:
    cx, cy, cz = camera_config.x, camera_config.y, camera_config.z
    half_h = math.radians(camera_config.horizontal_fov / 2.0)
    half_v = math.radians(camera_config.vertical_fov / 2.0)
    fy = depth * math.tan(half_h)
    fz = depth * math.tan(half_v)
    corners = [
        (cx + depth, cy + fy, cz + fz),
        (cx + depth, cy - fy, cz + fz),
        (cx + depth, cy - fy, cz - fz),
        (cx + depth, cy + fy, cz - fz),
    ]

    segments: list[np.ndarray] = []
    for corner in corners:
        segments.append(make_line_points((cx, cy, cz), corner))
    for i in range(4):
        segments.append(make_line_points(corners[i], corners[(i + 1) % 4]))
    return segments


def build_static_eye_rings(eye_configs: list[EyeConfig], radius: float = STATIC_RING_RADIUS) -> dict[int, np.ndarray]:
    theta = np.linspace(0.0, 2.0 * math.pi, EYE_RING_POINTS)
    y_ring = radius * np.cos(theta)
    z_ring = radius * np.sin(theta)

    rings: dict[int, np.ndarray] = {}
    for cfg in eye_configs:
        rings[cfg.eye_id] = np.column_stack(
            (
                np.full_like(theta, cfg.position.x, dtype=float),
                cfg.position.y + y_ring,
                cfg.position.z + z_ring,
            )
        )
    return rings


def build_bounds_box() -> list[np.ndarray]:
    x0, x1 = X_LIMITS
    y0, y1 = Y_LIMITS
    z0, z1 = Z_LIMITS
    corners = [
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    ]
    edge_indices = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    return [make_line_points(corners[a], corners[b]) for a, b in edge_indices]


def build_disc_mesh(
    center: tuple[float, float, float],
    u_axis: tuple[float, float, float],
    v_axis: tuple[float, float, float],
    radius: float,
    segments: int = EYE_RING_POINTS,
) -> gl.MeshData:
    cx, cy, cz = center
    ux, uy, uz = u_axis
    vx, vy, vz = v_axis

    theta = np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)
    rim = np.column_stack(
        (
            cx + radius * (np.cos(theta) * ux + np.sin(theta) * vx),
            cy + radius * (np.cos(theta) * uy + np.sin(theta) * vy),
            cz + radius * (np.cos(theta) * uz + np.sin(theta) * vz),
        )
    )
    vertexes = np.vstack((np.array([[cx, cy, cz]], dtype=float), rim))
    faces = np.array(
        [[0, i + 1, ((i + 1) % segments) + 1] for i in range(segments)],
        dtype=np.uint32,
    )
    return gl.MeshData(vertexes=vertexes, faces=faces)


class EyeStatusWidget(QtWidgets.QFrame):
    def __init__(self, eye_id: int, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.eye_id = eye_id
        self.setMinimumSize(120, 120)
        self._face_id: int | None = None
        self._yaw_text = "Y:--"
        self._pitch_text = "P:--"
        self._eye_lid = 1.0
        self._iris_color = Color(128, 128, 128)

    def update_state(self, state) -> None:
        self._face_id = state.face_id
        self._eye_lid = state.eye_lid
        self._iris_color = state.iris_color
        if state.face_id is None:
            self._yaw_text = "Y:--"
            self._pitch_text = "P:--"
        else:
            self._yaw_text = f"Y:{state.yaw:+.1f}°"
            self._pitch_text = f"P:{state.pitch:+.1f}°"
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor(24, 24, 28))

        center_x = self.width() / 2.0
        eye_center_y = 42.0
        radius = 26.0
        height = max(6.0, radius * 2.0 * self._eye_lid)
        ellipse_rect = QtCore.QRectF(
            center_x - radius,
            eye_center_y - height / 2.0,
            radius * 2.0,
            height,
        )

        painter.setPen(QtGui.QPen(QtGui.QColor("black"), 1.5))
        painter.setBrush(
            QtGui.QColor(
                self._iris_color.red,
                self._iris_color.green,
                self._iris_color.blue,
            )
        )
        painter.drawEllipse(ellipse_rect)

        brightness = (
            0.299 * self._iris_color.red
            + 0.587 * self._iris_color.green
            + 0.114 * self._iris_color.blue
        ) / 255.0
        eye_text_color = QtGui.QColor("black" if brightness > 0.55 else "white")
        painter.setPen(eye_text_color)
        bold_font = painter.font()
        bold_font.setBold(True)
        bold_font.setPointSize(9)
        painter.setFont(bold_font)
        painter.drawText(
            QtCore.QRectF(center_x - 38.0, eye_center_y - 11.0, 76.0, 22.0),
            QtCore.Qt.AlignCenter,
            f"Eye ID: {self.eye_id}",
        )

        normal_font = painter.font()
        normal_font.setBold(False)
        normal_font.setPointSize(8)
        painter.setFont(normal_font)
        painter.setPen(QtGui.QColor(220, 220, 225))
        face_label = f"Face ID:{self._face_id}" if self._face_id is not None else "x"
        painter.drawText(
            QtCore.QRectF(0.0, 70.0, self.width(), 16.0),
            QtCore.Qt.AlignHCenter,
            face_label,
        )

        painter.setPen(QtGui.QColor(220, 220, 225) if self._face_id is not None else QtGui.QColor(120, 120, 128))
        painter.drawText(
            QtCore.QRectF(0.0, 88.0, self.width(), 14.0),
            QtCore.Qt.AlignHCenter,
            self._yaw_text,
        )
        painter.drawText(
            QtCore.QRectF(0.0, 102.0, self.width(), 14.0),
            QtCore.Qt.AlignHCenter,
            self._pitch_text,
        )


class EyeStatusStrip(QtWidgets.QWidget):
    def __init__(self, eye_configs: list[EyeConfig], parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)
        self._widgets: dict[int, EyeStatusWidget] = {}
        for cfg in eye_configs:
            widget = EyeStatusWidget(cfg.eye_id, self)
            layout.addWidget(widget, 1)
            self._widgets[cfg.eye_id] = widget

    def update_states(self, eye_states: dict[int, object]) -> None:
        for eye_id, widget in self._widgets.items():
            if eye_id in eye_states:
                widget.update_state(eye_states[eye_id])


class PlotWindow(QtWidgets.QMainWindow):
    def __init__(self, num_frames: int = NUM_FRAMES, interval_ms: int = FRAME_INTERVAL_MS,
                 driven_externally: bool = False) -> None:
        super().__init__()
        self.num_frames = num_frames
        self.interval_ms = interval_ms
        self.frame = 0
        self.paused = False

        self.tracker = FaceTracker()
        self.eye_manager = EyeManager(eye_configs=EYE_CONFIGS, camera_config=CAMERA_CONFIG)
        self.eye_configs = EYE_CONFIGS
        self.eye_cfg_by_id = {cfg.eye_id: cfg for cfg in self.eye_configs}
        self.track_history: dict[int, dict[str, list[float]]] = defaultdict(
            lambda: {"x": [], "y": [], "z": []}
        )
        self.theta_ring = np.linspace(0.0, 2.0 * math.pi, EYE_RING_POINTS)

        self.face_label_items: dict[int, object] = {}
        self.eye_label_items: dict[int, object] = {}
        self.face_mesh_items: dict[int, gl.GLMeshItem] = {}

        self.setWindowTitle("aEyes - Face Tracking + Eye Assignment")
        self.resize(1280, 900)
        self._build_ui()
        self._build_static_scene()
        self._init_dynamic_items()
        self._install_shortcuts()

        if not driven_externally:
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self.advance_frame)
            self.timer.start(self.interval_ms)
            self.advance_frame()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background-color: #18181c;
                color: #e6e6ea;
            }
            QLabel {
                color: #e6e6ea;
            }
            """
        )

        central = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.view = gl.GLViewWidget(self)
        self.view.setBackgroundColor((38, 38, 46))
        self.view.opts["center"] = pg.Vector(1.3, 0.0, 0.0)
        self.view.setCameraPosition(distance=6.0, elevation=18.0, azimuth=-35.0)
        layout.addWidget(self.view, 1)

        self.paused_label = QtWidgets.QLabel("PAUSED - zoom/rotate freely, press Space to resume", self.view)
        self.paused_label.setStyleSheet(
            "background: rgba(24, 24, 28, 220); color: #ff6b6b; padding: 6px 10px; border: 1px solid #444; border-radius: 4px;"
        )
        self.paused_label.adjustSize()
        self.paused_label.hide()

        self.frame_counter_label = QtWidgets.QLabel(self.view)
        self.frame_counter_label.setStyleSheet(
            "background: rgba(24, 24, 28, 220); color: #e6e6ea; padding: 6px 10px; border: 1px solid #444; border-radius: 4px;"
        )
        self.frame_counter_label.setAlignment(QtCore.Qt.AlignCenter)
        self.frame_counter_label.setText("Frame 0")
        self.frame_counter_label.adjustSize()

        self.eye_strip = EyeStatusStrip(self.eye_configs, self)
        layout.addWidget(self.eye_strip)

        self.setCentralWidget(central)
        self._position_overlays()

    def _install_shortcuts(self) -> None:
        self.toggle_pause_shortcut = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Space), self)
        self.toggle_pause_shortcut.setContext(QtCore.Qt.WindowShortcut)
        self.toggle_pause_shortcut.activated.connect(self.toggle_pause)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_overlays()

    def _position_overlays(self) -> None:
        margin = 14
        paused_x = max(margin, (self.view.width() - self.paused_label.width()) // 2)
        self.paused_label.move(paused_x, margin)
        frame_x = max(margin, self.view.width() - self.frame_counter_label.width() - margin)
        frame_y = max(margin, self.view.height() - self.frame_counter_label.height() - margin)
        self.frame_counter_label.move(frame_x, frame_y)

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        timer = getattr(self, "timer", None)
        if self.paused:
            if timer:
                timer.stop()
            self.paused_label.show()
        else:
            self.paused_label.hide()
            if timer:
                timer.start(self.interval_ms)

    def _build_static_scene(self) -> None:
        grid = gl.GLGridItem()
        grid.setSize(x=X_LIMITS[1] - X_LIMITS[0], y=Y_LIMITS[1] - Y_LIMITS[0])
        grid.setSpacing(x=0.5, y=0.5)
        grid.translate((X_LIMITS[0] + X_LIMITS[1]) / 2.0, 0.0, Z_LIMITS[0])
        grid.setColor((140, 140, 150, 130))
        self.view.addItem(grid)

        for segment in build_bounds_box():
            item = gl.GLLinePlotItem(
                pos=segment,
                color=(0.45, 0.45, 0.48, 0.35),
                width=1.0,
                antialias=True,
                mode="line_strip",
            )
            self.view.addItem(item)

        for segment in build_camera_frustum(CAMERA_CONFIG):
            item = gl.GLLinePlotItem(
                pos=segment,
                color=(1.0, 0.85, 0.0, 0.6),
                width=1.0,
                antialias=True,
                mode="line_strip",
            )
            self.view.addItem(item)

        for ring in build_static_eye_rings(self.eye_configs).values():
            item = gl.GLLinePlotItem(
                pos=ring,
                color=(0.82, 0.82, 0.86, 1.0),
                width=1.0,
                antialias=True,
                mode="line_strip",
            )
            self.view.addItem(item)

    def _init_dynamic_items(self) -> None:
        self.gimbal_arm_items: dict[int, object] = {}
        self.eye_ring_items: dict[int, object] = {}
        self.eye_disc_items: dict[int, gl.GLMeshItem] = {}
        self.assignment_items: dict[int, object] = {}
        for cfg in self.eye_configs:
            arm = gl.GLLinePlotItem(pos=np.zeros((2, 3)), color=(0.9, 0.9, 0.92, 1.0), width=2.0, antialias=True, mode="line_strip")
            ring = gl.GLLinePlotItem(pos=np.zeros((EYE_RING_POINTS, 3)), color=(0.9, 0.9, 0.92, 1.0), width=1.0, antialias=True, mode="line_strip")
            disc = gl.GLMeshItem(
                meshdata=build_disc_mesh((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), DYNAMIC_RING_RADIUS),
                smooth=False,
                color=(0.5, 0.5, 0.5, 0.85),
                shader=None,
                glOptions="translucent",
            )
            assign = gl.GLLinePlotItem(pos=np.zeros((2, 3)), color=(0.5, 0.5, 0.5, 0), width=1.5, antialias=True, mode="line_strip")
            self.gimbal_arm_items[cfg.eye_id] = arm
            self.eye_ring_items[cfg.eye_id] = ring
            self.eye_disc_items[cfg.eye_id] = disc
            self.assignment_items[cfg.eye_id] = assign
            self.view.addItem(arm)
            self.view.addItem(disc)
            self.view.addItem(ring)
            self.view.addItem(assign)

        self.trail_items = [
            gl.GLLinePlotItem(pos=np.zeros((0, 3)), color=(0.82, 0.82, 0.86, 0), width=1.2, antialias=True, mode="line_strip")
            for _ in range(36)
        ]
        for item in self.trail_items:
            self.view.addItem(item)

    def _set_text_item(self, store: dict[int, object], key: int, position: tuple[float, float, float], text: str) -> None:
        if GLTextItem is None:
            return
        item = store.get(key)
        if item is None:
            item = GLTextItem(pos=position, text=text, color=QtGui.QColor(235, 235, 240))
            store[key] = item
            self.view.addItem(item)
            return
        item.setData(pos=position, text=text, color=QtGui.QColor(235, 235, 240))

    def _sync_text_items(
        self,
        tracked_faces: dict[int, object],
        face_to_eyes: dict[int, list[int]],
    ) -> None:
        if GLTextItem is None:
            return

        live_face_ids = set(tracked_faces)
        for face_id in list(self.face_label_items):
            if face_id not in live_face_ids:
                self.view.removeItem(self.face_label_items.pop(face_id))
        for face_id in list(self.eye_label_items):
            if face_id not in live_face_ids:
                self.view.removeItem(self.eye_label_items.pop(face_id))

        for track_id, tf in tracked_faces.items():
            pos = tf.position
            label = f"Face ID: {track_id} [STATIC]" if tf.is_static else f"Face ID: {track_id}"
            face_pos = (pos.x, pos.y, pos.z + 0.06)
            self._set_text_item(self.face_label_items, track_id, face_pos, label)
            if track_id in face_to_eyes:
                eye_pos = (pos.x, pos.y, pos.z - 0.10)
                eye_label = "Eyes: " + ",".join(map(str, face_to_eyes[track_id]))
                self._set_text_item(self.eye_label_items, track_id, eye_pos, eye_label)
            elif track_id in self.eye_label_items:
                self.view.removeItem(self.eye_label_items.pop(track_id))

    def _sync_face_meshes(self, tracked_faces: dict[int, object]) -> None:
        live_face_ids = set(tracked_faces)
        for face_id in list(self.face_mesh_items):
            if face_id not in live_face_ids:
                self.view.removeItem(self.face_mesh_items.pop(face_id))

        for face_id, tf in tracked_faces.items():
            pos = tf.position
            mesh_item = self.face_mesh_items.get(face_id)
            if mesh_item is None:
                meshdata = gl.MeshData.sphere(rows=12, cols=24, radius=0.06)
                mesh_item = gl.GLMeshItem(
                    meshdata=meshdata,
                    smooth=True,
                    color=(0.92, 0.92, 0.96, 1.0),
                    shader="shaded",
                    glOptions="opaque",
                )
                self.face_mesh_items[face_id] = mesh_item
                self.view.addItem(mesh_item)
            mesh_item.resetTransform()
            mesh_item.translate(pos.x, pos.y, pos.z)

    def advance_frame(self) -> None:
        if self.num_frames > 0 and self.frame >= self.num_frames:
            self.timer.stop()
            return

        detections = get_detections(self.frame)
        tracked_faces = self.tracker.update(detections)
        eye_states = self.eye_manager.update(tracked_faces)

        face_to_eyes: dict[int, list[int]] = {}
        for eye_id, state in eye_states.items():
            if state.face_id is not None:
                face_to_eyes.setdefault(state.face_id, []).append(eye_id)

        self.eye_strip.update_states(eye_states)
        self._update_scene(tracked_faces, eye_states, face_to_eyes)
        self.frame_counter_label.setText(f"Frame {self.frame}")
        self.frame_counter_label.adjustSize()
        self._position_overlays()
        self.frame += 1

    def push_frame(self, frame: int, tracked_faces: dict, eye_states: dict) -> None:
        """Update the visualization with externally-supplied pipeline data."""
        face_to_eyes: dict[int, list[int]] = {}
        for eye_id, state in eye_states.items():
            if state.face_id is not None:
                face_to_eyes.setdefault(state.face_id, []).append(eye_id)
        self.eye_strip.update_states(eye_states)
        self._update_scene(tracked_faces, eye_states, face_to_eyes)
        self.frame_counter_label.setText(f"Frame {frame}")
        self.frame_counter_label.adjustSize()
        self._position_overlays()

    def _update_scene(
        self,
        tracked_faces: dict[int, object],
        eye_states: dict[int, object],
        face_to_eyes: dict[int, list[int]],
    ) -> None:
        for eye_id, state in eye_states.items():
            cfg = self.eye_cfg_by_id[eye_id]
            yaw_r = math.radians(state.yaw)
            pitch_r = math.radians(state.pitch)

            ox, oy, oz = cfg.pitch_pivot_offset.x, cfg.pitch_pivot_offset.y, cfg.pitch_pivot_offset.z
            pp_x = cfg.position.x + ox * math.cos(yaw_r) - oy * math.sin(yaw_r)
            pp_y = cfg.position.y + ox * math.sin(yaw_r) + oy * math.cos(yaw_r)
            pp_z = cfg.position.z + oz

            arm_points = np.array(
                [[cfg.position.x, cfg.position.y, cfg.position.z], [pp_x, pp_y, pp_z]],
                dtype=float,
            )
            self.gimbal_arm_items[eye_id].setData(pos=arm_points, color=(0.9, 0.9, 0.92, 1.0))

            cp, sp = math.cos(pitch_r), math.sin(pitch_r)
            cy, sy = math.cos(yaw_r), math.sin(yaw_r)
            ux, uy, uz = -sy, cy, 0.0
            vx, vy, vz = -sp * cy, -sp * sy, cp
            ring_x = pp_x + DYNAMIC_RING_RADIUS * (np.cos(self.theta_ring) * ux + np.sin(self.theta_ring) * vx)
            ring_y = pp_y + DYNAMIC_RING_RADIUS * (np.cos(self.theta_ring) * uy + np.sin(self.theta_ring) * vy)
            ring_z = pp_z + DYNAMIC_RING_RADIUS * (np.cos(self.theta_ring) * uz + np.sin(self.theta_ring) * vz)
            ring_points = np.column_stack((ring_x, ring_y, ring_z))
            disc_mesh = build_disc_mesh(
                (pp_x, pp_y, pp_z),
                (ux, uy, uz),
                (vx, vy, vz),
                DYNAMIC_RING_RADIUS * 0.96,
            )
            self.eye_disc_items[eye_id].setMeshData(meshdata=disc_mesh)
            self.eye_disc_items[eye_id].setColor(color_to_rgbf(state.iris_color))
            self.eye_ring_items[eye_id].setData(pos=ring_points, color=(0.9, 0.9, 0.92, 1.0))

            if state.face_id is not None and state.face_id in tracked_faces:
                fp = tracked_faces[state.face_id].position
                ray_len = math.sqrt((fp.x - pp_x) ** 2 + (fp.y - pp_y) ** 2 + (fp.z - pp_z) ** 2)
                look_x = cp * cy
                look_y = cp * sy
                look_z = sp
                assign_points = np.array(
                    [[pp_x, pp_y, pp_z], [pp_x + ray_len * look_x, pp_y + ray_len * look_y, pp_z + ray_len * look_z]],
                    dtype=float,
                )
                self.assignment_items[eye_id].setData(pos=assign_points, color=color_to_rgbf(state.iris_color))
            else:
                self.assignment_items[eye_id].setData(
                    pos=np.zeros((0, 3), dtype=float),
                    color=(0.0, 0.0, 0.0, 0.0),
                )

        trail_slot = 0

        for track_id, tf in tracked_faces.items():
            pos = tf.position
            hist = self.track_history[track_id]
            hist["x"].append(pos.x)
            hist["y"].append(pos.y)
            hist["z"].append(pos.z)

            rx = hist["x"][-TRAIL_LEN:]
            ry = hist["y"][-TRAIL_LEN:]
            rz = hist["z"][-TRAIL_LEN:]
            n = len(rx)
            seg_size = max(1, n // TRAIL_SEGMENTS)

            for seg_i in range(0, max(n - 1, 0), seg_size):
                if trail_slot >= len(self.trail_items):
                    break
                seg_end = min(seg_i + seg_size + 1, n)
                segment = np.column_stack((rx[seg_i:seg_end], ry[seg_i:seg_end], rz[seg_i:seg_end]))
                alpha = 0.1 + 0.5 * (seg_i / max(n - 1, 1))
                self.trail_items[trail_slot].setData(pos=segment, color=(0.82, 0.82, 0.86, alpha))
                trail_slot += 1

        for i in range(trail_slot, len(self.trail_items)):
            self.trail_items[i].setData(pos=np.zeros((0, 3), dtype=float), color=(0.82, 0.82, 0.86, 0.0))
        self._sync_face_meshes(tracked_faces)
        self._sync_text_items(tracked_faces, face_to_eyes)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    window = PlotWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

