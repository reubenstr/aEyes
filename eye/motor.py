from tmc_driver import (
    Tmc2208,
    Loglevel,
    Board,
    tmc_gpio,
    MovementAbsRel,
    TmcEnableControlPin,
    TmcMotionControlStepDir,
)
from tmc_driver.com import TmcComUart

from time import sleep


print("---")
print("SCRIPT START")
print("---")


# -----------------------------------------------------------------------
# initiate the Tmc2209 class
# use your pins for pin_en, pin_step, pin_dir here
# -----------------------------------------------------------------------
UART_PORT = {
    Board.RASPBERRY_PI: "/dev/serial0",
    Board.RASPBERRY_PI5: "/dev/ttyAMA0",
    Board.NVIDIA_JETSON: "/dev/ttyTHS1",
}

'''
# Driver 0
tmc = Tmc2208(
    TmcEnableControlPin(19),
    TmcMotionControlStepDir(13, 6),
    TmcComUart(UART_PORT.get(tmc_gpio.BOARD, "/dev/serial0")),
    loglevel=Loglevel.DEBUG,
) 
'''


# Driver 1
tmc = Tmc2208(
    TmcEnableControlPin(22),
    TmcMotionControlStepDir(27, 17),
    TmcComUart("/dev/ttyAMA3"),
    loglevel=Loglevel.DEBUG,
)
''' '''

# -----------------------------------------------------------------------
# set the loglevel of the libary (currently only printed)
# set whether the movement should be relative or absolute
# both optional
# -----------------------------------------------------------------------
tmc.tmc_logger.loglevel = Loglevel.DEBUG
tmc.movement_abs_rel = MovementAbsRel.ABSOLUTE


'''  
tmc.set_direction_reg(False)
tmc.set_current_rms(300)
tmc.set_interpolation(True)
tmc.set_spreadcycle(False)
tmc.set_microstepping_resolution(2)
tmc.set_internal_rsense(False)
'''

'''
tmc.read_register("ioin")
tmc.read_register("chopconf")
tmc.read_register("drvstatus")
tmc.read_register("gconf")
'''






# -----------------------------------------------------------------------
# set the Acceleration and maximal Speed
# -----------------------------------------------------------------------
#tmc.set_acceleration(1000)
#tmc.set_max_speed(250)

# -----------------------------------------------------------------------
# set the Acceleration and maximal Speed in fullsteps
# -----------------------------------------------------------------------
tmc.acceleration_fullstep = 500
tmc.max_speed_fullstep = 125


tmc.set_motor_enabled(True)

sleep(5)



tmc.run_to_position_fullsteps(200)  # move to position 200 (fullsteps)
#tmc.run_to_position_fullsteps(0)  # move to position 0

#tmc.run_to_position_fullsteps(
#    200, MovementAbsRel.RELATIVE
#)  # move 200 fullsteps forward
#tmc.run_to_position_fullsteps(
#    -200, MovementAbsRel.RELATIVE
#)  # move 200 fullsteps backward

#tmc.run_to_position_steps(400)  # move to position 400 (µsteps)
#tmc.run_to_position_steps(0)  # move to position 0

#tmc.run_to_position_revolutions(1)  # move 1 revolution forward
#tmc.run_to_position_revolutions(0)  # move 1 revolution backward

tmc.set_motor_enabled(False)

del tmc
