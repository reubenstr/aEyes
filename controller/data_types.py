from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

EyeId = int
FaceId = int

@dataclass
class Color:
    red: int = 0    # 0 - 255
    green: int = 0  # 0 - 255
    blue: int = 0   # 0 - 255

    def as_rgb(self) -> tuple[int, int, int]:
        return self.red, self.green, self.blue

@dataclass(frozen=True)
class Position3D:
    """A 3-D position relative to the camera centre."""
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class CameraConfig:
    """Camera mount position relative to the system base (meters)."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    horizontal_fov: float = 0.0   # degrees
    vertical_fov: float = 0.0     # degrees


@dataclass(frozen=True)
class EyeConfig:
    """Static configuration for a single eye."""
    eye_id: EyeId
    position: Position3D = field(default_factory=lambda: Position3D(0.0, 0.0, 0.0))
    pitch_pivot_offset: Position3D = field(default_factory=lambda: Position3D(0.0, 0.0, 0.0))


@dataclass
class EyeAssignmentState:
    """Runtime state for a single eye."""
    eye_id: EyeId

    # Which face this eye is currently tracking (None = unassigned)
    assigned_face_id: FaceId | None = None

    # Timestamp when this eye became unassigned and entered the available pool
    # (None means it is currently assigned)
    available_since: float | None = None

@dataclass(frozen=True)
class TrackedFace:
    position: Position3D
    is_static: bool = False

TrackedFaces = Dict[FaceId, TrackedFace]
EyeAssignments = Dict[EyeId, Optional[FaceId]]

@dataclass
class EyeState:
    """Render state for a single eye."""
    eye_id: EyeId
    iris_color: Color = field(default_factory=lambda: Color(128, 128, 128))          # current (lerped) color
    target_iris_color: Color = field(default_factory=lambda: Color(128, 128, 128))   # target to lerp toward
    iris_accent_color: Color = field(default_factory=lambda: Color(128, 128, 128))
    target_iris_accent_color: Color = field(default_factory=lambda: Color(128, 128, 128))
    iris_center_color: Color = field(default_factory=lambda: Color(128, 128, 128))
    target_iris_center_color: Color = field(default_factory=lambda: Color(128, 128, 128))
    striation_color: Color = field(default_factory=Color)
    target_striation_color: Color = field(default_factory=Color)
    pupil_color: Color = field(default_factory=Color)
    sclera_color: Color = field(default_factory=lambda: Color(214, 207, 199))
    vein_color: Color = field(default_factory=lambda: Color(184, 23, 23))
    face_id: FaceId | None = None  # currently assigned face
    radius: float = 1.0     # outer eye radius in shader coordinates
    iris_size: float = 0.5
    pupil_size: float = 0.5
    curvature: float = 0.2
    vein_count: int = 8
    vein_seed: int = 1
    rotation: float = 0.0   # degrees
    eye_lid: float = 0.85   # final openness after applying blink
    resting_eye_lid: float = 0.85
    is_cat_eye: bool = False
    yaw: float = 0.0        # degrees
    pitch: float = 0.0      # degrees


EyeStates = Dict[EyeId, EyeState]

@dataclass
class ControlMessage:
    radius: float
    rotation_deg: float
    eye_lid_position: float
    iris_color: tuple[int, int, int]
    striation_color: tuple[int, int, int]
    is_cat_eye: bool
    yaw: float
    pitch: float
    iris_accent_color: tuple[int, int, int]
    iris_center_color: tuple[int, int, int]
    pupil_color: tuple[int, int, int]
    sclera_color: tuple[int, int, int]
    vein_color: tuple[int, int, int]
    iris_size: float
    pupil_size: float
    curvature: float
    vein_count: int
    vein_seed: int

    @classmethod
    def from_state(cls, state: EyeState) -> ControlMessage:
        return cls(
            radius=state.radius,
            rotation_deg=state.rotation,
            eye_lid_position=state.eye_lid,
            iris_color=state.iris_color.as_rgb(),
            striation_color=state.striation_color.as_rgb(),
            is_cat_eye=state.is_cat_eye,
            yaw=state.yaw,
            pitch=state.pitch,
            iris_accent_color=state.iris_accent_color.as_rgb(),
            iris_center_color=state.iris_center_color.as_rgb(),
            pupil_color=state.pupil_color.as_rgb(),
            sclera_color=state.sclera_color.as_rgb(),
            vein_color=state.vein_color.as_rgb(),
            iris_size=state.iris_size,
            pupil_size=state.pupil_size,
            curvature=state.curvature,
            vein_count=state.vein_count,
            vein_seed=state.vein_seed,
        )


@dataclass
class Detection:
    """Project-frame XYZ and/or a normalized image box from one camera frame."""
    position: Position3D | None
    embedding: Any | None = None  # numpy ndarray in practice
    bbox: tuple[float, float, float, float] | None = None  # xmin, ymin, xmax, ymax
    confidence: float = 1.0
    depth_quality: float = 1.0  # 0 = unavailable; otherwise relative measurement trust
