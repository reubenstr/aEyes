from dataclasses import dataclass
from enum import Enum, auto


class MessageType(Enum):
    INFO = auto()
    ERROR = auto()


@dataclass
class ControlMessage:
    radius: float
    rotation_deg: float
    eye_lid_position: float
    iris_color: tuple[float, float, float]
    cornea_color: tuple[float, float, float]
    is_cat_eye: bool
    yaw: float      # degrees
    pitch: float    # degrees
