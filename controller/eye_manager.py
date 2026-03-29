from __future__ import annotations

import math
import random
import time

from data_types import CameraConfig, Color, FaceId, EyeAssignments, EyeConfig, EyeId, EyeState, EyeStates, TrackedFaces
from colors import COLOR_POOL, GREY
from conversions import Conversions
from eye_assigner import EyeAssigner

class EyeManager:
    """
    Maintains render state (color, radius, rotation, eye_lid, is_cat_eye)
    for each eye.

    Color assignment rules
    ----------------------
    - Each unique face is assigned a color from the pool when first seen.
    - All eyes tracking the same face share that face's color.
    - Eyes with no assigned face morph back to grey.
    - Color transitions are time-based: speed is expressed in units/second
      and converted to a per-frame factor via 1 - exp(-speed * dt), so
      behaviour is identical regardless of update call rate.
    """
    
    # Higher = faster transition.  e.g. 3.0 ≈ 95% complete in ~1 second.
    COLOR_IN_RATE  = 2.0   # speed toward a face color
    COLOR_OUT_RATE = 4.0   # speed back toward grey
    
    BLINK_RATE      = 1.0   # complete blinks per second (1.0 = 1 second per blink)

    def __init__(self, eye_configs: list[EyeConfig], camera_config: CameraConfig) -> None:

        self._eye_assigner = EyeAssigner(eye_configs)

        self._conversions = Conversions(eye_configs, camera_config)
        
        self._states: dict[EyeId, EyeState] = {
            cfg.eye_id: EyeState(eye_id=cfg.eye_id)
            for cfg in eye_configs
        }

        # face_id → Color, assigned once when a face is first seen
        self._face_colors: dict[FaceId, Color] = {}

        # eye_id → blink start time (None = not blinking)
        self._blink_starts: dict[EyeId, float | None] = {
            cfg.eye_id: None for cfg in eye_configs
        }

        self._last_update: float = time.monotonic()

    # ------------------------------------------------------------------
    # Color pool helpers
    # ------------------------------------------------------------------

    def _pick_unique_color(self) -> Color:
        """Pick a random color not already assigned to an active face."""
        assigned = {id(c) for c in self._face_colors.values()}
        available = [c for c in COLOR_POOL if id(c) not in assigned]
        return random.choice(available if available else COLOR_POOL)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _lerp_color(current: Color, target: Color, t: float) -> Color:
        """
        Linearly interpolate each channel of current toward target by t.

        t is computed as 1 - exp(-speed * dt) so it is frame-rate independent.
        """
        return Color(
            red=  int(current.red   + (target.red   - current.red)   * t),
            green=int(current.green + (target.green - current.green) * t),
            blue= int(current.blue  + (target.blue  - current.blue)  * t),
        )
    
    def _lerp_colors(self, now: float) -> None:
        """Lerp every eye's current color toward its target."""

        dt = now - self._last_update
        self._last_update = now

        t_in  = 1.0 - math.exp(-self.COLOR_IN_RATE  * dt)
        t_out = 1.0 - math.exp(-self.COLOR_OUT_RATE * dt)

        for state in self._states.values():
            if state.face_id is not None:
                state.iris_color = self._lerp_color(state.iris_color, state.target_iris_color, t_in)
                state.striation_color = self._lerp_color(state.striation_color, state.target_striation_color, t_in)
            else:
                state.iris_color = self._lerp_color(state.iris_color, GREY, t_out)
                state.striation_color = self._lerp_color(state.striation_color, GREY, t_out)

    def _update_blinks(self, now: float) -> None:
        """Animate eye_lid as a blink (open → closed → open) when a new face is assigned."""
        blink_duration = 1.0 / self.BLINK_RATE
        half = blink_duration / 2.0

        for eye_id, state in self._states.items():
            start = self._blink_starts[eye_id]
            if start is None:
                state.eye_lid = 1.0
                continue

            elapsed = now - start
            if elapsed >= blink_duration:
                state.eye_lid = 1.0
                self._blink_starts[eye_id] = None
            elif elapsed < half:
                state.eye_lid = 1.0 - (elapsed / half)   # open → closed
            else:
                state.eye_lid = (elapsed - half) / half   # closed → open

    def _update_orientation(self, tracked_faces: TrackedFaces):
        """Compute gimbal angles for each eye tracking a face"""
        for eye_id, state in self._states.items():
            if state.face_id is not None and state.face_id in tracked_faces:
                state.yaw, state.pitch = self._conversions.get_pitch_yaw(
                    eye_id, tracked_faces[state.face_id]
                )
                # Partial gimbal-induced roll compensation: yaw-then-pitch kinematics
                # drag the eye's local "up" off world-vertical, making the blink appear rotated.                
                # state.rotation = -0.4 * math.degrees(math.atan2(
                #    math.sin(math.radians(state.yaw)) * math.sin(math.radians(state.pitch)),
                #    math.cos(math.radians(state.pitch))
                # ))
            else:
                state.yaw = 0.0
                state.pitch = 0.0
                state.rotation = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, tracked_faces: TrackedFaces) -> EyeStates:
        """Update eye states from the latest eye assignments."""

        now = time.monotonic()

        # Assign eyes to faces
        assignments = self._eye_assigner.update(tracked_faces)
       
        # Free colors for faces no longer tracked, so the pool doesn't exhaust
        active_ids = set(tracked_faces.keys())
        self._face_colors = {fid: c for fid, c in self._face_colors.items() if fid in active_ids}

        # Assign a color to any newly seen face_id
        for fid in assignments.values():
            if fid is not None and fid not in self._face_colors:
                self._face_colors[fid] = self._pick_unique_color()

        # Update face assignments, target colors, and trigger blinks on new assignments
        for eye_id, face_id in assignments.items():
            state = self._states[eye_id]
            prev_face_id = state.face_id
            state.face_id = face_id

            if face_id is not None:
                state.target_iris_color = self._face_colors[face_id]
                state.target_striation_color = self._face_colors[face_id]
                if prev_face_id != face_id:
                    self._blink_starts[eye_id] = now
            else:
                state.target_iris_color = GREY
                state.target_striation_color = GREY

        self._lerp_colors(now)
        self._update_blinks(now)
        self._update_orientation(tracked_faces)      

        return dict(self._states)