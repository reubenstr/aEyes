from data_types import CameraConfig, EyeConfig, Position3D

"""

    Describes physical system.

"""

_PITCH_PIVOT_OFFSET = Position3D(x=0.080, y=0.0, z=0.0)

EYE_CONFIGS = [
    EyeConfig(eye_id=1, position=Position3D(x= 0.0, y= 0.4,  z= 0.0),   pitch_pivot_offset=_PITCH_PIVOT_OFFSET),
    EyeConfig(eye_id=2, position=Position3D(x= 0.0, y= 0.2,  z= 0.346), pitch_pivot_offset=_PITCH_PIVOT_OFFSET),
    EyeConfig(eye_id=3, position=Position3D(x= 0.0, y=-0.2,  z= 0.346), pitch_pivot_offset=_PITCH_PIVOT_OFFSET),
    EyeConfig(eye_id=4, position=Position3D(x= 0.0, y=-0.4,  z= 0.0),   pitch_pivot_offset=_PITCH_PIVOT_OFFSET),
    EyeConfig(eye_id=5, position=Position3D(x= 0.0, y=-0.2,  z=-0.346), pitch_pivot_offset=_PITCH_PIVOT_OFFSET),
    EyeConfig(eye_id=6, position=Position3D(x= 0.0, y= 0.2,  z=-0.346), pitch_pivot_offset=_PITCH_PIVOT_OFFSET),
]

CAMERA_CONFIG = CameraConfig(x=0.0, y=0.0, z=0.0, horizontal_fov=87.0, vertical_fov=58.0)