from __future__ import annotations

import random
from dataclasses import dataclass, field

from data_types import Color, FaceId, EyeAssignments, EyeConfig, EyeId


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------




@dataclass
class EyeState:
    """Render state for a single gimbal eye."""
    gimbal_id: EyeId
    color:      Color = field(default_factory=lambda: Color(128, 128, 128))  # default grey
    radius:     float = 1.0
    rotation:   float = 0.0   # degrees
    eye_lid:    float = 0.0   # 0.0 = fully open, 1.0 = fully closed
    is_cat_eye: bool  = False


# Return type for EyeManager.update()
EyeStates = dict[EyeId, EyeState]


# ---------------------------------------------------------------------------
# Color pool
# ---------------------------------------------------------------------------

# Ordered pool of colors assigned to faces in the order they appear.
# Grey is reserved for unassigned gimbals and is never drawn from the pool.
_COLOR_POOL: list[Color] = [
    Color(255,   0,   0),   # red
    Color(  0, 255,   0),   # green
    Color(  0,   0, 255),   # blue
    Color(255, 255,   0),   # yellow
    Color(  0, 255, 255),   # cyan
    Color(255,   0, 255),   # magenta
]

_GREY = Color(128, 128, 128)


# ---------------------------------------------------------------------------
# EyeManager
# ---------------------------------------------------------------------------

class EyeManager:
    """
    Maintains render state (color, radius, rotation, eye_lid, is_cat_eye)
    for each gimbal eye.

    Color assignment rules
    ----------------------
    - Each unique face is assigned a color from the pool in the order it is
      first seen.  The pool cycles if more faces than colors are present.
    - All gimbals tracking the same face share that face's color.
    - Gimbals with no assigned face use grey.

    Parameters
    ----------
    gimbal_configs : list of GimbalConfig objects that define the gimbal layout.
    """

    def __init__(self, eye_configs: list[EyeConfig]) -> None:
        # Initialise one EyeState per gimbal, all starting grey and unassigned
        self._states: dict[EyeId, EyeState] = {
            cfg.eye_id: EyeState(gimbal_id=cfg.eye_id)
            for cfg in eye_configs
        }

        # face_id → Color, populated lazily as new faces are seen
        self._face_colors: dict[FaceId, Color] = {}


    # ------------------------------------------------------------------
    # Color pool helpers
    # ------------------------------------------------------------------

    def _pick_unique_color(self) -> Color:
        """Pick a random color, retrying until one not already in use is found."""
        assigned = set(map(id, self._face_colors.values()))
        available = [c for c in _COLOR_POOL if id(c) not in assigned]
        # Fall back to full pool if all colors are already taken
        return random.choice(available if available else _COLOR_POOL)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, assignments: EyeAssignments) -> EyeStates:
        """
        Update eye states from the latest gimbal assignments.

        Parameters
        ----------
        assignments : GimbalAssignments  (dict[GimbalId, list[FaceId]])

        Returns
        -------
        EyeStates : dict[GimbalId, EyeState]
        """
        # Register any newly seen faces and assign them a color
        for face_ids in assignments.values():
            for fid in face_ids:
                if fid not in self._face_colors:
                    self._face_colors[fid] = self._pick_unique_color()

        # Update the color of each gimbal eye
        for gimbal_id, face_ids in assignments.items():
            if gimbal_id not in self._states:
                continue
            if face_ids:
                # Use the color of the first assigned face
                self._states[gimbal_id].color = self._face_colors[face_ids[0]]
            else:
                self._states[gimbal_id].color = _GREY

        return dict(self._states)

    def set_radius(self, gimbal_id: EyeId, radius: float) -> None:
        """Set the eye radius for a specific gimbal."""
        self._states[gimbal_id].radius = radius

    def set_rotation(self, gimbal_id: EyeId, rotation: float) -> None:
        """Set the eye rotation (degrees) for a specific gimbal."""
        self._states[gimbal_id].rotation = rotation

    def set_eye_lid(self, gimbal_id: EyeId, eye_lid: float) -> None:
        """Set the eye lid position (0.0 = open, 1.0 = closed) for a specific gimbal."""
        self._states[gimbal_id].eye_lid = eye_lid

    def set_cat_eye(self, gimbal_id: EyeId, is_cat_eye: bool) -> None:
        """Toggle cat-eye mode for a specific gimbal."""
        self._states[gimbal_id].is_cat_eye = is_cat_eye


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from data_types import EyeConfig

    configs = [
        EyeConfig(eye_id=0, x=-0.2, y=0.0, z=0.5),
        EyeConfig(eye_id=1, x=-0.1, y=0.0, z=0.5),
        EyeConfig(eye_id=2, x= 0.0, y=0.0, z=0.5),
        EyeConfig(eye_id=3, x= 0.1, y=0.0, z=0.5),
        EyeConfig(eye_id=4, x= 0.2, y=0.0, z=0.5),
        EyeConfig(eye_id=5, x= 0.3, y=0.0, z=0.5),
    ]

    manager = EyeManager(eye_configs=configs)

    def print_states(label: str, states: EyeStates) -> None:
        print(f"\n{'='*50}")
        print(f"  {label}")
        print(f"{'='*50}")
        for gid, state in sorted(states.items()):
            c = state.color
            print(
                f"  Gimbal {gid}: "
                f"rgb=({c.red:3d},{c.green:3d},{c.blue:3d})  "
                f"radius={state.radius:.1f}  "
                f"rotation={state.rotation:.1f}°  "
                f"eye_lid={state.eye_lid:.2f}  "
                f"cat_eye={state.is_cat_eye}"
            )

    # --- Scene 1: all gimbals unassigned ---
    assignments: EyeAssignments = {gid: [] for gid in range(6)}
    states = manager.update(assignments)
    print_states("All unassigned — expect grey", states)

    # --- Scene 2: face 0 assigned to gimbals 0, 1, 2 ---
    assignments = {0: [0], 1: [0], 2: [0], 3: [], 4: [], 5: []}
    states = manager.update(assignments)
    print_states("Face 0 → gimbals 0,1,2 (same random color); rest grey", states)

    # --- Scene 3: face 1 appears on gimbals 3, 4 ---
    assignments = {0: [0], 1: [0], 2: [0], 3: [1], 4: [1], 5: []}
    states = manager.update(assignments)
    print_states("Face 0 → gimbals 0,1,2; Face 1 → gimbals 3,4; Gimbal 5 grey", states)

    # --- Scene 4: all six faces, one gimbal each ---
    assignments = {i: [i] for i in range(6)}
    states = manager.update(assignments)
    print_states("Six faces 1-to-1 — each a unique random color", states)

    # --- Scene 5: test setter helpers ---
    manager.set_radius(0, 2.5)
    manager.set_rotation(0, 45.0)
    manager.set_eye_lid(1, 0.75)
    manager.set_cat_eye(2, True)
    states = manager.update(assignments)
    print_states("Gimbal 0: radius=2.5, rotation=45°  |  Gimbal 1: eye_lid=0.75  |  Gimbal 2: cat_eye=True", states)