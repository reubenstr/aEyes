from data_types import CameraConfig, EyeConfig, Position3D

"""
    Describes the physical system.

    Looking at the system, the first eye is middle left, next eyes are clockwise.

    X: Forward/Backward (+/-)
    Y: Right/Left (+/-)
    Z: Up/Down (+/-)

    Units: meters  
"""

#Pitch joint extends out from the yaw joint.
PITCH_PIVOT_OFFSET = Position3D(x=0.1035, y=0.0, z=0.0)

EYE_CONFIGS = [
    EyeConfig(eye_id=1, position=Position3D(x= 0.0275, y= -0.360,  z= 0.0),     pitch_pivot_offset=PITCH_PIVOT_OFFSET),
    EyeConfig(eye_id=2, position=Position3D(x= 0.0275, y= -0.180,  z= 0.31177), pitch_pivot_offset=PITCH_PIVOT_OFFSET),
    EyeConfig(eye_id=3, position=Position3D(x= 0.0275, y=  0.180,  z= 0.31177), pitch_pivot_offset=PITCH_PIVOT_OFFSET),
    EyeConfig(eye_id=4, position=Position3D(x= 0.0275, y=  0.360,  z= 0.0),     pitch_pivot_offset=PITCH_PIVOT_OFFSET),
    EyeConfig(eye_id=5, position=Position3D(x= 0.0275, y=  0.180,  z=-0.31177), pitch_pivot_offset=PITCH_PIVOT_OFFSET),
    EyeConfig(eye_id=6, position=Position3D(x= 0.0275, y= -0.180,  z=-0.31177), pitch_pivot_offset=PITCH_PIVOT_OFFSET),
]

# Oak-D W (wide) depth camera
# https://shop.luxonis.com/products/oak-d-w?Central+RGB+Camera=OV9782
# FOV units: degrees
RGB_CAMERA_OFFSET = 0.0
CAMERA_CONFIG = CameraConfig(x=0.04375, y=RGB_CAMERA_OFFSET, z=0.0, horizontal_fov=127.0, vertical_fov=79.5)