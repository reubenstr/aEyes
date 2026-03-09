from dataclasses import dataclass
from typing import Any, Optional

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
class Detection:
    """A single face detection from the camera, with optional embedding for re-ID."""
    position: Position3D
    embedding: Optional[Any] = None  # numpy ndarray in practice