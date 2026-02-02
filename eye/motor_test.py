from time import sleep
from motors.interfaces import MotorName, MotorSpeeds
from motors.motors import Motors


motors = Motors(allow_enable=True)

motors.enable_all_motors()

sleep(50)

try:
    while True:
        motors.set_motor_targets(MotorName.BASE, MotorSpeeds.MOTION, -15)
        sleep(2)
        motors.set_motor_targets(MotorName.BASE, MotorSpeeds.MOTION, 15)
        sleep(2)
except KeyboardInterrupt:
    motors.shutdown()
