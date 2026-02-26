import numpy as np

# Rotation matrices:
def R_x(roll_rad: float) -> np.ndarray:
    c, s = np.cos(roll_rad), np.sin(roll_rad)
    return np.array([
        [1, 0, 0],
        [0, c, -s],
        [0, s,  c]
    ], dtype=float)

def R_y(pitch_rad: float) -> np.ndarray:
    c, s = np.cos(pitch_rad), np.sin(pitch_rad)
    return np.array([
        [ c, 0, s],
        [ 0, 1, 0],
        [-s, 0, c]
    ], dtype=float)

def R_z(yaw_rad: float) -> np.ndarray:
    c, s = np.cos(yaw_rad), np.sin(yaw_rad)
    return np.array([
        [c, -s, 0],
        [s,  c, 0],
        [0,  0, 1]
    ], dtype=float)


def R_from_rpy(roll_rad: float, pitch_rad: float, yaw_rad: float) -> np.ndarray:
    # ZYX convention
    return R_z(yaw_rad) @ R_y(pitch_rad) @ R_x(roll_rad)


# Homogeneous transforms:
def T_from_R_t(R_parent_child: np.ndarray,
               t_parent_child_m: np.ndarray) -> np.ndarray:
    """
    T_parent_child maps p_child -> p_parent
    """
    T_parent_child = np.eye(4, dtype=float)
    T_parent_child[0:3, 0:3] = R_parent_child
    T_parent_child[0:3, 3] = t_parent_child_m.reshape(3)
    return T_parent_child


def T_inverse(T_parent_child: np.ndarray) -> np.ndarray:
    """
    Returns T_child_parent
    """
    R_parent_child = T_parent_child[0:3, 0:3]
    t_parent_child = T_parent_child[0:3, 3]

    T_child_parent = np.eye(4, dtype=float)
    T_child_parent[0:3, 0:3] = R_parent_child.T
    T_child_parent[0:3, 3] = -R_parent_child.T @ t_parent_child
    return T_child_parent

def p_to_homogeneous(p_xyz: np.ndarray) -> np.ndarray:
    return np.array([p_xyz[0], p_xyz[1], p_xyz[2], 1.0], dtype=float)


def p_from_homogeneous(p_xyzw: np.ndarray) -> np.ndarray:
    return p_xyzw[0:3] / p_xyzw[3]



    '''
        System coordinates:
            +X → Forward
            +Y → Left
            +Z → Up
            +Yaw → Rotate CCW
            +Pitch → Rotate up
    '''

class Conversions:
    def __init__(self):

        # System frame: X+ forward, Y+ left, Z+ up 

        # Camera mount relative to base (meters)
        t_base_camera_m = np.array([0.0, 0.0, 0.180]) 
        rpy_base_camera_rad = np.deg2rad([0.0, 0.0, 0.0])

        # Gimbal mount relative to base (meters)
        t_base_gimbal_m = np.array([0.50, -0.203, 0.0]) 
        rpy_base_gimbal_rad = np.deg2rad([0.0, 0.0, 0.0])

        R_base_camera = R_from_rpy(*rpy_base_camera_rad)
        R_base_gimbal = R_from_rpy(*rpy_base_gimbal_rad)

        self.T_base_camera = T_from_R_t(R_base_camera, t_base_camera_m)
        self.T_base_gimbal = T_from_R_t(R_base_gimbal, t_base_gimbal_m)


    def realsense_point_to_system(self, p_realsense_m: np.ndarray):   
        # RealSense point (meters)
        # p_realsense_m = np.array([0.0, 0.0, 1.0], dtype=float)

        # Convert RealSense optical frame
        # (X right, Y down, Z forward)
        # to system frame
        # (X forward, Y left, Z up)
        p_camera_m = np.array([
            p_realsense_m[2],        # X_system =  Z_rs
            -p_realsense_m[0],       # Y_system = -X_rs
            -p_realsense_m[1]        # Z_system = -Y_rs
        ], dtype=float)

        # camera -> base
        p_base_m = p_from_homogeneous(
            self.T_base_camera @ p_to_homogeneous(p_camera_m)
        )

        # base -> gimbal
        T_gimbal_base = T_inverse(self.T_base_gimbal)

        p_gimbal_m = p_from_homogeneous(
            T_gimbal_base @ p_to_homogeneous(p_base_m)
        )

        # point gimbal to realsense point
        x, y, z = p_gimbal_m
        yaw_deg = np.degrees(np.arctan2(y, x))
        pitch_deg = np.degrees(np.arctan2(z, np.hypot(x, y)))
       

        if False:
        

            np.set_printoptions(precision=6, suppress=True)
            #print("T_base_camera:\n", self.T_base_camera)
            #print("\nT_base_gimbal:\n", self.T_base_gimbal)

            print("\np_realsense_m:", p_realsense_m)
            print("p_camera_m:", p_camera_m)
            print("p_base_m:  ", p_base_m)
            print("p_gimbal_m:", p_gimbal_m)

            print("yaw_deg:  ", yaw_deg)
            print("pitch_deg:", pitch_deg)

        return yaw_deg, pitch_deg
