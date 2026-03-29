from __future__ import annotations

import math
import time

from data_types import (
    FaceId,
    EyeAssignments,
    EyeConfig,
    EyeId,
    EyeAssignmentState,
    TrackedFaces,
)


# ---------------------------------------------------------------------------
# Core manager
# ---------------------------------------------------------------------------

class EyeAssigner:
    """
    Manages assignment of eyes to tracked face positions.

    Each eye is described by a :class:`EyeConfig` that carries its
    physical position relative to the base link.  When a free eye must be
    chosen for a new face assignment, the **closest eye in the X-Y plane**
    is selected.

    Parameters
    ----------
    eye_configs     : list of EyeConfig objects (one per eye).
                      IDs must be unique and in the range [0, 5].
    assign_interval_s  : seconds between successive eye assignments when
                         ramping onto a new face (default 1.0).
    """

    def __init__(
        self,
        eye_configs: list[EyeConfig],
        assign_interval_s: float = 1.0,
    ) -> None:
        if len({c.eye_id for c in eye_configs}) != len(eye_configs):
            raise ValueError("EyeConfig eye_id values must be unique.")

        self.assign_interval_s = assign_interval_s
        self.num_eyes = len(eye_configs)

        # Store configs keyed by eye_id for O(1) look-up
        self._configs: dict[EyeId, EyeConfig] = {c.eye_id: c for c in eye_configs}

        # All eyes start unassigned
        self._eyes: dict[EyeId, EyeAssignmentState] = {
            c.eye_id: EyeAssignmentState(eye_id=c.eye_id) for c in eye_configs
        }

        # Pool of eye IDs that are unassigned and eligible for assignment.
        # Selection is done by proximity, so this is an unordered set.
        self._available_pool: set[EyeId] = set()

        # Track when the last eye was pulled from the available pool.
        # Initialized to now so the rate gate is active from the first frame.
        self._last_assign_time: float = time.monotonic()

        # The face positions from the most recent tracker frame.
        self._current_faces: TrackedFaces = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        tracked_faces: TrackedFaces,
    ) -> EyeAssignments:
        """
        Call once per frame with the output of tracker.update(detections).

        Parameters
        ----------
        tracked_faces : TrackedFaces

        Returns
        -------
        EyeAssignments: dict[EyeId, FaceId | None]
        Each eye maps to its assigned face ID, or None if unassigned.
        """
        now = time.monotonic()

        self._current_faces = tracked_faces
        active_face_ids = list(tracked_faces.keys())

        # 1. Handle disappearing faces – free their eyes into the available pool
        self._release_lost_faces(active_face_ids, now)

        # 2. Seed unassigned eyes into the pool BEFORE assigning, so that
        #    eyes are available on the same frame a new face appears
        self._seed_available_pool(active_face_ids, now)

        # 3. Assign from the pool.  Faces with zero eyes bypass the rate
        #    limit so the first eye is always assigned immediately.
        #    Subsequent (extra) eyes onto already-covered faces are
        #    still throttled to one per assign_interval_s.
        self._assign_available_eyes(active_face_ids, now)

        # 4. If any face is still uncovered and the pool is empty, steal one
        #    eye from the closest face that has more than one assigned.
        #    This guarantees every face gets at least one eye immediately,
        #    converging to a 1-to-1 state as faces accumulate up to num_eyes.
        self._steal_for_uncovered_faces(active_face_ids)

        # 5. Rebalance: if the distribution is uneven, return one excess eye
        #    to the pool so it can be re-assigned via the same proximity logic
        self._rebalance(active_face_ids, now)

        # 6. Return eye → face assignment map
        return {
            gid: g.assigned_face_id
            for gid, g in self._eyes.items()
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _release_lost_faces(self, active_face_ids: list[FaceId], now: float) -> None:
        """Free eyes that are assigned to faces no longer tracked."""
        for eye in self._eyes.values():
            if (
                eye.assigned_face_id is not None
                and eye.assigned_face_id not in active_face_ids
            ):
                eye.assigned_face_id = None
                if eye.eye_id not in self._available_pool:
                    eye.available_since = now
                    self._available_pool.add(eye.eye_id)

    def _seed_available_pool(self, active_face_ids: list[FaceId], now: float) -> None:
        """
        If faces exist and some eyes are completely unassigned (not assigned,
        not in the pool), add them so they eventually get assigned.
        """
        if not active_face_ids:
            return

        for eye in self._eyes.values():
            if (
                eye.assigned_face_id is None
                and eye.eye_id not in self._available_pool
            ):
                eye.available_since = now
                self._available_pool.add(eye.eye_id)

    def _assign_available_eyes(self, active_face_ids: list[FaceId], now: float) -> None:
        """
        Assign eyes from the available pool to faces.

        Priority rule
        -------------
        * Any face with **zero** assigned eyes is served immediately,
          bypassing the rate-limit timer — so new faces are never left
          uncovered for even one frame.
        * Once every face has at least one eye, additional assignments
          are throttled to one per assign_interval_s to avoid sudden
          mass re-pointing.
        """
        if not active_face_ids or not self._available_pool:
            return

        # Build current load once; updated incrementally after each assignment.
        load: dict[FaceId, int] = {fid: 0 for fid in active_face_ids}
        for eye in self._eyes.values():
            if eye.assigned_face_id in load:
                load[eye.assigned_face_id] += 1

        while self._available_pool:
            target_face_id = self._least_loaded_face(active_face_ids)
            face_is_uncovered = load[target_face_id] == 0

            # Rate gate applies only when the target face already has an eye
            if not face_is_uncovered:
                if now - self._last_assign_time < self.assign_interval_s:
                    break

            pos = self._current_faces[target_face_id]
            face_x, face_y = pos.x, pos.y
            best_eye_id = self._closest_available_eye(face_x, face_y)
            if best_eye_id is None:
                break

            self._available_pool.discard(best_eye_id)
            eye = self._eyes[best_eye_id]
            eye.assigned_face_id = target_face_id
            eye.available_since = None      
            self._last_assign_time = now

            load[target_face_id] += 1

    def _steal_for_uncovered_faces(self, active_face_ids: list[FaceId]) -> None:
        """
        For every face that still has zero eyes after normal assignment,
        find the donor face — the one with >1 eyes whose X-Y position is
        closest to the uncovered face — and immediately transfer one eye.

        This ensures all faces are covered even when the available pool is
        empty, converging toward a 1-to-1 assignment as face count grows.
        """
        # Build face → [eye_ids] load map
        face_load: dict[FaceId, list[EyeId]] = {fid: [] for fid in active_face_ids}
        for eye in self._eyes.values():
            if eye.assigned_face_id in face_load:
                face_load[eye.assigned_face_id].append(eye.eye_id)

        uncovered = [fid for fid, gids in face_load.items() if len(gids) == 0]
        if not uncovered:
            return

        # Faces eligible to donate (have more than one eye)
        donors = [fid for fid, gids in face_load.items() if len(gids) > 1]
        if not donors:
            return

        for uncovered_fid in uncovered:
            if not donors:
                break

            ux, uy = self._current_faces[uncovered_fid].x, self._current_faces[uncovered_fid].y

            # Pick the donor face closest in X-Y to the uncovered face
            donor_fid = min(
                donors,
                key=lambda fid: math.sqrt(
                    (self._current_faces[fid].x - ux) ** 2 +
                    (self._current_faces[fid].y - uy) ** 2
                ),
            )

            # Steal the eye from the donor that is closest in X-Y to the
            # uncovered face, so the transferred eye needs minimal re-pointing
            stolen_gid = min(
                face_load[donor_fid],
                key=lambda gid: math.sqrt(
                    (self._configs[gid].position.x - ux) ** 2 +
                    (self._configs[gid].position.y - uy) ** 2
                ),
            )
            face_load[donor_fid].remove(stolen_gid)
            self._eyes[stolen_gid].assigned_face_id = uncovered_fid
            face_load[uncovered_fid].append(stolen_gid)

            # Donor no longer eligible if it now has only one eye
            if len(face_load[donor_fid]) <= 1:
                donors.remove(donor_fid)

    def _closest_available_eye(self, face_x: float, face_y: float) -> EyeId | None:
        """
        Return the eye_id from the available pool whose X-Y position
        (from its EyeConfig) is closest to (face_x, face_y).
        Returns None if the pool is empty.
        """
        best_id: EyeId | None = None
        best_dist = float("inf")

        for gid in self._available_pool:
            cfg = self._configs[gid]
            dist = math.sqrt((cfg.position.x - face_x) ** 2 + (cfg.position.y - face_y) ** 2)
            if dist < best_dist:
                best_dist = dist
                best_id = gid

        return best_id

    def _rebalance(self, active_face_ids: list[FaceId], now: float) -> None:
        """
        Check whether the current distribution is uneven.  If any face has
        strictly more eyes than ceil(total / n_faces), move one eye back
        into the available pool so it can be re-assigned later via the
        proximity selection.
        """
        if len(active_face_ids) <= 1:
            return

        n_faces = len(active_face_ids)
        ideal = self.num_eyes / n_faces
        max_allowed = math.ceil(ideal)

        load: dict[FaceId, int] = {fid: 0 for fid in active_face_ids}
        for eye in self._eyes.values():
            if eye.assigned_face_id in load:
                load[eye.assigned_face_id] += 1

        for fid, count in load.items():
            if count > max_allowed:
                for eye in self._eyes.values():
                    if (
                        eye.assigned_face_id == fid
                        and eye.eye_id not in self._available_pool
                    ):
                        eye.assigned_face_id = None
                        eye.available_since = now
                        self._available_pool.add(eye.eye_id)
                        break  # only move one per face per frame

    def _least_loaded_face(self, active_face_ids: list[FaceId]) -> FaceId:
        """Return the face ID with the fewest currently-assigned eyes."""
        load: dict[FaceId, int] = {fid: 0 for fid in active_face_ids}
        for eye in self._eyes.values():
            if eye.assigned_face_id in load:
                load[eye.assigned_face_id] += 1
        return min(load, key=load.__getitem__)

    # ------------------------------------------------------------------
    # Diagnostic helpers
    # ------------------------------------------------------------------

    def debug_state(self) -> str:
        """Return a human-readable summary of the current assignment state."""
        lines = ["EyeAssignmentManager state:"]
        for g in self._eyes.values():
            cfg = self._configs[g.eye_id]
            status = (
                f"→ face {g.assigned_face_id}"
                if g.assigned_face_id is not None
                else "  (unassigned)"
            )
            lines.append(
                f"  Eye {g.eye_id:2d} "
                f"[pos=({cfg.position.x:.2f}, {cfg.position.y:.2f}, {cfg.position.z:.2f})]: "
                f"{status}"
            )
        lines.append(f"  Available pool: {sorted(self._available_pool)}")
        return "\n".join(lines)