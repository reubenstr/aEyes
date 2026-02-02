from typing import List
from motors.interfaces import MotorInfo, MotorName


"""
    Motor configurations.

    Use allow_motion and allow_comms during development to limit active motors and comms errors.

    Use inverse_rotation to match the output position (rotation in degrees) to the kinematics system.

"""


def motor_list() -> List[MotorInfo]:
    return [
        MotorInfo(
            name=MotorName.BASE,
            can_channel="can0",
            id=1,
            min_angle=-60.0,
            max_angle=60.0,
            inverse_rotation=True,
            allow_motion=True,
            allow_comms=True,
        ),
        MotorInfo(
            name=MotorName.EYE,
            can_channel="can1",
            id=1,
            min_angle=-60.0,
            max_angle=60.0,
            inverse_rotation=True,
            allow_motion=False,
            allow_comms=False,
        ),
    ]
