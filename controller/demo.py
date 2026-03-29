import signal
import sys
import math
from PySide6 import QtCore, QtWidgets
from data_types import ControlMessage, Detection, Position3D
from face_tracker import FaceTracker
from eye_manager import EyeManager
from config import EYE_CONFIGS, CAMERA_CONFIG
from visual import PlotWindow
from publisher import Publisher
from parameters import params as _params

"""
    Generates demo face locations and passing data through the pipeline to the physical eyes.
    No camera or inference.

    sudo apt-get install -y libxcb-cursor0
"""


def get_detections(frame: int) -> list[Detection]:
    """Return the set of Detection objects for a given frame number.

    All positions stay within: x[1, 3], y[-2.0, 2.0], z[-1.0, 1.0].
    """
    t = frame * 0.05

    face_a = Detection(position=Position3D(
        x=1.5 + 0.3 * math.sin(t),
        y=0.0 + 0.4 * math.cos(t),
        z=0.0 + 0.3 * math.sin(t * 0.5),
    ))
    face_b = Detection(position=Position3D(
        x=2.2 + 0.4 * math.cos(t * 0.7),
        y=0.8 + 0.5 * math.sin(t * 0.9),
        z=-0.3 + 0.4 * math.sin(t * 0.3),
    ))
    face_c = Detection(position=Position3D(
        x=1.2 + 0.15 * math.sin(t * 1.3),
        y=-1.0 + 0.5 * math.cos(t * 0.6),
        z=0.5 + 0.3 * math.sin(t * 0.4),
    ))
    face_d = Detection(position=Position3D(
        x=2.7 + 0.25 * math.sin(t * 0.8),
        y=0.0 + 0.6 * math.cos(t * 1.1),
        z=-0.5 + 0.3 * math.sin(t * 0.7),
    ))
    face_e = Detection(position=Position3D(
        x=1.8 + 0.3 * math.sin(t * 1.5),
        y=-0.5 + 0.4 * math.cos(t * 1.2),
        z=0.2 + 0.3 * math.sin(t * 0.8),
    ))
    face_static = Detection(position=Position3D(
        x=1.5,
        y=0.4,
        z=0.3,
    ))

    if frame < 10:
        return [face_static, face_a, face_b, face_c, face_d]
    elif frame < 20:
        return [face_static, face_b, face_c, face_d]
    elif frame < 30:
        return [face_static, face_b, face_c, face_d, face_e]
    elif frame < 40:
        return [face_static, face_b, face_d, face_e]
    elif frame < 100:
        return [face_static, face_b, face_a]
    elif frame < 130:
        return [face_static, face_b]
    else:
        return [face_static, face_b, face_a]


class Demo(QtCore.QObject):
    def __init__(self, window: PlotWindow) -> None:
        super().__init__()
        self.window = window
        self.frame = 0
        self.tracker = FaceTracker()
        self.eye_mgr = EyeManager(eye_configs=EYE_CONFIGS, camera_config=CAMERA_CONFIG)

        self.publisher = Publisher()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000 // _params.system.refresh_rate_hz)

    def _tick(self) -> None:
        if self.window.paused:
            return
        dets = get_detections(self.frame % 500)
        tracked_faces = self.tracker.update(dets)
        eye_states = self.eye_mgr.update(tracked_faces)

        messages = {
            eye_id: ControlMessage(
                radius=state.radius,
                rotation_deg=state.rotation,
                eye_lid_position=state.eye_lid,
                iris_color=(state.iris_color.red, state.iris_color.green, state.iris_color.blue),
                cornea_color=(state.striation_color.red, state.striation_color.green, state.striation_color.blue),
                is_cat_eye=state.is_cat_eye,
                yaw=state.yaw,
                pitch=state.pitch,
            )
            for eye_id, state in eye_states.items()
        }
        self.publisher.send(messages)

        self.window.push_frame(self.frame % 500, tracked_faces, eye_states)
        self.frame += 1


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    window = PlotWindow(driven_externally=True)
    window.show()
    demo = Demo(window)
    sys.exit(app.exec())
