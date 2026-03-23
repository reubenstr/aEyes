from typing import List
from motors.interfaces import MotorInfo, MotorName


"""
    Motor configurations.

    Use allow_motion and allow_comms during development to limit active motors and comms errors.

    Use inverse_rotation to match the output position (rotation in degrees) to the kinematics system.

    home_position used to home motor, for example the EYE motor does not have dual encoders so it must be homed upon startup.
"""


def motor_list() -> List[MotorInfo]:
    return [
        MotorInfo(
            name=MotorName.BASE,
            can_channel="can0",
            id=1,
            min_position=-45.0,
            max_position=45.0,
            inverse_rotation=False,
            allow_motion=True,
            allow_comms=True,
            home_position=None,
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
            home_position=50.5
        ),
    ]
