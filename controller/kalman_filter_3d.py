"""Constant-velocity filtering in project axes, with velocities in meters/second."""

import math
import numpy as np

from data_types import Position3D
from parameters import params as _params


class KalmanFilter3D:
    def __init__(self, position: Position3D):
        self.state = np.array([position.x, position.y, position.z, 0., 0., 0.])
        self.F = np.eye(6)
        self.H = np.eye(3, 6)
        self.P = np.eye(6)
        self.Q = np.zeros((6, 6))
        # Depth is project X. Configuration values are standard deviations [m].
        p = _params.kalman
        self.R = np.diag([p.measurement_std_depth ** 2,
                          p.measurement_std_lateral ** 2,
                          p.measurement_std_lateral ** 2])

    def predict(self, dt: float | None = None) -> Position3D:
        if dt is None:
            dt = 1.0 / _params.system.refresh_rate_hz
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("Prediction dt must be finite and nonnegative")
        self.F = np.eye(6)
        self.F[:3, 3:] = np.eye(3) * dt
        # Integrated white acceleration: covariance composes over irregular steps.
        q = _params.kalman.acceleration_noise
        self.Q = q * np.block([[np.eye(3) * dt ** 3 / 3, np.eye(3) * dt ** 2 / 2],
                               [np.eye(3) * dt ** 2 / 2, np.eye(3) * dt]])
        self.state = self.F @ self.state
        self.P = self.F @ self.P @ self.F.T + self.Q
        return self.position

    def measurement_covariance(self, trust: float = 1.0) -> np.ndarray:
        return self.R / max(0.1, min(1.0, trust))

    def innovation(self, measurement: Position3D, trust: float = 1.0):
        residual = np.array([measurement.x, measurement.y, measurement.z]) - self.state[:3]
        covariance = self.P[:3, :3] + self.measurement_covariance(trust)
        return residual, covariance

    def distance_squared(self, measurement: Position3D, trust: float = 1.0) -> float:
        residual, covariance = self.innovation(measurement, trust)
        return float(residual @ np.linalg.solve(covariance, residual))

    def update(self, measurement: Position3D, trust: float = 1.0):
        residual, covariance = self.innovation(measurement, trust)
        gain = np.linalg.solve(covariance, self.P[:3, :]).T
        self.state += gain @ residual
        # Joseph form preserves symmetry/positive semidefiniteness under rounding.
        remainder = np.eye(6) - gain @ self.H
        self.P = (remainder @ self.P @ remainder.T
                  + gain @ self.measurement_covariance(trust) @ gain.T)
        self.P = (self.P + self.P.T) / 2

    @property
    def position(self) -> Position3D:
        return Position3D(*self.state[:3])

    @property
    def velocity(self) -> np.ndarray:
        return self.state[3:].copy()
