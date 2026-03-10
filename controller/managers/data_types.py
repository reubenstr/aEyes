from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass
class Detection:
    """A single face detection from the camera, with optional embedding for re-ID."""
    position: Position3D
    embedding: Optional[Any] = None  # numpy ndarray in practice

EyeId = int
FaceId = int

@dataclass
class Color:
    red:   int = 0  # 0 - 255
    green: int = 0  # 0 - 255
    blue:  int = 0  # 0 - 255

@dataclass(frozen=True)
class Position3D:
    """A 3-D position relative to the camera centre."""
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class EyeConfig:
    """Static configuration for a single gimbal."""
    eye_id: EyeId
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class EyeAssignmentState:
    """Runtime state for a single gimbal."""
    eye_id: EyeId
   
    # Which face this gimbal is currently tracking (None = unassigned)
    assigned_face_id: Optional[FaceId] = None

    # Timestamp when this gimbal became unassigned and entered the available pool
    # (None means it is currently assigned)
    available_since: Optional[float] = None


EyeAssignments = dict[EyeId, list[FaceId]]
TrackedFaces = dict[FaceId, Position3D]

@dataclass
class EyeState:
    """Render state for a single gimbal eye."""
    eye_id:      EyeId
    color:       Color = field(default_factory=lambda: Color(128, 128, 128))  # current (lerped) color
    target_color: Color = field(default_factory=lambda: Color(128, 128, 128))  # target to lerp toward
    face_ids:    list[FaceId] = field(default_factory=list)  # currently assigned faces
    radius:      float = 1.0
    rotation:    float = 0.0   # degrees
    eye_lid:     float = 0.0   # 0.0 = fully open, 1.0 = fully closed
    is_cat_eye:  bool  = False


# Return type for EyeManager.update()
EyeStates = dict[EyeId, EyeState]   