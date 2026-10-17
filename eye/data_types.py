from dataclasses import dataclass


@dataclass
class ControlMessage:
    radius: float  # outer eye radius in shader coordinates
    rotation_deg: float
    eye_lid_position: float
    iris_color: tuple[int, int, int]
    striation_color: tuple[int, int, int]
    is_cat_eye: bool
    yaw: float      # degrees
    pitch: float    # degrees
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
