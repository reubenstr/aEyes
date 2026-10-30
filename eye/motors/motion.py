"""Bounded quintic tracking trajectories, independent of CAN and rendering.

Retargeting starts at the current position, velocity and acceleration. Polynomial
extrema are checked over the complete candidate trajectory, including braking
excursions after a reversal. If a new goal cannot yet be reached within the joint
and derivative limits, finish the previous feasible trajectory before replanning.
"""

from dataclasses import dataclass
import math

from .data_types import MotionLimits


def _value(coefficients, t):
    result = 0.0
    for coefficient in reversed(coefficients):
        result = result * t + coefficient
    return result


def _derivative(coefficients):
    return [index * value for index, value in enumerate(coefficients)][1:]


def _roots(coefficients):
    """Real polynomial roots in [0, 1], isolated between derivative roots."""
    coefficients = list(coefficients)
    while len(coefficients) > 1 and abs(coefficients[-1]) < 1e-12:
        coefficients.pop()
    if len(coefficients) <= 1:
        return []
    if len(coefficients) == 2:
        root = -coefficients[0] / coefficients[1]
        return [root] if 0.0 <= root <= 1.0 else []
    points = [0.0, *_roots(_derivative(coefficients)), 1.0]
    tolerance = 1e-12 * max(1.0, sum(abs(value) for value in coefficients))
    roots = [point for point in points if abs(_value(coefficients, point)) <= tolerance]
    for left, right in zip(points, points[1:]):
        left_value = _value(coefficients, left)
        if left_value * _value(coefficients, right) >= 0:
            continue
        for _ in range(40):
            middle = (left + right) / 2.0
            if left_value * _value(coefficients, middle) <= 0:
                right = middle
            else:
                left, left_value = middle, _value(coefficients, middle)
        roots.append((left + right) / 2.0)
    return sorted(set(roots))


@dataclass(frozen=True)
class MotionState:
    position: float
    velocity: float = 0.0
    acceleration: float = 0.0


class _Trajectory:
    def __init__(self, start, target, duration):
        self.target = target
        self.duration = duration
        distance = target - start.position
        velocity = start.velocity * duration
        acceleration = start.acceleration * duration**2
        self.derivatives = [[
            start.position, velocity, acceleration / 2.0,
            10.0 * distance - 6.0 * velocity - 1.5 * acceleration,
            -15.0 * distance + 8.0 * velocity + 1.5 * acceleration,
            6.0 * distance - 3.0 * velocity - 0.5 * acceleration,
        ]]
        for _ in range(3):
            self.derivatives.append(_derivative(self.derivatives[-1]))

    def sample(self, elapsed):
        if elapsed >= self.duration:
            return MotionState(self.target)
        t = elapsed / self.duration
        return MotionState(*(_value(coefficients, t) / self.duration**order
                             for order, coefficients in enumerate(self.derivatives[:3])))

    def fits(self, minimum, maximum, limits):
        bounds = ((minimum, maximum),
                  (-limits.max_speed_deg_s, limits.max_speed_deg_s),
                  (-limits.max_acceleration_deg_s2, limits.max_acceleration_deg_s2),
                  (-limits.max_jerk_deg_s3, limits.max_jerk_deg_s3))
        for order, (coefficients, (low, high)) in enumerate(zip(self.derivatives, bounds)):
            for t in (0.0, 1.0, *_roots(_derivative(coefficients))):
                value = _value(coefficients, t) / self.duration**order
                if not low - 1e-9 <= value <= high + 1e-9:
                    return False
        return True


class MotionProfile:
    def __init__(self, minimum: float, maximum: float, limits: MotionLimits):
        if not all(math.isfinite(value) for value in (minimum, maximum)) or minimum >= maximum:
            raise ValueError("Motion position limits must be finite and increasing")
        self.minimum, self.maximum, self.limits = minimum, maximum, limits
        self.reset(max(minimum, min(maximum, 0.0)))

    def reset(self, position: float):
        """Reseed at rest after initialization or a feedback/network/timing fault.

        Fault holds and reseeding override normal trajectory continuity; normal
        retargeting must use advance() so velocity/acceleration are preserved.
        """
        if not math.isfinite(position) or not self.minimum <= position <= self.maximum:
            raise ValueError("Motion reset position must be finite and within joint limits")
        self.state = MotionState(position)
        self._trajectory = None
        self._elapsed = 0.0
        self._requested_target = position

    def _plan(self, target):
        distance = abs(target - self.state.position)
        limits = self.limits
        # Exact peak factors for a rest-to-rest quintic; retargets may need longer.
        duration = max(0.05, 1.875 * distance / limits.max_speed_deg_s,
                       math.sqrt(5.774 * distance / limits.max_acceleration_deg_s2),
                       (60.0 * distance / limits.max_jerk_deg_s3)**(1.0 / 3.0),
                       abs(self.state.velocity) / limits.max_acceleration_deg_s2,
                       abs(self.state.acceleration) / limits.max_jerk_deg_s3)
        for _ in range(40):
            trajectory = _Trajectory(self.state, target, duration)
            if trajectory.fits(self.minimum, self.maximum, limits):
                self._trajectory = trajectory
                self._elapsed = 0.0
                return
            duration *= 1.1
        # The previous plan is still feasible. Do not clip velocity/acceleration
        # or jump to a new goal if it is suddenly inside the stopping distance.

    def advance(self, target: float, dt: float) -> MotionState:
        if not all(math.isfinite(value) for value in (target, dt)) or dt < 0:
            raise ValueError("Motion target/time must be finite and time nonnegative")
        target = max(self.minimum, min(self.maximum, target))
        if target != self._requested_target or self._trajectory is None:
            self._requested_target = target
            if target != self.state.position or self.state.velocity or self.state.acceleration:
                self._plan(target)
            else:
                self._trajectory = None
        if self._trajectory is not None:
            self._elapsed += dt
            self.state = self._trajectory.sample(self._elapsed)
            if self._elapsed >= self._trajectory.duration:
                self._trajectory = None
        return self.state
