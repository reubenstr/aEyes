from typing import List
from motors.data_types import MotionLimits, MotorConfig, MotorName

"""
    Motor configurations.

    Use allow_motion and allow_comms during development to limit active motors and comms errors.

    Use inverse_rotation to match the output position (rotation in degrees) to the kinematics system.

    home_position used to home motor, for example the EYE motor does not have dual encoders so it must be homed upon startup.

    motion limits shape the local tracking trajectory in output degrees/seconds.
    These are starting values for hardware tuning at the existing current limit;
    they do not change driver current, PID, acceleration, or CAN speed settings.
"""

# Eye 2: switch zeroing side to avoid the U-Bracket from colliding with the frame.
BASE_HOME_INVERSION = [None, False, True, False, False, False, False]

# Eyes 4 and 6: invert rotation due to being mounted upside down.
EYE_INVERSIONS = [None, False, False, False, True, False, True]

def motor_config() -> List[MotorConfig]:
    return [
        MotorConfig(
            name=MotorName.BASE,
            can_channel="can0",
            id=1,
            min_position=-45.0,
            max_position=45.0,
            inverse_rotation=True,  # CW is negative, CCW is positive
            allow_motion=True,
            allow_comms=True,
            home_position=67.5,  # Physical endstop position.
            motion=MotionLimits(
                max_speed_deg_s=45.0,
                max_acceleration_deg_s2=90.0,
                max_jerk_deg_s3=360.0,
                max_following_error_deg=5.0,
                feedback_timeout_s=0.25,
            ),
        ),
        MotorConfig(
            name=MotorName.EYE,
            can_channel="can0",
            id=2,
            min_position=-45.0,
            max_position=45.0,
            inverse_rotation=True,
            allow_motion=True,
            allow_comms=True,
            home_position=45,  # Physical endstop position.
            motion=MotionLimits(
                max_speed_deg_s=30.0,
                max_acceleration_deg_s2=60.0,
                max_jerk_deg_s3=240.0,
                max_following_error_deg=5.0,
                feedback_timeout_s=0.25,
            ),
        ),
    ]


def get_motor_info(name: MotorName) -> MotorConfig:
    for motor in motor_config():
        if motor.name == name:
            return motor

    raise ValueError(f"Motor not found: {name}")
