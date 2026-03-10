from __future__ import annotations

import math
import random
import time

from data_types import Color, FaceId, EyeAssignments, EyeConfig, EyeId, EyeState, EyeStates
from colors import COLOR_POOL, GREY


class EyeManager:
    """
    Maintains render state (color, radius, rotation, eye_lid, is_cat_eye)
    for each gimbal eye.

    Color assignment rules
    ----------------------
    - Each unique face is assigned a color from the pool when first seen.
    - All eyes tracking the same face share that face's color.
    - Eyes with no assigned face morph back to grey.
    - Color transitions are time-based: speed is expressed in units/second
      and converted to a per-frame factor via 1 - exp(-speed * dt), so
      behaviour is identical regardless of update call rate.
    """

    # How many "units" to close the gap per second.
    # Higher = faster transition.  e.g. 3.0 ≈ 95% complete in ~1 second.
    COLOR_IN_SPEED  = 3.0   # speed toward a face color
    COLOR_OUT_SPEED = 1.0   # speed back toward grey (slower so color lingers)

    def __init__(self, eye_configs: list[EyeConfig]) -> None:
        self._states: dict[EyeId, EyeState] = {
            cfg.eye_id: EyeState(eye_id=cfg.eye_id)
            for cfg in eye_configs
        }

        # face_id → Color, assigned once when a face is first seen
        self._face_colors: dict[FaceId, Color] = {}

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
    # Lerp helper
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
    
    def _lerp_colors(self) -> None:
        """Lerp every eye's current color toward its target."""

        now = time.monotonic()
        dt  = now - self._last_update
        self._last_update = now

        t_in  = 1.0 - math.exp(-self.COLOR_IN_SPEED  * dt)
        t_out = 1.0 - math.exp(-self.COLOR_OUT_SPEED * dt)

        for state in self._states.values():
            if state.face_ids:
                state.color = self._lerp_color(state.color, state.target_color, t_in)
            else:
                state.color = self._lerp_color(state.color, GREY, t_out)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, assignments: EyeAssignments) -> EyeStates:
        """Update eye states from the latest gimbal assignments."""
    
        # Assign a color to any newly seen face_id
        for face_ids in assignments.values():
            for fid in face_ids:
                if fid not in self._face_colors:
                    self._face_colors[fid] = self._pick_unique_color()

        # Update face assignments and target colors
        for eye_id, face_ids in assignments.items():
            state = self._states[eye_id]
            state.face_ids = list(face_ids)

            if face_ids:
                state.target_color = self._face_colors[face_ids[0]]
            else:
                state.target_color = GREY

        self._lerp_colors()

        return dict(self._states)  