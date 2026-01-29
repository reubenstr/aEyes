from dataclasses import dataclass


@dataclass
class ControlMessage:
    radius: float
    rotation_deg: float
    eye_lid_position: float 
    iris_color: tuple[float, float, float]
    cornea_color: tuple[float, float, float] 
    is_cat_eye: bool
    motor_enable: bool
    position_0: float
    position_1: float