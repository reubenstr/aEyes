"""

Script to test the motor position behavior.

Using a USB-CAN adapter with candlelite firmware

Run these commands to up the CAN device:
    sudo ip link set can0 up type can bitrate 1000000
    sudo ifconfig can0 txqueuelen 65536
    sudo ifconfig can0 up

"""

import can
from time import sleep
from motors.motor import Motor
from motors.data_types import MotorName

if __name__ == "__main__":
    can_channel = "can0"

    bus = can.interface.Bus(interface="socketcan", channel=can_channel, bitrate=1000000)

    motor = Motor(
        name=MotorName.BASE,
        motor_id=1,  # match to motor's dip switch setting
        min_position=-1000,
        max_position=1000,
        inverse_rotation=False,
        allow_comms=True,
        allow_motion=True,
        can_channel=can_channel,
        bus=bus,
    )

    while True:
        motor.req_position()
        print(motor.raw_position_degrees)
        sleep(0.100)
