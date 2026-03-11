import numpy as np

from data_types import Position3D


class KalmanFilter3D:
    """
    Constant-velocity Kalman filter in 3D.

    State vector: [x, y, z, vx, vy, vz]
    Observation:  [x, y, z]
    """

    def __init__(self, position: Position3D):
        self.state = np.array(
            [position.x, position.y, position.z, 0.0, 0.0, 0.0], dtype=float
        )

        # State transition matrix (constant velocity)
        self.F = np.eye(6)
        self.F[0, 3] = 1.0
        self.F[1, 4] = 1.0
        self.F[2, 5] = 1.0

        # Observation matrix (we only observe position)
        self.H = np.zeros((3, 6))
        self.H[0, 0] = 1.0
        self.H[1, 1] = 1.0
        self.H[2, 2] = 1.0

        # Covariance matrix
        self.P = np.eye(6) * 1.0

        # Process noise (tune for how dynamic faces move)
        q = 0.1
        self.Q = np.eye(6) * q

        # Anisotropic measurement noise: Z (depth) is noisier on OAK-D than X/Y.
        # Higher R[2,2] tells the filter to trust depth readings less and rely
        # more on its own prediction — keeps tracks stable during noisy depth
        # frames and makes re-linking after a brief miss much more reliable.
        r_xy = 0.05   # spatial noise (metres) — tune to your camera
        r_z  = 0.20   # depth noise — increase if Z readings are very jittery
        self.R = np.diag([r_xy, r_xy, r_z])

    def predict(self) -> Position3D:
        """Predict next state. Returns predicted position."""
        self.state = self.F @ self.state
        self.P = self.F @ self.P @ self.F.T + self.Q
        return Position3D(self.state[0], self.state[1], self.state[2])

    def update(self, measurement: Position3D):
        """Update with observed position."""
        z = np.array([measurement.x, measurement.y, measurement.z]) - self.H @ self.state
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.state = self.state + K @ z
        self.P = (np.eye(6) - K @ self.H) @ self.P

    @property
    def position(self) -> Position3D:
        return Position3D(self.state[0], self.state[1], self.state[2])

    @property
    def velocity(self) -> np.ndarray:
        return self.state[3:].copy()