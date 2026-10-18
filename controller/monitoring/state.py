"""Receive the local feed in a worker; HTTP only reads copied latest state."""

from collections import deque
from copy import deepcopy
import json
import logging
from threading import Event, RLock, Thread
import time

import numpy as np
import zmq

from .contracts import ENDPOINT, SCHEMA_VERSION, STALE_SECONDS, geometry
from .video import VideoCache

log = logging.getLogger(__name__)


class MonitorState:
    def __init__(self):
        self.lock = RLock()
        self.video = VideoCache()
        self.source = None
        self.retired = deque(maxlen=16)
        self.received_at = None
        self.compute = None
        self.health = [
            {
                "eye_id": i,
                "address": f"192.168.5.{100 + i}",
                "status": "unknown",
                "application": "unknown",
                "motors": "unknown",
            }
            for i in range(1, 7)
        ]

    def accept(self, snapshot):
        if snapshot.get("schema_version") != SCHEMA_VERSION:
            return
        with self.lock:
            session = snapshot["session_id"]
            if session in self.retired:
                return
            if self.source:
                if (
                    session == self.source["session_id"]
                    and snapshot["timestamp"] <= self.source["timestamp"]
                ):
                    return
                if session != self.source["session_id"]:
                    self.retired.append(self.source["session_id"])
            self.source = snapshot
            self.received_at = time.monotonic()
        self.video.set_session(session)
        self.video.observe(session, snapshot.get("observation"))

    def describe(self, service=None, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            source = deepcopy(self.source) if self.source else {}
            compute, health = deepcopy(self.compute), deepcopy(self.health)
        observation = source.pop("observation", None)
        source_age = max(0.0, now - source["timestamp"]) if source else None
        capture_age = max(0.0, now - observation["timestamp"]) if observation else None
        _, _, image_timestamp = self.video.preview()
        video_age = (
            max(0.0, now - image_timestamp) if image_timestamp is not None else None
        )
        fresh = source_age is not None and source_age <= STALE_SECONDS
        source_kind = source.get("source", "main") if source else None
        camera_available = bool(source and source.get("camera_available", True))
        if compute and not fresh:
            compute["process"] = None
        for face in source.get("faces", []):
            face["observation_age_s"] = max(0.0, now - face["last_seen"])
            face["depth_age_s"] = max(0.0, now - face["last_depth_seen"])
        return {
            **source,
            "schema_version": SCHEMA_VERSION,
            "source": source_kind,
            "pid": source.get("pid") if fresh else None,
            "geometry": source.get("geometry") or geometry(),
            "active_config": source.get("active_config") if fresh else None,
            "config_revision": source.get("config_revision") if fresh else None,
            "faces": source.get("faces", []) if fresh else [],
            "eyes": source.get("eyes", []) if fresh else [],
            "timing": source.get("timing") if fresh else None,
            "crops": self.video.crop_metadata(now) if fresh and camera_available else {},
            "system": compute,
            "eye_health": health,
            "controller": {
                "status": "running" if fresh else "stale" if source else "offline",
                "age_s": source_age,
                "service": service.status if service else "unknown",
                "restart_available": bool(service and service.enabled and source_kind != "demo"),
                "restarting": bool(service and service.restarting),
                "restart_error": service.error if service else None,
            },
            "camera": {
                "available": camera_available,
                "status": "unavailable"
                if source and not camera_available
                else "streaming"
                if fresh and video_age is not None and video_age <= 1
                else "stale"
                if source
                else "offline",
                "age_s": capture_age if fresh and camera_available else None,
                "video_age_s": video_age if fresh and camera_available else None,
                "capture_key": observation.get("capture_key") if observation and fresh and camera_available else None,
            },
        }


class FeedSubscriber:
    def __init__(self, state, endpoint=ENDPOINT):
        self.state, self.endpoint = state, endpoint
        self.stop_event = Event()
        self.thread = Thread(target=self.run, name="monitor-feed", daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        context = zmq.Context()
        socket = context.socket(zmq.SUB)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVHWM, 8)
        socket.setsockopt(zmq.SUBSCRIBE, b"")
        try:
            socket.connect(self.endpoint)
            while not self.stop_event.is_set():
                if socket.poll(20):
                    parts = socket.recv_multipart()
                    try:
                        if parts[0] == b"state" and len(parts) == 2:
                            self.state.accept(json.loads(parts[1]))
                        elif parts[0] == b"video" and len(parts) == 3:
                            meta = json.loads(parts[1])
                            shape = meta["shape"]
                            if (
                                len(shape) != 3
                                or shape[2] != 3
                                or not all(
                                    type(x) is int and 0 < x <= 4096 for x in shape
                                )
                            ):
                                continue
                            image = np.frombuffer(parts[2], dtype=np.uint8).reshape(
                                shape
                            )
                            self.state.video.image(meta, image)
                    except (ValueError, KeyError, TypeError):
                        log.warning(
                            "Ignoring malformed monitoring packet", exc_info=True
                        )
                try:
                    self.state.video.render()
                except Exception:
                    log.exception(
                        "Preview encoding failed; telemetry remains available"
                    )
        except Exception:
            log.exception("Monitoring feed unavailable")
        finally:
            socket.close()
            context.term()

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=3)
