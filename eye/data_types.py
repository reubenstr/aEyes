from dataclasses import dataclass


@dataclass
class ControlMessage:
    radius: float
    rotation_deg: float
    eye_lid_position: float
    iris_color: tuple[int, int, int]
    cornea_color: tuple[int, int, int]
    is_cat_eye: bool
    yaw: float      # degrees
    pitch: float    # degrees
