"""
Advanced OAK-D Face Tracker
============================
Features:
  - Hungarian algorithm for optimal detection-to-track assignment
  - Kalman filter per track (position + velocity)
  - Kalman keeps predicting during missing frames for better re-linking
  - Anisotropic measurement noise (Z/depth trusted less than X/Y)
  - Depth-adaptive matching distance
  - Tentative vs confirmed track lifecycle
  - Re-identification window for recently lost tracks
  - Optional face embedding similarity (re-ID)
  - Exponential moving average smoothing on output positions
"""

import math
import numpy as np
from scipy.optimize import linear_sum_assignment
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from data_types import Detection, FaceId, Position3D, TrackedFaces


# ---------------------------------------------------------------------------
# Kalman Filter (constant-velocity model in 3D)
# ---------------------------------------------------------------------------

class KalmanFilter3D:
    """
    State vector: [x, y, z, vx, vy, vz]
    Observation:  [x, y, z]
    """

    def __init__(self, position: Position3D):
        self.state = np.array(
            [position.x, position.y, position.z, 0.0, 0.0, 0.0], dtype=float
        )

        # State transition matrix (constant velocity)
        self.F = np.eye(6)
        self.F[0, 3] = 1.0
        self.F[1, 4] = 1.0
        self.F[2, 5] = 1.0

        # Observation matrix (we only observe position)
        self.H = np.zeros((3, 6))
        self.H[0, 0] = 1.0
        self.H[1, 1] = 1.0
        self.H[2, 2] = 1.0

        # Covariance matrix
        self.P = np.eye(6) * 1.0

        # Process noise (tune for how dynamic faces move)
        q = 0.1
        self.Q = np.eye(6) * q

        # Anisotropic measurement noise: Z (depth) is noisier on OAK-D than X/Y.
        # Higher R[2,2] tells the filter to trust depth readings less and rely
        # more on its own prediction — keeps tracks stable during noisy depth
        # frames and makes re-linking after a brief miss much more reliable.
        r_xy = 0.05   # spatial noise (metres) — tune to your camera
        r_z  = 0.20   # depth noise — increase if Z readings are very jittery
        self.R = np.diag([r_xy, r_xy, r_z])

    def predict(self) -> Position3D:
        """Predict next state. Returns predicted position."""
        self.state = self.F @ self.state
        self.P = self.F @ self.P @ self.F.T + self.Q
        return Position3D(self.state[0], self.state[1], self.state[2])

    def update(self, measurement: Position3D):
        """Update with observed position."""
        z = np.array([measurement.x, measurement.y, measurement.z]) - self.H @ self.state
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.state = self.state + K @ z
        self.P = (np.eye(6) - K @ self.H) @ self.P

    @property
    def position(self) -> Position3D:
        return Position3D(self.state[0], self.state[1], self.state[2])

    @property
    def velocity(self) -> np.ndarray:
        return self.state[3:].copy()


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
                self.embedding = 0.7 * self.embedding + 0.3 * embedding
                norm = np.linalg.norm(self.embedding)
                if norm > 0:
                    self.embedding /= norm

        # EMA smoothing on output position
        kp = self.kalman.position
        self.smooth_x = self.ema_alpha * kp.x + (1 - self.ema_alpha) * self.smooth_x
        self.smooth_y = self.ema_alpha * kp.y + (1 - self.ema_alpha) * self.smooth_y
        self.smooth_z = self.ema_alpha * kp.z + (1 - self.ema_alpha) * self.smooth_z

        self.position_history.append(position)

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
    def __init__(
        self,
        # Matching
        base_max_distance: float = 0.4,      # metres at 1m depth
        depth_scale_factor: float = 0.15,    # extra distance per metre of depth
        embedding_weight: float = 0.3,       # 0 = position only, 1 = embedding only

        # Track lifecycle
        min_hits_to_confirm: int = 3,        # tentative → confirmed
        max_missing_confirmed: int = 15,     # frames before confirmed track is dropped
        max_missing_tentative: int = 2,      # frames before tentative track is dropped

        # Re-identification
        reid_window_frames: int = 30,        # how long to keep lost tracks for re-ID
        reid_max_distance: float = 0.8,      # wider search radius for re-ID

        # Smoothing
        ema_alpha: float = 0.4,
    ):
        self.base_max_distance = base_max_distance
        self.depth_scale_factor = depth_scale_factor
        self.embedding_weight = embedding_weight
        self.min_hits_to_confirm = min_hits_to_confirm
        self.max_missing_confirmed = max_missing_confirmed
        self.max_missing_tentative = max_missing_tentative
        self.reid_window_frames = reid_window_frames
        self.reid_max_distance = reid_max_distance
        self.ema_alpha = ema_alpha

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

        # 8. Return smoothed positions for confirmed tracks only
        return {
            tid: track.smoothed_position
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


# ---------------------------------------------------------------------------
# Example usage / smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random

    random.seed(42)
    tracker = FaceTracker(
        base_max_distance=0.4,
        depth_scale_factor=0.15,
        min_hits_to_confirm=3,
        max_missing_confirmed=15,
        reid_window_frames=30,
        ema_alpha=0.4,
    )

    # Simulate two faces moving through the scene for 40 frames
    for frame in range(40):
        t = frame * 0.05  # time
        face_a = Detection(position=Position3D(
            x=0.1 + 0.02 * math.sin(t),
            y=0.0 + 0.01 * math.cos(t),
            z=1.5 + 0.05 * math.sin(t * 0.5),
        ))
        face_b = Detection(position=Position3D(
            x=-0.3 + 0.03 * math.cos(t),
            y=0.05,
            z=2.0 + 0.1 * math.sin(t * 0.3),
        ))

        # Drop face_b from frames 15–20 to test re-ID
        dets = [face_a] if 15 <= frame <= 20 else [face_a, face_b]

        result = tracker.update(dets)

        ids_str = ", ".join(
            f"ID {fid}: ({pos.x:.2f}, {pos.y:.2f}, {pos.z:.2f}m)"
            for fid, pos in sorted(result.items())
        )
        print(f"Frame {frame:02d}: {ids_str if ids_str else '(no confirmed tracks yet)'}")