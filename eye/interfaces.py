from dataclasses import dataclass

@dataclass
class ControlMessage:
    radius: float
    rotation_deg: float
    blink: float 
    pupil_size: float 
    iris_color: tuple[float, float, float]
    cornea_color: tuple[float, float, float] 
    is_cat_eye: bool