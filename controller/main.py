from __future__ import annotations

import time
from data_types import Detection, Position3D, ControlMessage
from camera.detector import Detector
from face_tracker import FaceTracker
from eye_manager import EyeManager
from config import EYE_CONFIGS, CAMERA_CONFIG
from publisher import Publisher
from parameters import params as _params


class Controller:
    def __init__(self):
        self.running = True
        self.detector = Detector()
        self.tracker = FaceTracker()
        self.eye_mgr = EyeManager(eye_configs=EYE_CONFIGS, camera_config=CAMERA_CONFIG)
        self.publisher = Publisher()

    @staticmethod
    def _camera_xyz_to_detection(xyz_m: tuple[float, float, float]) -> Detection:
        x_right, y_down, z_forward = xyz_m
        return Detection(
            position=Position3D(
                x=z_forward,
                y=-x_right,
                z=-y_down,
            )
        )

    ###############################################################################
    # Main Loop
    ###############################################################################

    def run(self):
        frame_idx = 0
        while self.running:
            faces = self.detector.poll_faces()
            detections = [
                self._camera_xyz_to_detection(face.xyz_m)
                for face in faces or []
                if face.xyz_m is not None
            ]

            tracked_faces = self.tracker.update(detections)
            eye_states = self.eye_mgr.update(tracked_faces)

            detected_count = len(faces) if faces is not None else 0
            assigned = sum(1 for s in eye_states.values() if s.face_id is not None)
            static_count = sum(1 for tf in tracked_faces.values() if tf.is_static)
            print(
                f"[frame {frame_idx}] detected={detected_count}  "
                f"positioned={len(detections)}  tracked={len(tracked_faces)}  "
                f"assigned={assigned}  static={static_count}"
            )
            frame_idx += 1

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

            time.sleep(1 / _params.system.refresh_rate_hz)

    def shutdown(self):
        self.detector.shutdown()
        self.running = False


###############################################################################
# Main Entry
###############################################################################
if __name__ == "__main__":
    controller = Controller()
    try:
        controller.run()
    except KeyboardInterrupt:
        pass
    finally:
        controller.shutdown()
