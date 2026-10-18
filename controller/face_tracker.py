from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from data_types import Detection, FaceId, Position3D, TrackedFace, TrackedFaces
from kalman_filter_3d import KalmanFilter3D
from parameters import params as _params


class TrackStatus:
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    REACQUIRING = "reacquiring"
    LOST = "lost"


def bbox_iou(a, b) -> float:
    if a is None or b is None:
        return 0.0
    width = max(0., min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0., min(a[3], b[3]) - max(a[1], b[1]))
    intersection = width * height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


@dataclass
class Track:
    id: FaceId
    kalman: KalmanFilter3D
    status: str = TrackStatus.TENTATIVE
    hits: int = 1
    consecutive_hits: int = 1
    missing_frames: int = 0  # Diagnostic only; expiration uses elapsed seconds.
    ema_alpha: float = 0.4
    embedding: np.ndarray | None = None
    bbox: tuple[float, float, float, float] | None = None
    confidence: float = 1.0
    last_seen: float = 0.0
    last_depth_seen: float = 0.0
    lost_at: float | None = None
    reacquire_kalman: KalmanFilter3D | None = None
    reacquire_hits: int = 0
    reacquire_from_lost: bool = False
    is_static: bool = False
    speed_window: deque = field(default_factory=deque, repr=False)
    static_since: float | None = None
    position_history: deque = field(default_factory=lambda: deque(maxlen=300), repr=False)

    def __post_init__(self):
        self._smooth = np.array([self.kalman.position.x, self.kalman.position.y, self.kalman.position.z])

    @property
    def filter(self) -> KalmanFilter3D:
        return self.reacquire_kalman if self.reacquire_kalman is not None else self.kalman

    @property
    def predicted_position(self) -> Position3D:
        return self.filter.position

    @property
    def smoothed_position(self) -> Position3D:
        return Position3D(*self._smooth)

    def output_position(self, timestamp: float) -> Position3D:
        age = min(_params.tracker.coast_time_s, max(0., timestamp - self.last_depth_seen))
        return Position3D(*(self._smooth + self.kalman.velocity * age))

    def predict(self, dt: float):
        self.kalman.predict(dt)
        if self.reacquire_kalman is not None:
            self.reacquire_kalman.predict(dt)

    def reset_static(self):
        self.speed_window.clear()
        self.static_since = None
        self.is_static = False

    def mark_missing(self):
        # Prediction belongs to the frame update, exactly once per filter.
        self.missing_frames += 1
        self.consecutive_hits = 0
        self.reset_static()

    def _update_embedding(self, embedding):
        if embedding is None:
            return
        incoming = np.asarray(embedding, dtype=float)
        norm = np.linalg.norm(incoming)
        if not np.isfinite(incoming).all() or norm <= 0:
            return
        incoming = incoming / norm
        if self.embedding is None:
            self.embedding = incoming.copy()
        else:
            keep = _params.tracker.embedding_ema_keep
            self.embedding = keep * self.embedding + (1 - keep) * incoming
            self.embedding /= max(np.linalg.norm(self.embedding), 1e-8)

    def observe(self, detection: Detection, timestamp: float):
        self.bbox = detection.bbox
        self.confidence = detection.confidence
        self.last_seen = timestamp
        self.missing_frames = 0
        if detection.position is None or detection.depth_quality <= 0:
            self.reset_static()
            return
        previous = self.output_position(timestamp)
        dt = max(0., timestamp - self.last_depth_seen)
        self.filter.update(detection.position, detection.confidence * detection.depth_quality)
        self.hits += 1
        self.consecutive_hits += 1
        self._update_embedding(detection.embedding)
        if self.status == TrackStatus.REACQUIRING:
            self.reacquire_hits += 1
        else:
            alpha = 1 - (1 - self.ema_alpha) ** (dt * _params.system.refresh_rate_hz)
            current = self.kalman.state[:3]
            self._smooth = alpha * current + (1 - alpha) * np.array([previous.x, previous.y, previous.z])
        self.last_depth_seen = timestamp
        self.position_history.append(detection.position)
        self.speed_window.append((timestamp, float(np.linalg.norm(self.filter.velocity))))
        if self.static_since is None:
            self.static_since = timestamp
        window_s = _params.tracker.static_window / _params.system.refresh_rate_hz
        while self.speed_window and self.speed_window[0][0] < timestamp - window_s:
            self.speed_window.popleft()
        self.is_static = (timestamp - self.static_since >= window_s
                          and max(speed for _, speed in self.speed_window) < _params.tracker.static_speed_thresh_mps)

    def start_reacquire(self, detection: Detection, timestamp: float):
        self.status = TrackStatus.REACQUIRING
        self.reacquire_from_lost = True
        self.reacquire_kalman = KalmanFilter3D(detection.position)
        self.reacquire_hits = 1
        self.consecutive_hits = 1
        self.missing_frames = 0
        self.last_seen = self.last_depth_seen = timestamp
        self.bbox = detection.bbox
        self.confidence = detection.confidence
        self._update_embedding(detection.embedding)
        self.reset_static()

    def accept_reacquire(self):
        self.kalman = self.reacquire_kalman
        self.reacquire_kalman = None
        self.reacquire_from_lost = False
        self.reacquire_hits = 0
        self.lost_at = None
        self.status = TrackStatus.CONFIRMED
        self._smooth = self.kalman.state[:3].copy()


