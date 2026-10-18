from __future__ import annotations

import argparse
import json
import logging
import signal
import time
from contextlib import nullcontext
from dataclasses import asdict

from data_types import Detection, Position3D, ControlMessage
from face_tracker import FaceTracker
from eye_manager import EyeManager
from config import EYE_CONFIGS, CAMERA_CONFIG
from publisher import Publisher
from parameters import params as _params
from demo import get_detections


class Controller:
    def __init__(self, monitor=True, demo=False):
        self.running = True
        self.detector = None
        if not demo:
            # Demo mode never imports or opens the camera SDK.
            from camera.detector import Detector
            self.detector = Detector(enable_visualizer=False, enable_preview=monitor)
        self.tracker = FaceTracker()
        self.eye_mgr = EyeManager(eye_configs=EYE_CONFIGS, camera_config=CAMERA_CONFIG)
        self.publisher = Publisher()
        self.monitor = None
        if monitor:
            from monitoring.bridge import MonitorBridge
            self.monitor = MonitorBridge(
                self.detector.preview_queue if self.detector is not None else None,
                active_config=_params, source="demo" if demo else "main",
                camera_available=not demo,
            )

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
        demo_frame = 0
        log_context = open(record_path, "w") if record_path else nullcontext(None)
        with log_context as recording:
            while self.running:
                observed = None
                frame = None
                detections = None
                if self.detector is None:
                    timestamp = time.monotonic()
                    sequence = demo_frame
                    detections = get_detections(demo_frame % 500)
                    demo_frame += 1
                else:
                    frame = self.detector.poll_frame()
                    if frame is not None:
                        timestamp, sequence = frame.timestamp, frame.sequence
                        detections = [self._camera_xyz_to_detection(face.xyz_m, bbox=face.bbox,
                                                                    confidence=face.confidence)
                                      for face in frame.faces]
                if detections is not None and (last_capture_time is None or timestamp > last_capture_time):
                    self.tracker.update(detections, timestamp=timestamp)
                    last_capture_time = timestamp
                    observed = frame
                    if recording is not None:
                        recording.write(json.dumps({"timestamp": timestamp, "sequence": sequence,
                                                    "detections": [asdict(d) for d in detections]}) + "\n")
                # Project for publication without moving the measurement-time filter.
                states = self.eye_mgr.update(self.tracker.get_output(time.monotonic()))
                self.publisher.send({eye_id: ControlMessage.from_state(state) for eye_id, state in states.items()})
                if getattr(self, "monitor", None) is not None:
                    try:
                        self.monitor.offer(self.tracker, states, observed)
                    except Exception:
                        logging.exception("Monitoring snapshot failed; publication continues")
                deadline += period
                now = time.monotonic()
                if deadline < now:
                    deadline = now  # Reset after overrun rather than replaying missed slots.
                time.sleep(max(0., deadline - now))

    def shutdown(self):
        self.running = False
        try:
            if self.monitor:
                self.monitor.close()
        finally:
            try:
                if self.detector is not None:
                    self.detector.shutdown()
            finally:
                self.publisher.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Track faces and publish commands to the eyes")
    parser.add_argument("--demo", action="store_true",
                        help="Use synthetic detections without a camera or display (publishes commands to physical eyes)")
    parser.add_argument("--record", help="Write frame timestamps and project-frame detections as JSONL for replay")
    parser.add_argument("--monitor", action=argparse.BooleanOptionalAction, default=True,
                        help="Publish dashboard telemetry/preview (enabled by default; --no-monitor disables it)")
    args = parser.parse_args(argv)
    controller = Controller(monitor=args.monitor, demo=args.demo)
    signal.signal(signal.SIGTERM, lambda *_: setattr(controller, "running", False))
    try:
        controller.run(record_path=args.record)
    except KeyboardInterrupt:
        pass
    finally:
        controller.shutdown()


if __name__ == "__main__":
    main()
