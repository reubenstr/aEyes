import can
from threading import Thread, Lock, Event
from enum import IntEnum, Enum, StrEnum
from dataclasses import dataclass


class Status(StrEnum):
    NONE = "none"
    STANDBY = "standby"
    ACTIVE = "active"
    WARNING = "warning"
    CRITICAL = "critical"
    ERROR = "error"


class MotorSpeeds(IntEnum):
    SLOW = 500
    MOTION = 1000 # 15000


class MotorName(StrEnum):
    BASE = "BASE"
    EYE = "EYE"


@dataclass
class MotorInfo:
    name: MotorName
    can_channel: str
    id: int
    min_position: float
    max_position: float
    inverse_rotation: bool
    allow_motion: bool
    allow_comms: bool


@dataclass
class CanInfo:
    can_channel: str
    bus: can.interface.Bus
    status: Status
    thread_handle: Thread
    lock: Lock
    exit_event: Event
    loop_completion_time_ms: float = 0.01
    worker_running_flag: bool = False


# For zeroing script.
@dataclass
class MotorZeroInfo:
    can_id: int
    motor_name: str
    motor_id: int
    allow_comms: bool
    allow_motion: bool
    position: float
    comms_error: bool
    hardware_error: bool
