from __future__ import annotations

import time
from data_types import Detection, Position3D, ControlMessage
from detector import Detector
from face_tracker import FaceTracker
from eye_manager import EyeManager
from config import EYE_CONFIGS, CAMERA_CONFIG
from publisher import Publisher

REFRESH_RATE_HZ = 15


class Controller:
    def __init__(self):
        self.running = True
        self.detector = Detector()
        self.tracker = FaceTracker()
        self.eye_mgr = EyeManager(eye_configs=EYE_CONFIGS, camera_config=CAMERA_CONFIG)
        self.publisher = Publisher()

    ###############################################################################
    # Main Loop
    ###############################################################################

    def run(self):
        frame_idx = 0
        while self.running:
            color_bgr, depth_u16, intr = self.detector.cam.get_aligned_frames()
            if color_bgr is None:
                continue

            dets, _ = self.detector.det.detect(color_bgr)

            # Convert FaceDetection (pixel bbox) → Detection (3D position in meters).
            # The detector returns raw bounding boxes in image coordinates; face_xyz()
            # back-projects the bbox centre through the RealSense depth frame using
            # camera intrinsics to produce a metric Position3D.
            # Faces where depth is unavailable or out of range are skipped.
            detections = []
            for f in dets:
                xyz = self.detector.cam.face_xyz(depth_u16, intr, f.bbox_xyxy)
                if xyz is not None:
                    # Remap from RealSense camera frame (X=right, Y=down, Z=forward)
                    # to system frame (X=forward, Y=left, Z=up)
                    detections.append(Detection(position=Position3D(x=xyz[2], y=-xyz[0], z=-xyz[1])))

            tracked_faces = self.tracker.update(detections)
            eye_states = self.eye_mgr.update(tracked_faces)

            assigned = sum(1 for s in eye_states.values() if s.face_id is not None)
            print(f"[frame {frame_idx}] detected={len(dets)}  tracked={len(tracked_faces)}  assigned={assigned}")
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

            time.sleep(1 / REFRESH_RATE_HZ)

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
