from __future__ import annotations

import math
import numpy as np
from scipy.optimize import linear_sum_assignment
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from data_types import Detection, FaceId, Position3D, TrackedFace, TrackedFaces
from kalman_filter_3d import KalmanFilter3D
from parameters import params as _params


# ---------------------------------------------------------------------------
# Track
# ---------------------------------------------------------------------------

class TrackStatus:
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    LOST      = "lost"


@dataclass
class Track:
    id: FaceId
    kalman: KalmanFilter3D
    status: str = TrackStatus.TENTATIVE

    # Lifecycle counters
    hits: int = 1                  # Total matched frames
    consecutive_hits: int = 1      # Consecutive hits since last miss
    missing_frames: int = 0        # Consecutive unmatched frames

    # Smoothed output position (EMA)
    smooth_x: float = 0.0
    smooth_y: float = 0.0
    smooth_z: float = 0.0
    ema_alpha: float = 0.4         # 0=very smooth, 1=no smoothing

    # Optional: face embedding for re-ID
    embedding: Optional[np.ndarray] = None

    # History of raw positions (for debugging / visualisation)
    position_history: deque = field(default_factory=lambda: deque(maxlen=300))

    # Static-face detection
    is_static: bool = False
    speed_window: deque = field(default_factory=lambda: deque(maxlen=_params.tracker.static_window), repr=False)

    def __post_init__(self):
        pos = self.kalman.position
        self.smooth_x = pos.x
        self.smooth_y = pos.y
        self.smooth_z = pos.z

    def predict(self):
        self.kalman.predict()

    def update(self, position: Position3D, embedding: Optional[np.ndarray] = None):
        self.kalman.update(position)
        self.hits += 1
        self.consecutive_hits += 1
        self.missing_frames = 0

        # Update embedding with EMA if provided
        if embedding is not None:
            if self.embedding is None:
                self.embedding = embedding.copy()
            else:
                keep = _params.tracker.embedding_ema_keep
                self.embedding = keep * self.embedding + (1 - keep) * embedding
                norm = np.linalg.norm(self.embedding)
                if norm > 0:
                    self.embedding /= norm

        # EMA smoothing on output position
        kp = self.kalman.position
        self.smooth_x = self.ema_alpha * kp.x + (1 - self.ema_alpha) * self.smooth_x
        self.smooth_y = self.ema_alpha * kp.y + (1 - self.ema_alpha) * self.smooth_y
        self.smooth_z = self.ema_alpha * kp.z + (1 - self.ema_alpha) * self.smooth_z

        self.position_history.append(position)

        # Update static classification using rolling max velocity.
        # Velocity is in m/frame; convert threshold to m/frame at runtime so
        # the m/s constant remains valid across different publish frequencies.
        speed = float(np.linalg.norm(self.kalman.velocity))
        self.speed_window.append(speed)
        if len(self.speed_window) == _params.tracker.static_window:
            per_frame_thresh = _params.tracker.static_speed_thresh_mps / _params.system.refresh_rate_hz
            self.is_static = max(self.speed_window) < per_frame_thresh

    def mark_missing(self):
        # Keep the Kalman filter predicting forward even when there is no
        # detection. This extrapolates the face's position using its last
        # known velocity, so the predicted position stays close to where
        # the face actually is — making it much easier to re-link when the
        # detection returns after a brief occlusion or dropout.
        self.kalman.predict()
        self.missing_frames += 1
        self.consecutive_hits = 0

    @property
    def predicted_position(self) -> Position3D:
        return self.kalman.position

    @property
    def smoothed_position(self) -> Position3D:
        return Position3D(self.smooth_x, self.smooth_y, self.smooth_z)


# ---------------------------------------------------------------------------
# FaceTracker
# ---------------------------------------------------------------------------

