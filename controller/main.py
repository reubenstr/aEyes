from __future__ import annotations

import argparse
import json
import time
from contextlib import nullcontext
from dataclasses import asdict

from data_types import Detection, Position3D, ControlMessage
from face_tracker import FaceTracker
from eye_manager import EyeManager
from config import EYE_CONFIGS, CAMERA_CONFIG
from publisher import Publisher
from parameters import params as _params


class Controller:
    def __init__(self):
        # Keep pure pipeline imports usable without installing the camera SDK.
        from camera.detector import Detector
        self.running = True
        self.detector = Detector(enable_visualizer=False)
        self.tracker = FaceTracker()
        self.eye_mgr = EyeManager(eye_configs=EYE_CONFIGS, camera_config=CAMERA_CONFIG)
        self.publisher = Publisher()

    @staticmethod
    def _camera_xyz_to_detection(xyz_m: tuple[float, float, float] | None, *,
                                 bbox=None, confidence=1.0) -> Detection:
        position = None
        if xyz_m is not None:
            x_right, y_down, z_forward = xyz_m
            position = Position3D(x=z_forward, y=-x_right, z=-y_down)
        return Detection(position, bbox=bbox, confidence=confidence,
                         depth_quality=1.0 if position is not None else 0.0)

    def run(self, record_path: str | None = None):
        period = 1 / _params.system.refresh_rate_hz
        deadline = time.monotonic()
        last_capture_time = None
        log_context = open(record_path, "w") if record_path else nullcontext(None)
        with log_context as recording:
            while self.running:
                frame = self.detector.poll_frame()
                if frame is not None and (last_capture_time is None or frame.timestamp > last_capture_time):
                    detections = [self._camera_xyz_to_detection(face.xyz_m, bbox=face.bbox,
                                                                confidence=face.confidence)
                                  for face in frame.faces]
                    self.tracker.update(detections, timestamp=frame.timestamp)
                    last_capture_time = frame.timestamp
                    if recording is not None:
                        recording.write(json.dumps({"timestamp": frame.timestamp, "sequence": frame.sequence,
                                                    "detections": [asdict(d) for d in detections]}) + "\n")
                # Project for publication without moving the measurement-time filter.
                states = self.eye_mgr.update(self.tracker.get_output(time.monotonic()))
                self.publisher.send({eye_id: ControlMessage.from_state(state) for eye_id, state in states.items()})
                deadline += period
                now = time.monotonic()
                if deadline < now:
                    deadline = now  # Reset after overrun rather than replaying missed slots.
                time.sleep(max(0., deadline - now))

    def shutdown(self):
        self.running = False
        self.detector.shutdown()
        self.publisher.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", help="Write capture timestamps and project-frame detections as JSONL for replay")
    args = parser.parse_args()
    controller = Controller()
    try:
        controller.run(record_path=args.record)
    except KeyboardInterrupt:
        pass
    finally:
        controller.shutdown()
