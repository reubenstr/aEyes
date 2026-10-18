"""Bounded capture pairing and shared JPEG work, independent of HTTP clients."""

from collections import OrderedDict
from threading import RLock
import time
from urllib.parse import urlencode

import cv2
import numpy as np


class VideoCache:
    def __init__(self):
        self.lock = RLock()
        self.session = None
        self.images = OrderedDict()
        self.observations = OrderedDict()
        self.crops = OrderedDict()
        self.latest_crops = {}
        self.jpeg = None
        self.serial = 0
        self.timestamp = None
        self.last_render = -1.0
        self.last_crop = -1.0
        self.rendered = None

    def set_session(self, session):
        with self.lock:
            if self.session == session:
                return
            self.session = session
            self.images.clear()
            self.observations.clear()
            self.crops.clear()
            self.latest_crops.clear()
            self.jpeg = self.timestamp = self.rendered = None

    @staticmethod
    def _bounded(mapping, key, value, limit=4):
        mapping[key] = value
        mapping.move_to_end(key)
        while len(mapping) > limit:
            mapping.popitem(last=False)

    def observe(self, session, observation):
        with self.lock:
            if (
                session == self.session
                and observation
                and observation.get("capture_key")
            ):
                self._bounded(
                    self.observations, observation["capture_key"], observation
                )

    def image(self, meta, image):
        with self.lock:
            if meta["session_id"] != self.session:
                return
            if (
                self.images
                and meta["timestamp"]
                < next(reversed(self.images.values()))[0]["timestamp"]
            ):
                return
            self._bounded(self.images, meta["capture_key"], (meta, image))

    @staticmethod
    def _jpeg(image):
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ok:
            raise ValueError("JPEG encoding failed")
        return encoded.tobytes()

    @staticmethod
    def _box(bbox, width, height):
        if not bbox or len(bbox) != 4 or not all(np.isfinite(bbox)):
            return None
        x1, y1, x2, y2 = bbox
        result = (
            max(0, min(width - 1, int(x1 * width))),
            max(0, min(height - 1, int(y1 * height))),
            max(0, min(width, int(x2 * width))),
            max(0, min(height, int(y2 * height))),
        )
        return result if result[2] > result[0] and result[3] > result[1] else None

    def render(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if not self.images or now - self.last_render < 0.1:
                return
            key = next(reversed(self.images))
            meta, raw = self.images[key]
            observation = self.observations.get(key)
            version = (key, bool(observation))
            if version == self.rendered:
                return
            annotated = raw.copy()
            height, width = raw.shape[:2]
            colors = {}
            assigned = set()
            if observation:
                for eye in observation["eyes"]:
                    if eye["face_id"] is not None:
                        assigned.add(eye["face_id"])
                        colors[eye["face_id"]] = eye["target_iris_color"]
                matched_boxes = set()
                make_crops = (
                    now - self.last_crop >= 0.2 and now - meta["timestamp"] <= 0.5
                )
                for face in observation["faces"]:
                    box = self._box(face["bbox"], width, height)
                    if box is None:
                        continue
                    matched_boxes.add(tuple(face["bbox"]))
                    color = tuple(reversed(colors.get(face["id"], [180, 180, 180])))
                    x1, y1, x2, y2 = box
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 1)
                    cv2.putText(
                        annotated,
                        f"#{face['id']}  {face['confidence']:.0%}",
                        (x1, max(14, y1 - 7)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.4,
                        color,
                        1,
                    )
                    if make_crops and face["id"] in assigned:
                        crop_key = (self.session, key, face["id"])
                        self._bounded(
                            self.crops,
                            crop_key,
                            (meta["timestamp"], self._jpeg(raw[y1:y2, x1:x2])),
                            16,
                        )
                        self.latest_crops[face["id"]] = {
                            "timestamp": meta["timestamp"],
                            "url": f"/api/faces/{face['id']}/crop.jpg?"
                            + urlencode({"session": self.session, "capture": key}),
                        }
                for detection in observation.get("detections", []):
                    bbox = detection.get("bbox")
                    box = self._box(bbox, width, height)
                    if box and tuple(bbox) not in matched_boxes:
                        cv2.rectangle(annotated, box[:2], box[2:], (110, 110, 110), 1)
                if make_crops:
                    self.last_crop = now
            self.jpeg = self._jpeg(annotated)
            self.serial += 1
            self.timestamp = meta["timestamp"]
            self.rendered = version
            self.last_render = now
            self.latest_crops = {
                fid: value
                for fid, value in self.latest_crops.items()
                if now - value["timestamp"] <= 0.5
            }

    def crop(self, session, capture, face_id, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            item = self.crops.get((session, capture, face_id))
            return item[1] if item and 0 <= now - item[0] <= 0.5 else None

    def preview(self):
        with self.lock:
            return self.serial, self.jpeg, self.timestamp

    def crop_metadata(self, now):
        with self.lock:
            return {
                str(fid): value["url"]
                for fid, value in self.latest_crops.items()
                if 0 <= now - value["timestamp"] <= 0.5
            }