class FaceTracker:
    def __init__(self):
        p = _params.tracker
        # Matching
        self.base_max_distance  = p.base_max_distance
        self.depth_scale_factor = p.depth_scale_factor
        self.embedding_weight   = p.embedding_weight
        # Track lifecycle
        self.min_hits_to_confirm   = p.min_hits_to_confirm
        self.max_missing_confirmed = p.max_missing_confirmed
        self.max_missing_tentative = p.max_missing_tentative
        # Re-identification
        self.reid_window_frames = p.reid_window_frames
        self.reid_max_distance  = p.reid_max_distance
        # Smoothing
        self.ema_alpha = p.ema_alpha

        self.tracks: dict[FaceId, Track] = {}
        self.lost_tracks: list[tuple[int, Track]] = []  # (frames_since_lost, track)
        self._next_id: FaceId = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, detections: list[Detection]) -> TrackedFaces:
        """
        Process one frame of detections.

        Returns TrackedFaces (dict[FaceId, Position3D]) for all CONFIRMED tracks.
        """
        # 1. Predict all active tracks forward one step
        for track in self.tracks.values():
            track.predict()

        # 2. Match detections → active tracks (Hungarian)
        matched, unmatched_dets, unmatched_tracks = self._match(
            detections, list(self.tracks.values()),
            max_dist=self._adaptive_max_distance(detections)
        )

        # 3. Update matched tracks
        for det_idx, track_id in matched:
            det = detections[det_idx]
            self.tracks[track_id].update(det.position, det.embedding)
            if (self.tracks[track_id].consecutive_hits >= self.min_hits_to_confirm
                    and self.tracks[track_id].status == TrackStatus.TENTATIVE):
                self.tracks[track_id].status = TrackStatus.CONFIRMED

        # 4. Age unmatched active tracks
        for track_id in unmatched_tracks:
            track = self.tracks[track_id]
            track.mark_missing()
            max_miss = (self.max_missing_confirmed
                        if track.status == TrackStatus.CONFIRMED
                        else self.max_missing_tentative)
            if track.missing_frames > max_miss:
                track.status = TrackStatus.LOST
                self.lost_tracks.append([0, track])
                del self.tracks[track_id]

        # 5. Try to re-identify remaining unmatched detections against lost tracks
        still_unmatched = []
        for det_idx in unmatched_dets:
            det = detections[det_idx]
            reid_track = self._try_reid(det)
            if reid_track is not None:
                reid_track.update(det.position, det.embedding)
                reid_track.status = TrackStatus.CONFIRMED
                self.tracks[reid_track.id] = reid_track
                # Remove from lost list
                self.lost_tracks = [
                    (age, t) for age, t in self.lost_tracks if t.id != reid_track.id
                ]
            else:
                still_unmatched.append(det_idx)

        # 6. Spawn new tentative tracks for truly unmatched detections
        for det_idx in still_unmatched:
            self._spawn_track(detections[det_idx])

        # 7. Age lost tracks, discard old ones
        self.lost_tracks = [
            [age + 1, t] for age, t in self.lost_tracks
            if age + 1 <= self.reid_window_frames
        ]

        # 8. Return TrackedFace (position + is_static) for confirmed tracks only
        return {
            tid: TrackedFace(position=track.smoothed_position, is_static=track.is_static)
            for tid, track in self.tracks.items()
            if track.status == TrackStatus.CONFIRMED
        }

    def get_all_tracks(self) -> dict[FaceId, Track]:
        """Return all active tracks (confirmed + tentative)."""
        return self.tracks

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def _match(
        self,
        detections: list[Detection],
        tracks: list[Track],
        max_dist: float,
    ) -> tuple[list[tuple[int, int]], list[int], list[int]]:
        """
        Hungarian matching between detections and tracks.
        Returns (matched pairs, unmatched det indices, unmatched track ids).
        """
        if not detections or not tracks:
            return [], list(range(len(detections))), [t.id for t in tracks]

        n_det = len(detections)
        n_trk = len(tracks)

        # Build cost matrix
        cost = np.full((n_det, n_trk), fill_value=1e6)
        for i, det in enumerate(detections):
            for j, track in enumerate(tracks):
                cost[i, j] = self._cost(det, track)

        # Solve assignment
        row_ind, col_ind = linear_sum_assignment(cost)

        matched = []
        unmatched_dets = set(range(n_det))
        unmatched_tracks = {t.id for t in tracks}

        for r, c in zip(row_ind, col_ind):
            if cost[r, c] > max_dist:
                continue  # Too far — treat as unmatched
            matched.append((r, tracks[c].id))
            unmatched_dets.discard(r)
            unmatched_tracks.discard(tracks[c].id)

        return matched, list(unmatched_dets), list(unmatched_tracks)

    def _cost(self, det: Detection, track: Track) -> float:
        """
        Combined cost: weighted sum of positional distance and
        embedding dissimilarity (if both are available).
        """
        p = track.predicted_position
        pos_dist = math.sqrt(
            (det.position.x - p.x) ** 2 +
            (det.position.y - p.y) ** 2 +
            (det.position.z - p.z) ** 2
        )

        if (det.embedding is not None
                and track.embedding is not None
                and self.embedding_weight > 0):
            # Cosine distance in [0, 1]
            sim = float(np.dot(det.embedding, track.embedding) /
                        (np.linalg.norm(det.embedding) * np.linalg.norm(track.embedding) + 1e-8))
            emb_dist = (1.0 - sim) / 2.0
            w = self.embedding_weight
            return (1 - w) * pos_dist + w * emb_dist

        return pos_dist

    def _adaptive_max_distance(self, detections: list[Detection]) -> float:
        """Widen the matching gate for distant faces (depth-adaptive)."""
        if not detections:
            return self.base_max_distance
        avg_z = sum(d.position.z for d in detections) / len(detections)
        return self.base_max_distance + self.depth_scale_factor * max(0.0, avg_z - 1.0)

    # ------------------------------------------------------------------
    # Re-identification
    # ------------------------------------------------------------------

    def _try_reid(self, det: Detection) -> Optional[Track]:
        """
        Try to match a new detection to a recently lost track.
        Prefers embedding similarity when available, falls back to position.
        """
        best_track = None
        best_cost = self.reid_max_distance

        for _, track in self.lost_tracks:
            c = self._cost(det, track)
            if c < best_cost:
                best_cost = c
                best_track = track

        return best_track

    # ------------------------------------------------------------------
    # Track management
    # ------------------------------------------------------------------

    def _spawn_track(self, det: Detection):
        tid = self._next_id
        self._next_id += 1
        kf = KalmanFilter3D(det.position)
        track = Track(
            id=tid,
            kalman=kf,
            ema_alpha=self.ema_alpha,
            embedding=det.embedding.copy() if det.embedding is not None else None,
        )
        self.tracks[tid] = track
