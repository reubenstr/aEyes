"""Clearly synthetic camera/telemetry, with no publisher or hardware imports."""

import math
import os
from threading import Event, Thread
import time
import uuid

import cv2
import numpy as np

from colors import COLOR_POOL
from .contracts import SCHEMA_VERSION, geometry, revision


class DemoFeed:
    def __init__(self, state, config):
        self.state, self.config = state, config
        self.session = "demo-" + uuid.uuid4().hex
        self.stop_event = Event()
        self.thread = Thread(target=self.run, name="monitor-demo", daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        started = time.monotonic()
        sequence = 0
        colors = [list(color.as_rgb()) for color in COLOR_POOL[:3]]
        shape = geometry()
        while not self.stop_event.is_set():
            now = time.monotonic()
            t = now - started
            capture = f"{sequence}-{round(now * 1_000_000)}"
            image = np.full((360, 640, 3), (28, 28, 28), dtype=np.uint8)
            for x in range(0, 640, 40):
                cv2.line(image, (x, 0), (x, 360), (40, 40, 40), 1)
            for y in range(0, 360, 40):
                cv2.line(image, (0, y), (640, y), (40, 40, 40), 1)
            cv2.putText(
                image,
                "SYNTHETIC CAMERA / NO HARDWARE",
                (16, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                (195, 195, 195),
                1,
            )
            faces = []
            for i, color in enumerate(colors):
                x = int(135 + i * 185 + 28 * math.sin(t * 0.38 + i))
                y = int(180 + 42 * math.sin(t * 0.27 + i * 2))
                cv2.ellipse(
                    image,
                    (x, y + 65),
                    (40, 42),
                    0,
                    180,
                    360,
                    tuple(reversed(color)),
                    -1,
                )
                cv2.ellipse(image, (x, y), (30, 41), 0, 0, 360, (112, 166, 226), -1)
                cv2.circle(image, (x - 10, y - 4), 3, (40, 40, 45), -1)
                cv2.circle(image, (x + 10, y - 4), 3, (40, 40, 45), -1)
                cv2.rectangle(image, (x - 11, y + 14), (x + 11, y + 16), (55, 55, 55), -1)
                faces.append(
                    {
                        "id": i,
                        "status": "confirmed",
                        "visible": True,
                        "is_static": False,
                        "position": {
                            "x": 1.8 + 0.25 * math.sin(t * 0.3 + i),
                            "y": (320 - x) / 220,
                            "z": (180 - y) / 220,
                        },
                        "velocity": [0.0, 0.03, 0.02],
                        "confidence": 0.93 - 0.03 * i,
                        "bbox": [
                            (x - 33) / 640,
                            (y - 45) / 360,
                            (x + 33) / 640,
                            (y + 45) / 360,
                        ],
                        "last_seen": now,
                        "last_depth_seen": now,
                        "hits": sequence + 30,
                        "missing_frames": 0,
                    }
                )
            eyes = []
            for i, cfg in enumerate(shape["eyes"]):
                fid = i // 2
                p = faces[fid]["position"]
                dx = p["x"] + shape["camera"]["x"] - cfg["position"]["x"]
                dy = p["y"] - cfg["position"]["y"]
                dz = p["z"] - cfg["position"]["z"]
                blink = max(0.05, min(1.0, abs(math.sin(t * 0.2 + i)) * 7))
                eyes.append(
                    {
                        "eye_id": i + 1,
                        "face_id": fid,
                        "iris_color": colors[fid],
                        "target_iris_color": colors[fid],
                        "eye_lid": blink,
                        "yaw": math.degrees(math.atan2(dy, dx)),
                        "pitch": math.degrees(
                            math.atan2(dz, math.hypot(dx, dy) - 0.1035)
                        ),
                    }
                )
            observation = {
                "capture_key": capture,
                "sequence": sequence,
                "timestamp": now,
                "faces": faces,
                "eyes": eyes,
            }
            self.state.accept(
                {
                    "schema_version": SCHEMA_VERSION,
                    "session_id": self.session,
                    "timestamp": now,
                    "pid": os.getpid(),
                    "geometry": shape,
                    "active_config": self.config,
                    "config_revision": revision(self.config),
                    "faces": faces,
                    "eyes": eyes,
                    "observation": observation,
                    "timing": {
                        "capture_fps": 15.0,
                        "publish_hz": 15.0,
                        "dropped_snapshots": 0,
                    },
                }
            )
            self.state.video.image(
                {"session_id": self.session, "capture_key": capture, "timestamp": now},
                image,
            )
            self.state.video.render(now)
            sequence += 1
            self.stop_event.wait(max(0.0, 1 / 15 - (time.monotonic() - now)))

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=3)