class FaceTracker:
    def __init__(self):
        p = _params.tracker
        for name in ("base_max_distance", "depth_scale_factor", "embedding_weight", "min_hits_to_confirm",
                     "min_hits_to_confirm_reacquiring_tracks", "max_missing_confirmed", "max_missing_tentative",
                     "reid_window_frames", "reid_max_distance", "ema_alpha"):
            setattr(self, name, getattr(p, name))
        self.tracks: dict[FaceId, Track] = {}
        self.lost_tracks: list[tuple[float, Track]] = []  # (lost timestamp, track)
        self._next_id = 0
        self._timestamp: float | None = None

    def _missing_limit(self, track: Track) -> float:
        frames = self.max_missing_tentative if track.status == TrackStatus.TENTATIVE else self.max_missing_confirmed
        return frames / _params.system.refresh_rate_hz

    def update(self, detections: list[Detection] | None, timestamp: float | None = None) -> TrackedFaces:
        """Update from one capture, or project output without consuming a frame for None.

        Explicit timestamps are monotonic capture seconds. Omitted timestamps advance
        one nominal period for deterministic synthetic callers. Late/duplicate captures
        are ignored. Publication must use get_output() so it cannot advance filter time
        ahead of a subsequently received camera capture.
        """
        if timestamp is None:
            timestamp = (self._timestamp or 0.) + (0. if detections is None else 1 / _params.system.refresh_rate_hz)
        if not math.isfinite(timestamp):
            raise ValueError("Capture timestamp must be finite")
        if detections is None:
            return self.get_output(timestamp)
        if self._timestamp is not None and timestamp <= self._timestamp:
            return self.get_output(self._timestamp)
        dt = 0. if self._timestamp is None else timestamp - self._timestamp
        self._timestamp = timestamp
        for track in self.tracks.values():
            track.predict(dt)
        for _, track in self.lost_tracks:
            track.predict(dt)

        # Expire before association so a long camera outage requires real re-ID.
        for tid, track in list(self.tracks.items()):
            if timestamp - track.last_seen > self._missing_limit(track) + 1e-9:
                self._retire(tid, track.last_seen + self._missing_limit(track))
        self._prune_lost(timestamp)
        detections = [d for d in detections if self._valid_detection(d)]
        matched, unmatched_dets, unmatched_tracks = self._match(detections, list(self.tracks.values()))
        for index, tid in matched:
            track = self.tracks[tid]
            track.observe(detections[index], timestamp)
            if track.status == TrackStatus.TENTATIVE and track.consecutive_hits >= self.min_hits_to_confirm:
                track.status = TrackStatus.CONFIRMED
            elif (track.status == TrackStatus.REACQUIRING
                  and track.reacquire_hits >= self.min_hits_to_confirm_reacquiring_tracks):
                track.accept_reacquire()
        for tid in unmatched_tracks:
            track = self.tracks[tid]
            track.mark_missing()
            if track.status == TrackStatus.REACQUIRING:
                self._retire(tid, track.lost_at)

        # Re-identification is also a joint assignment, independent of detection order.
        candidates = [detections[i] for i in unmatched_dets]
        lost = [track for _, track in self.lost_tracks]
        reidentified, remaining, _ = self._match(candidates, lost, max_dist=self.reid_max_distance, reid=True)
        for index, tid in reidentified:
            track = next(t for t in lost if t.id == tid)
            track.start_reacquire(candidates[index], timestamp)
            if self.min_hits_to_confirm_reacquiring_tracks <= 1:
                track.accept_reacquire()
            self.tracks[tid] = track
        restored = {tid for _, tid in reidentified}
        self.lost_tracks = [(at, t) for at, t in self.lost_tracks if t.id not in restored]
        for index in remaining:
            if candidates[index].position is not None and candidates[index].depth_quality > 0:
                self._spawn_track(candidates[index], timestamp)
        self._prune_lost(timestamp)
        return self.get_output(timestamp)

    def get_output(self, timestamp: float | None = None) -> TrackedFaces:
        timestamp = self._timestamp if timestamp is None else timestamp
        if timestamp is None:
            return {}
        return {tid: TrackedFace(track.output_position(timestamp), track.is_static)
                for tid, track in self.tracks.items()
                if track.status == TrackStatus.CONFIRMED
                and timestamp - track.last_seen <= self._missing_limit(track) + 1e-9}

    def get_all_tracks(self) -> dict[FaceId, Track]:
        return self.tracks

    def get_diagnostics(self, timestamp: float) -> list[dict]:
        """Return copied diagnostics without advancing filters or lifecycle counters."""
        public = self.get_output(timestamp)
        tracks = list(self.tracks.values()) + [track for _, track in self.lost_tracks]
        return [{"id": track.id, "status": track.status,
                 "position": {axis: float(getattr(public[track.id].position if track.id in public
                                                    else track.predicted_position, axis))
                              for axis in ("x", "y", "z")},
                 "velocity": [float(v) for v in track.filter.velocity],
                 "visible": track.id in public, "is_static": bool(track.is_static),
                 "bbox": list(track.bbox) if track.bbox else None,
                 "confidence": float(track.confidence), "last_seen": track.last_seen,
                 "last_depth_seen": track.last_depth_seen, "hits": track.hits,
                 "missing_frames": track.missing_frames}
                for track in tracks]

    def _retire(self, tid: int, lost_at: float):
        track = self.tracks.pop(tid)
        if track.status == TrackStatus.TENTATIVE:
            return
        track.reacquire_kalman = None
        track.reacquire_from_lost = False
        track.status = TrackStatus.LOST
        track.lost_at = lost_at
        track.reset_static()
        self.lost_tracks.append((lost_at, track))

    def _prune_lost(self, timestamp):
        self.lost_tracks = [(at, t) for at, t in self.lost_tracks
                            if timestamp - at <= self.reid_window_frames / _params.system.refresh_rate_hz + 1e-9]

    @staticmethod
    def _valid_detection(det: Detection) -> bool:
        if not (math.isfinite(det.confidence) and _params.tracker.min_detection_confidence <= det.confidence <= 1
                and math.isfinite(det.depth_quality) and 0 <= det.depth_quality <= 1):
            return False
        if det.position is not None and not all(math.isfinite(v) for v in (det.position.x, det.position.y, det.position.z)):
            return False
        if det.bbox is not None:
            if (len(det.bbox) != 4 or not all(math.isfinite(v) and 0 <= v <= 1 for v in det.bbox)
                    or det.bbox[0] >= det.bbox[2] or det.bbox[1] >= det.bbox[3]):
                return False
        return det.position is not None or det.bbox is not None

    def _adaptive_max_distance(self, position: Position3D) -> float:
        return self.base_max_distance + self.depth_scale_factor * max(0., position.x - 1.)

    def _cost(self, det: Detection, track: Track, max_dist: float | None = None, reid: bool = False) -> float:
        overlap = bbox_iou(det.bbox, track.bbox)
        if det.position is None or det.depth_quality <= 0:
            if (reid or track.status != TrackStatus.CONFIRMED
                    or self._timestamp - track.last_depth_seen > _params.tracker.depth_grace_s
                    or overlap < _params.tracker.min_bbox_iou):
                return math.inf
            return 1 - overlap
        p = track.predicted_position
        distance = math.dist((det.position.x, det.position.y, det.position.z), (p.x, p.y, p.z))
        gate = max_dist if max_dist is not None else self._adaptive_max_distance(p)
        mahalanobis = track.filter.distance_squared(det.position, det.confidence * det.depth_quality)
        if distance > gate or mahalanobis > _params.tracker.mahalanobis_gate:
            return math.inf
        cost = 0.5 * distance / gate + 0.5 * math.sqrt(max(0., mahalanobis) / _params.tracker.mahalanobis_gate)
        if det.bbox is not None and track.bbox is not None:
            cost = 0.85 * cost + 0.15 * (1 - overlap)
        if det.embedding is not None and track.embedding is not None and self.embedding_weight > 0:
            incoming = np.asarray(det.embedding)
            if incoming.shape == track.embedding.shape and np.isfinite(incoming).all():
                sim = float(np.dot(incoming, track.embedding) / (np.linalg.norm(incoming) * np.linalg.norm(track.embedding) + 1e-8))
                cost = (1 - self.embedding_weight) * cost + self.embedding_weight * (1 - np.clip(sim, -1, 1)) / 2
        return float(cost)

    def _match(self, detections: list[Detection], tracks: list[Track], max_dist: float | None = None,
               reid: bool = False) -> tuple[list[tuple[int, int]], list[int], list[int]]:
        if not detections or not tracks:
            return [], list(range(len(detections))), [t.id for t in tracks]
        # Every row has dummy columns. A penalty above all valid costs combined
        # makes cardinality primary, then minimizes uncertainty/appearance cost.
        penalty = len(detections) + len(tracks) + 1.
        cost = np.full((len(detections), len(tracks) + len(detections)), penalty)
        for i, detection in enumerate(detections):
            for j, track in enumerate(tracks):
                cost[i, j] = self._cost(detection, track, max_dist, reid)
        rows, columns = linear_sum_assignment(cost)
        matched = [(int(i), tracks[j].id) for i, j in zip(rows, columns) if j < len(tracks)]
        used_detections = {i for i, _ in matched}
        used_tracks = {tid for _, tid in matched}
        return (matched, [i for i in range(len(detections)) if i not in used_detections],
                [t.id for t in tracks if t.id not in used_tracks])

    def _spawn_track(self, detection: Detection, timestamp: float | None = None):
        timestamp = (self._timestamp or 0.) if timestamp is None else timestamp
        track = Track(self._next_id, KalmanFilter3D(detection.position), ema_alpha=self.ema_alpha,
                      bbox=detection.bbox, confidence=detection.confidence,
                      last_seen=timestamp, last_depth_seen=timestamp)
        track._update_embedding(detection.embedding)
        if self.min_hits_to_confirm <= 1:
            track.status = TrackStatus.CONFIRMED
        self.tracks[track.id] = track
        self._next_id += 1
