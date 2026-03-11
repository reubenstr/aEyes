from dataclasses import dataclass, field
from typing import Any

EyeId = int
FaceId = int

@dataclass
class Color:
    red: int = 0    # 0 - 255
    green: int = 0  # 0 - 255
    blue: int = 0   # 0 - 255

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

TrackedFaces = dict[FaceId, Position3D]
EyeAssignments = dict[EyeId, FaceId | None]

@dataclass
class EyeState:
    """Render state for a single eye."""
    eye_id: EyeId
    iris_color: Color = field(default_factory=lambda: Color(128, 128, 128))          # current (lerped) color
    target_iris_color: Color = field(default_factory=lambda: Color(128, 128, 128))   # target to lerp toward
    striation_color: Color = field(default_factory=lambda: Color(128, 128, 128))     # current (lerped) color
    target_striation_color: Color = field(default_factory=lambda: Color(128, 128, 128))  # target to lerp toward
    face_id: FaceId | None = None  # currently assigned face
    radius: float = 1.0
    rotation: float = 0.0   # degrees
    eye_lid: float = 1.0    # 0.0 = fully closed, 1.0 = fully open
    is_cat_eye: bool = False
    yaw: float = 0.0        # degrees
    pitch: float = 0.0      # degrees


EyeStates = dict[EyeId, EyeState]   

@dataclass
class Detection:
    """A single face detection from the camera, with optional embedding for re-ID."""
    position: Position3D
    embedding: Any | None = None  # numpy ndarray in practice