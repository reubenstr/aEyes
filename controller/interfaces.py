from dataclasses import dataclass
from typing import Tuple

@dataclass
class ControlMessage:
    radius: float
    rotation_deg: float
    eye_lid_position: float
    iris_color: Tuple[float, float, float]
    cornea_color: Tuple[float, float, float]
    is_cat_eye: bool
    yaw: float
    pitch: float