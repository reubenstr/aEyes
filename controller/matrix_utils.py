import numpy as np

def R_x(roll_rad: float) -> np.ndarray:
    c, s = np.cos(roll_rad), np.sin(roll_rad)
    return np.array([
        [1, 0,  0],
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


def T_from_R_t(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Build a 4x4 homogeneous transform. Maps p_child -> p_parent."""
    T = np.eye(4, dtype=float)
    T[0:3, 0:3] = R
    T[0:3, 3] = t.reshape(3)
    return T


def T_inverse(T: np.ndarray) -> np.ndarray:
    """Invert a homogeneous transform without full matrix inversion."""
    R = T[0:3, 0:3]
    t = T[0:3, 3]
    T_inv = np.eye(4, dtype=float)
    T_inv[0:3, 0:3] = R.T
    T_inv[0:3, 3] = -R.T @ t
    return T_inv


def to_homogeneous(p: np.ndarray) -> np.ndarray:
    return np.array([p[0], p[1], p[2], 1.0], dtype=float)


def from_homogeneous(p: np.ndarray) -> np.ndarray:
    return p[0:3] / p[3]