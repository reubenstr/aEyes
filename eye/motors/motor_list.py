from typing import List
from motors.data_types import MotorInfo, MotorName

"""
    Motor configurations.

    Use allow_motion and allow_comms during development to limit active motors and comms errors.

    Use inverse_rotation to match the output position (rotation in degrees) to the kinematics system.

    home_position used to home motor, for example the EYE motor does not have dual encoders so it must be homed upon startup.
"""

def motor_info_list() -> List[MotorInfo]:
    return [
        MotorInfo(
            name=MotorName.BASE,
            can_channel="can0",
            id=1,
            min_position=-45.0,
            max_position=45.0,
            inverse_rotation=True, # CW is negative, CCW is positive
            allow_motion=True,
            allow_comms=True,
            home_position=67.5, # Physical endstop position.
        ),
        MotorInfo(
            name=MotorName.EYE,
            can_channel="can0",
            id=2,
            min_position=-45.0,
            max_position=45.0,
            inverse_rotation=True,
            allow_motion=True,
            allow_comms=True,
            home_position=45, # Physical endstop position.
        ),
    ]

def get_motor_info(name: MotorName) -> MotorInfo:
    for motor in motor_info_list():
        if motor.name == name:
            return motor

    raise ValueError(f"Motor not found: {name}")