"""Speed- and acceleration-limited tracking, independent of CAN and rendering.

Each new goal replaces the previous goal immediately. Constant-acceleration
segments take the shortest route allowed by the configured speed/acceleration
limits, braking first when a reversal or a closer goal requires it.
"""

from dataclasses import dataclass
import math

from .data_types import MotionLimits


@dataclass(frozen=True)
class MotionState:
    position: float
    velocity: float = 0.0
    acceleration: float = 0.0


class MotionProfile:
    def __init__(self, minimum: float, maximum: float, limits: MotionLimits):
        if not all(math.isfinite(value) for value in (minimum, maximum)) or minimum >= maximum:
            raise ValueError("Motion position limits must be finite and increasing")
        self.minimum, self.maximum, self.limits = minimum, maximum, limits
        self.reset(max(minimum, min(maximum, 0.0)))

    def reset(self, position: float):
        """Start at rest after initialization or a feedback/network/timing fault."""
        if not math.isfinite(position) or not self.minimum <= position <= self.maximum:
            raise ValueError("Motion reset position must be finite and within joint limits")
        self.state = MotionState(position)
        self._segments = []
        self._target = position

    def _plan(self, target):
        self._target = target
        self._segments = []
        position, velocity = self.state.position, self.state.velocity
        acceleration = self.limits.max_acceleration_deg_s2
        speed = self.limits.max_speed_deg_s
        direction = 1.0 if target >= position else -1.0
        distance = abs(target - position)
        forward_speed = velocity * direction

        # Brake to rest first if moving away, or unable to stop before the goal.
        # A close retarget may be overshot while braking; joint bounds still apply
        # because every preceding plan could stop within the configured range.
        if forward_speed < 0.0 or forward_speed**2 / (2.0 * acceleration) > distance:
            duration = abs(velocity) / acceleration
            braking = -math.copysign(acceleration, velocity)
            self._segments.append((duration, braking))
            position += velocity * duration + 0.5 * braking * duration**2
            direction = 1.0 if target >= position else -1.0
            distance = abs(target - position)
            forward_speed = 0.0

        peak_speed = min(speed, math.sqrt(acceleration * distance + forward_speed**2 / 2.0))
        accelerating = max(0.0, (peak_speed - forward_speed) / acceleration)
        braking = peak_speed / acceleration
        cruise_distance = (distance - (peak_speed**2 - forward_speed**2) / (2.0 * acceleration)
                           - peak_speed**2 / (2.0 * acceleration))
        cruising = max(0.0, cruise_distance / peak_speed) if peak_speed else 0.0
        for duration, value in ((accelerating, direction * acceleration),
                                (cruising, 0.0), (braking, -direction * acceleration)):
            if duration > 0.0:
                self._segments.append((duration, value))

    def advance(self, target: float, dt: float) -> MotionState:
        if not all(math.isfinite(value) for value in (target, dt)) or dt < 0:
            raise ValueError("Motion target/time must be finite and time nonnegative")
        if dt == 0.0:
            return self.state
        target = max(self.minimum, min(self.maximum, target))
        if target != self._target:
            self._plan(target)
        position, velocity = self.state.position, self.state.velocity
        acceleration = 0.0
        while self._segments and dt > 0.0:
            duration, acceleration = self._segments[0]
            step = min(duration, dt)
            position += velocity * step + 0.5 * acceleration * step**2
            velocity += acceleration * step
            dt -= step
            if step == duration:
                self._segments.pop(0)
            else:
                self._segments[0] = (duration - step, acceleration)
        if not self._segments:
            self.state = MotionState(target)
        else:
            self.state = MotionState(max(self.minimum, min(self.maximum, position)),
                                     velocity, acceleration)
        return self.state
