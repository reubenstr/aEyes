from typing import Any
from threading import Thread, Lock, Event
from enum import IntEnum, Enum, StrEnum
from dataclasses import dataclass, field
import math


class Status(StrEnum):
    NONE = "none"
    STANDBY = "standby"
    ACTIVE = "active"
    WARNING = "warning"
    CRITICAL = "critical"
    ERROR = "error"


class MotorSpeeds(IntEnum):
    SLOW = 300
    FAST = 10000


class MotorName(StrEnum):
    BASE = "BASE"
    EYE = "EYE"


@dataclass
class MotionLimits:
    """Eye-side trajectory limits in output degrees and seconds, not CAN units."""
    max_speed_deg_s: float = 30.0
    max_acceleration_deg_s2: float = 60.0
    max_jerk_deg_s3: float = 240.0
    max_following_error_deg: float = 5.0
    feedback_timeout_s: float = 0.25

    def __post_init__(self):
        if not all(math.isfinite(value) and value > 0 for value in (
                self.max_speed_deg_s, self.max_acceleration_deg_s2,
                self.max_jerk_deg_s3, self.max_following_error_deg, self.feedback_timeout_s)):
            raise ValueError("Motion limits must be finite and positive")


@dataclass
class MotorConfig:
    name: MotorName
    can_channel: str
    id: int
    min_position: float
    max_position: float
    inverse_rotation: bool
    allow_motion: bool
    allow_comms: bool
    home_position: float
    motion: MotionLimits = field(default_factory=MotionLimits)


@dataclass
class CanInfo:
    can_channel: str
    bus: Any
    status: Status
    thread_handle: Thread
    lock: Lock
    exit_event: Event
    loop_completion_time_ms: float = 0.01
    worker_running_flag: bool = False


# For zeroing script.
@dataclass
class MotorZeroInfo:
    can_id: str
    motor_name: str
    motor_id: int
    allow_comms: bool
    allow_motion: bool
    position: float
    comms_error: bool
    hardware_error: bool
