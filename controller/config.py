from data_types import CameraConfig, EyeConfig, Position3D

"""

    Describes physical system.

"""
#Pitch joint extends out from the yaw joint.
PITCH_PIVOT_OFFSET = Position3D(x=0.080, y=0.0, z=0.0)

# Prototype version does not fully match CAD assembly, y pos is widened by 5mm.
EYE_CONFIGS = [
    EyeConfig(eye_id=1, position=Position3D(x= 0.0275, y= -0.405,  z= 0.0),   pitch_pivot_offset=PITCH_PIVOT_OFFSET),
    EyeConfig(eye_id=2, position=Position3D(x= 0.0275, y= -0.205,  z= 0.34641), pitch_pivot_offset=PITCH_PIVOT_OFFSET),
    EyeConfig(eye_id=3, position=Position3D(x= 0.0275, y=  0.205,  z= 0.34641), pitch_pivot_offset=PITCH_PIVOT_OFFSET),
    EyeConfig(eye_id=4, position=Position3D(x= 0.0275, y=  0.405,  z= 0.0),   pitch_pivot_offset=PITCH_PIVOT_OFFSET),
    EyeConfig(eye_id=5, position=Position3D(x= 0.0275, y=  0.205,  z=-0.34641), pitch_pivot_offset=PITCH_PIVOT_OFFSET),
    EyeConfig(eye_id=6, position=Position3D(x= 0.0275, y= -0.205,  z=-0.34641), pitch_pivot_offset=PITCH_PIVOT_OFFSET),
]

RGB_CAMERA_OFFSET = 0.030
CAMERA_CONFIG = CameraConfig(x=0.0, y=RGB_CAMERA_OFFSET, z=0.0, horizontal_fov=87.0, vertical_fov=58.0)