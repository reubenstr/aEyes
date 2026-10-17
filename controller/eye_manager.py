from __future__ import annotations

import colorsys
import math
import random
import time

from data_types import CameraConfig, Color, FaceId, EyeConfig, EyeId, EyeState, EyeStates, TrackedFaces
from colors import COLOR_POOL, GREY, BLACK
from conversions import Conversions
from eye_assigner import EyeAssigner
from parameters import params as _params

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

    def __init__(self, eye_configs: list[EyeConfig], camera_config: CameraConfig) -> None:
        p = _params.eye_manager
        self._params = p
        # Higher = faster transition.  e.g. 3.0 ≈ 95% complete in ~1 second.
        self.COLOR_IN_RATE  = p.color_in_rate   # speed toward a face color
        self.COLOR_OUT_RATE = p.color_out_rate  # speed back toward grey
        self.BLINK_RATE     = p.blink_rate      # complete blinks per second

        self._eye_assigner = EyeAssigner(eye_configs)

        self._conversions = Conversions(eye_configs, camera_config)
        
        self._states: dict[EyeId, EyeState] = {
            cfg.eye_id: EyeState(
                eye_id=cfg.eye_id,
                radius=p.radius,
                curvature=p.curvature,
                iris_size=p.iris_size,
                pupil_size=p.pupil_size,
                is_cat_eye=p.is_cat_eye,
                pupil_color=Color(*p.pupil_color),
                sclera_color=Color(*p.sclera_color),
                vein_color=Color(*p.vein_color),
                vein_count=p.vein_count,
                vein_seed=cfg.eye_id if p.vein_seed is None else p.vein_seed,
                eye_lid=p.eyelid_neutral_openness,
                resting_eye_lid=p.eyelid_neutral_openness,
            )
            for cfg in eye_configs
        }
        self._palette_channels = ("iris_color", "iris_accent_color", "iris_center_color", "striation_color")
        self._color_values = {
            eye_id: {name: getattr(state, name).as_rgb() for name in self._palette_channels}
            for eye_id, state in self._states.items()
        }

        # face_id → Color, assigned once when a face is first seen
        self._face_colors: dict[FaceId, Color] = {}

        # eye_id → blink start time (None = not blinking)
        self._blink_starts: dict[EyeId, float | None] = {
            cfg.eye_id: None for cfg in eye_configs
        }
        self._blink_closed: set[EyeId] = set()

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
    def _offset_color(color: Color, hue_offset: float, lightness: float, saturation: float) -> Color:
        hue = colorsys.rgb_to_hls(*(c / 255.0 for c in color.as_rgb()))[0]
        rgb = colorsys.hls_to_rgb((hue + hue_offset) % 1.0, lightness, saturation)
        return Color(*(int(round(c * 255.0)) for c in rgb))

    def _set_palette(self, state: EyeState, base: Color | None) -> None:
        state.target_iris_color = base if base is not None else GREY
        for channel in ("accent", "center", "striation"):
            if base is None:
                color = BLACK if channel == "striation" else GREY
            else:
                color = self._offset_color(
                    base,
                    getattr(self._params, f"iris_{channel}_hue_offset"),
                    getattr(self._params, f"iris_{channel}_lightness"),
                    getattr(self._params, f"iris_{channel}_saturation"),
                )
            name = "striation_color" if channel == "striation" else f"iris_{channel}_color"
            setattr(state, f"target_{name}", color)

    def _lerp_colors(self, dt: float) -> None:
        """Lerp every eye's current color toward its target."""

        t_in  = 1.0 - math.exp(-self.COLOR_IN_RATE  * dt)
        t_out = 1.0 - math.exp(-self.COLOR_OUT_RATE * dt)

        for eye_id, state in self._states.items():
            t = t_in if state.face_id is not None else t_out
            for name in self._palette_channels:
                current = self._color_values[eye_id][name]
                target = getattr(state, f"target_{name}").as_rgb()
                rgb = tuple(c + (goal - c) * t for c, goal in zip(current, target))
                self._color_values[eye_id][name] = rgb
                setattr(state, name, Color(*(round(c) for c in rgb)))

    def _resting_openness_for_distance(self, distance: float) -> float:
        p = self._params
        t = min(1.0, max(0.0, (distance - p.eyelid_near_distance_m)
                         / (p.eyelid_far_distance_m - p.eyelid_near_distance_m)))
        t = t * t * (3.0 - 2.0 * t)
        return p.eyelid_near_openness + t * (p.eyelid_far_openness - p.eyelid_near_openness)

    def _update_resting_eyelids(self, tracked_faces: TrackedFaces, dt: float) -> None:
        p = self._params
        blend = 1.0 - math.exp(-p.eyelid_smoothing_rate * dt)
        for eye_id, state in self._states.items():
            target = p.eyelid_neutral_openness
            if state.face_id is not None and state.face_id in tracked_faces:
                distance = self._conversions.get_target_distance(eye_id, tracked_faces[state.face_id].position)
                if math.isfinite(distance):
                    target = self._resting_openness_for_distance(distance)
            state.resting_eye_lid += (target - state.resting_eye_lid) * blend

    def _update_blinks(self, now: float) -> None:
        """Animate eye_lid as a blink (open → closed → open) when a new face is assigned."""
        blink_duration = 1.0 / self.BLINK_RATE
        half = blink_duration / 2.0

        for eye_id, state in self._states.items():
            start = self._blink_starts[eye_id]
            if start is None:
                state.eye_lid = state.resting_eye_lid
                continue

            elapsed = now - start
            # At 15 Hz the midpoint can fall between updates; send one fully closed frame.
            if elapsed >= half and eye_id not in self._blink_closed:
                state.eye_lid = 0.0
                self._blink_closed.add(eye_id)
            elif elapsed >= blink_duration:
                state.eye_lid = state.resting_eye_lid
                self._blink_starts[eye_id] = None
            elif elapsed < half:
                state.eye_lid = state.resting_eye_lid * (1.0 - elapsed / half)
            else:
                state.eye_lid = state.resting_eye_lid * ((elapsed - half) / half)

    def _update_orientation(self, tracked_faces: TrackedFaces):
        """Compute gimbal angles for each eye tracking a face"""
        for eye_id, state in self._states.items():
            if state.face_id is not None and state.face_id in tracked_faces:
                state.yaw, state.pitch = self._conversions.get_pitch_yaw(
                    eye_id, tracked_faces[state.face_id].position
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
        dt = max(0.0, now - self._last_update)
        self._last_update = now

        # Assign eyes to faces
        assignments = self._eye_assigner.update(tracked_faces)
       
        # Free colors for non-static faces no longer tracked, so the pool doesn't exhaust
        active_ids = {fid for fid, tf in tracked_faces.items() if not tf.is_static}
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
                self._set_palette(state, self._face_colors[face_id])
                if prev_face_id != face_id:
                    self._blink_starts[eye_id] = now
                    self._blink_closed.discard(eye_id)
            else:
                self._set_palette(state, None)

        self._lerp_colors(dt)
        self._update_resting_eyelids(tracked_faces, dt)
        self._update_blinks(now)
        self._update_orientation(tracked_faces)      

        return dict(self._states)
