import numpy as np

from data_types import EyeId, EyeConfig, CameraConfig, Position3D
from matrix_utils import R_from_rpy, T_from_R_t, T_inverse, to_homogeneous, from_homogeneous

# System coordinates:
#   +X → Forward
#   +Y → Left
#   +Z → Up
#   +Yaw  → Rotate CCW
#   +Pitch → Rotate up

class Conversions:
    def __init__(self, eye_configs: list[EyeConfig], camera_config: CameraConfig):

        # Camera mount relative to base (meters)
        t_base_camera = np.array([camera_config.x, camera_config.y, camera_config.z])

        R_base_camera = R_from_rpy(*np.deg2rad([0.0, 0.0, 0.0]))

        self.T_base_camera = T_from_R_t(R_base_camera, t_base_camera)

        # Offset from yaw pivot to pitch pivot along the gimbal arm (meters)
        # TODO: set physical offset
        self.t_yaw_to_pitch = np.array([0.0, 0.0, 0.0]) # np.array([0.106, 0.0, 0.0])

        # Precompute per-eye gimbal transforms from EyeConfig positions
        self.T_base_gimbal: dict[EyeId, np.ndarray] = {
            cfg.eye_id: T_from_R_t(R_from_rpy(0.0, 0.0, 0.0), np.array([cfg.x, cfg.y, cfg.z]))
            for cfg in eye_configs
        }

    def get_pitch_yaw(self, eye_id: EyeId, position: Position3D) -> tuple[float, float]:
        # Position is assumed to already be in the system frame
        # (X+ forward, Y+ left, Z+ up)
        p_camera = np.array([position.x, position.y, position.z], dtype=float)

        # Camera frame -> base frame
        p_base = from_homogeneous(self.T_base_camera @ to_homogeneous(p_camera))

        # Base frame -> yaw pivot frame
        T_gimbal_base = T_inverse(self.T_base_gimbal[eye_id])
        p_yaw = from_homogeneous(T_gimbal_base @ to_homogeneous(p_base))

        # Yaw: angle from gimbal origin to target in the base XY plane
        x_base, y_base, _ = p_base
        gimbal_y = self.T_base_gimbal[eye_id][1, 3]
        yaw_deg = np.degrees(np.arctan2(y_base - gimbal_y, x_base))

        # Pitch: rotate into yaw-aligned frame, offset to pitch pivot, then arctan
        R_yaw = R_from_rpy(0.0, 0.0, np.radians(yaw_deg))
        p_yaw_aligned = R_yaw.T @ p_yaw
        p_pitch = p_yaw_aligned - self.t_yaw_to_pitch
        px, py, pz = p_pitch
        pitch_deg = np.degrees(np.arctan2(pz, np.hypot(px, py)))

        return yaw_deg, pitch_deg
