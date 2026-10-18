"""Optional main-thread snapshot copy; all transport/image work runs in a worker."""

from collections import deque
from dataclasses import asdict
import logging
import os
from queue import Queue, Empty, Full
from threading import Event, Thread
import time
import uuid

from .contracts import ENDPOINT, SCHEMA_VERSION, capture_key, geometry, revision

log = logging.getLogger(__name__)


class MonitorBridge:
    def __init__(self, preview_queue=None, endpoint=ENDPOINT, active_config=None):
        self.preview_queue = preview_queue
        self.endpoint = endpoint
        self.session = uuid.uuid4().hex
        self.active = asdict(active_config) if active_config else {}
        self.static = {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session,
            "pid": os.getpid(),
            "geometry": geometry(),
            "active_config": self.active,
            "config_revision": revision(self.active),
        }
        self.pending = Queue(maxsize=1)
        self.stop_event = Event()
        self.dropped = 0
        self.observation = None
        self.captures = deque(maxlen=60)
        self.publications = deque(maxlen=60)
        self.worker = Thread(target=self._worker, name="monitor-bridge", daemon=True)
        self.worker.start()

    def offer(self, tracker, states, frame=None):
        now = time.monotonic()
        faces = tracker.get_diagnostics(now)
        eyes = []
        for state in states.values():
            copied = asdict(state)
            for name, value in copied.items():
                if isinstance(value, dict) and set(value) == {"red", "green", "blue"}:
                    copied[name] = [value["red"], value["green"], value["blue"]]
            eyes.append(copied)
        if frame is not None:
            self.captures.append(frame.timestamp)
            self.observation = {
                "capture_key": frame.capture_key,
                "timestamp": frame.timestamp,
                "sequence": frame.sequence,
                "faces": [f for f in faces if f["last_seen"] == frame.timestamp],
                "eyes": eyes,
                "detections": [
                    {
                        "bbox": list(f.bbox) if f.bbox else None,
                        "confidence": float(f.confidence),
                    }
                    for f in frame.faces
                ],
            }
        self.publications.append(now)
        rate = lambda samples: (
            (len(samples) - 1) / (samples[-1] - samples[0])
            if len(samples) > 1 and samples[-1] > samples[0] and now - samples[-1] <= 1
            else 0.0
        )
        snapshot = {
            **self.static,
            "timestamp": now,
            "faces": faces,
            "eyes": eyes,
            "observation": self.observation,
            "timing": {
                "capture_fps": rate(self.captures),
                "publish_hz": rate(self.publications),
                "dropped_snapshots": self.dropped,
            },
        }
        self.offer_snapshot(snapshot)

    def offer_snapshot(self, snapshot):
        try:
            self.pending.put_nowait(snapshot)
        except Full:
            try:
                self.pending.get_nowait()
            except Empty:
                pass
            self.dropped += 1
            try:
                self.pending.put_nowait(snapshot)
            except Full:
                pass

    def _worker(self):
        import json
        import zmq

        context = zmq.Context()
        socket = context.socket(zmq.PUB)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.SNDHWM, 4)
        last_video = 0.0
        try:
            socket.bind(self.endpoint)
            while not self.stop_event.wait(0.005):
                try:
                    snapshot = self.pending.get_nowait()
                    socket.send_multipart(
                        [b"state", json.dumps(snapshot, allow_nan=False).encode()],
                        flags=zmq.NOBLOCK,
                    )
                except Empty:
                    pass
                if (
                    self.preview_queue is not None
                    and time.monotonic() - last_video >= 0.1
                ):
                    messages = self.preview_queue.tryGetAll()
                    if messages:
                        message = messages[-1]
                        image = message.getCvFrame()
                        meta = {
                            "session_id": self.session,
                            "capture_key": capture_key(message),
                            "shape": image.shape,
                            "timestamp": time.monotonic()
                            - max(
                                0.0,
                                # SDK clock conversion stays in this optional adapter.
                                self._capture_age(message),
                            ),
                        }
                        socket.send_multipart(
                            [b"video", json.dumps(meta).encode(), image.tobytes()],
                            flags=zmq.NOBLOCK,
                        )
                        last_video = time.monotonic()
        except Exception:
            log.exception("Monitoring feed stopped; controller publication continues")
        finally:
            socket.close()
            context.term()

    @staticmethod
    def _capture_age(message):
        import depthai as dai

        return (dai.Clock.now() - message.getTimestamp()).total_seconds()

    def close(self):
        self.stop_event.set()
        self.worker.join(timeout=2)
