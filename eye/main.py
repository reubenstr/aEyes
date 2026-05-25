import os
import signal
import sys
import zmq
import json
from eye_renderer import EyeRenderer, TextType
from threading import Thread, Event
from time import sleep, time

from data_types import ControlMessage
from motors.data_types import MotorName, MotorSpeeds
from motors.motors import Motors
from motors.motor_config import get_motor_info, BASE_HOME_INVERSION, EYE_INVERSIONS

SOCKET_ADDRESS = "192.168.5.100"
SOCKET_PORT = 9000
MESSAGE_TIMEOUT_SECONDS = 3.0
CONTROLLER_FPS = 15

class Eye:
    def __init__(self):
        self.eye_id = None
        self.motors = None
        self.socket = None
        self.thread_handle = None
        self.commanded_yaw = 0.0
        self.commanded_pitch = 0.0

    ###############################################################################
    # Initializers
    ###############################################################################

    def init_eye_renderer(self):
        print("[Main] init eye renderer")
        self.eye_renderer = EyeRenderer()
        self.eye_renderer.window.on_close = self.shutdown
        self.eye_renderer.set_text(TextType.INFO, "Waiting for data.")

    def _init_local(self):
        print("[Main] initialize local variables")
        eye_id = os.getenv("EYE_ID", None)
        if eye_id is None:
            self.eye_renderer.set_text(TextType.ERROR, "EYE_ID not found in ENV vars!")
        else:
            self.eye_id = int(eye_id)

    def _init_motors(self):
        print("[Main] initialize motors")

        self.motors = Motors(allow_enable=True)

        if self.eye_id and EYE_INVERSIONS[self.eye_id] is True:
            self.motors.set_inversion_rotation(MotorName.BASE, not self.motors.get_inverse_rotation(MotorName.BASE))
            self.motors.set_inversion_rotation(MotorName.EYE, not self.motors.get_inverse_rotation(MotorName.EYE))

        # Allow repolling (recalcuation) of positions that may of been inversed.
        sleep(0.5)

        self.motors.enable_all_motors()
        self.home_motors(self.motors)
        self.motors.disable_all_motors()  # TEMP

    def _init_socket(self):
        print("[Main] init zmq")
        context = zmq.Context()
        self.socket = context.socket(zmq.SUB)
        address = f"tcp://{SOCKET_ADDRESS}:{SOCKET_PORT}"
        self.socket.connect(address)
        self.socket.setsockopt_string(zmq.SUBSCRIBE, "")
        print(f"[Main] Socket requested at address: {address}")

    ###############################################################################
    # Helpers
    ###############################################################################

    def _flush_socket(self):
        try:
            while True and self.socket is not None:
                self.socket.recv_string(flags=zmq.NOBLOCK)
        except zmq.Again:
            pass

    def ramp_target(self, commanded: float, target: float) -> float:
        CLOSE_DEG = 5.0  # below this → pass-through (fast tracking)
        FAR_DEG = 30.0  # above this → max slowdown
        FAST_DEG_S = 900.0  # deg/sec when close (~pass-through)
        SLOW_DEG_S = 22.5  # deg/sec when far   (smooth slew)
        delta = abs(target - commanded)
        t = max(0.0, min(1.0, (delta - CLOSE_DEG) / (FAR_DEG - CLOSE_DEG)))
        t = 3 * t**2 - 2 * t**3  # smoothstep
        max_step = (FAST_DEG_S + t * (SLOW_DEG_S - FAST_DEG_S)) / CONTROLLER_FPS
        return commanded + max(-max_step, min(max_step, target - commanded))

    ###############################################################################
    # Motor Utilities
    ###############################################################################

    def home_motors(self, motors: Motors):
        """
        Home both motors by moving into the physical endstop and polling for position halt.
        """

        motor_home_target_pos_offset = 180
        motors_to_home = [MotorName.BASE, MotorName.EYE]
        operation_timeout_seconds = 5.0
        home_duration = 0.5  # Time motor is required to be stopped before considered home.
        home_threshold_deg = 0.25
        prev_positions = {motor: motors.get_motor_position(motor) for motor in motors_to_home}
        home_started: dict[MotorName, float | None] = {motor: None for motor in motors_to_home}
        homed = {motor: False for motor in motors_to_home}

        self.eye_renderer.set_text(TextType.INFO, "Homing motors...")

        base_position = motors.get_motor_position(MotorName.BASE)    
        base_home_target_position = (
            -motor_home_target_pos_offset if self.eye_id is not None and BASE_HOME_INVERSION[self.eye_id] is True else motor_home_target_pos_offset
        )    
        eye_home_target_position = motor_home_target_pos_offset
        motors.set_enforce_position_limits(MotorName.BASE, False)
        motors.set_motor_targets(motor_name=MotorName.BASE, speed=MotorSpeeds.SLOW, position=base_position + base_home_target_position)

        eye_position = motors.get_motor_position(MotorName.EYE)
        motors.set_enforce_position_limits(MotorName.EYE, False)
        motors.set_motor_targets(motor_name=MotorName.EYE, speed=MotorSpeeds.SLOW, position=eye_position + eye_home_target_position)

        sleep(0.5)  # Allow motors to begin moving before polling.

        start = time()
        while time() - start < operation_timeout_seconds:
            for motor_name in (m for m in motors_to_home if not homed[m]):
                pos = motors.get_motor_raw_position(motor_name)
                delta = abs(pos - prev_positions[motor_name])
                prev_positions[motor_name] = pos

                if motor_name is MotorName.BASE:
                    print(f"{motor_name}: {pos}")

                started = home_started[motor_name]
                if delta < home_threshold_deg:
                    if started is None:
                        home_started[motor_name] = time()
                    elif time() - started >= home_duration:
                        homed[motor_name] = True
                else:
                    home_started[motor_name] = None

            if all(homed.values()):
                break

            sleep(0.050)

        home_position = get_motor_info(MotorName.BASE).home_position
        raw_pos = motors.get_motor_raw_position(MotorName.BASE)
        pos = motors.get_motor_position(MotorName.BASE)
    
        if self.eye_id is not None and BASE_HOME_INVERSION[self.eye_id] is True:
            offset = -raw_pos - home_position
        else:
            offset = -raw_pos + home_position          

        motors.set_enforce_position_limits(MotorName.BASE, True)
        motors.set_position_offset(MotorName.BASE, offset)
        motors.set_motor_targets(motor_name=MotorName.BASE, speed=MotorSpeeds.SLOW, position=0)

        home_position = get_motor_info(MotorName.EYE).home_position
        raw_pos = motors.get_motor_raw_position(MotorName.EYE)
        offset = -(raw_pos - home_position)
        motors.set_enforce_position_limits(MotorName.EYE, True)
        motors.set_position_offset(MotorName.EYE, offset)
        motors.set_motor_targets(motor_name=MotorName.EYE, speed=MotorSpeeds.SLOW, position=0)
       
        sleep(3)  # Allow motors to reach the home position before exiting. 
    

    ###############################################################################
    # Thread
    ###############################################################################

    def _start(self):
        print(f"[Main] worker thread starting")
        self.exit_event: Event = Event()
        self.thread_handle = Thread(target=self._worker)
        self.thread_handle.start()

    def stop(self):
        print(f"[Main] worker thread stoping")
        if self.thread_handle and self.thread_handle.is_alive():
            self.exit_event.set()
            self.thread_handle.join()

    def _worker(self):
        self.exit_event.clear()
        last_msg_time = time()
        connected = False
        self.eye_renderer.set_text(TextType.INFO, "Waiting for data")
        self._flush_socket()

        while not self.exit_event.is_set():
            if self.socket:
                try:
                    msg_raw = self.socket.recv_string(flags=zmq.NOBLOCK)
                    msg_json = json.loads(msg_raw)

                    if self.eye_id is not None:
                        if str(self.eye_id) not in msg_json:
                            print(f"[Main] WARNING: eye_id {self.eye_id} not found in message.")
                            self.eye_renderer.set_text(TextType.ERROR, f"Eye ID {self.eye_id} not found in message!")
                        else:
                            msg = ControlMessage(**msg_json[str(self.eye_id)])

                            last_msg_time = time()
                            if not connected:
                                connected = True
                                print("[Main] Controller connected.")

                            self.eye_renderer.set_text(TextType.INFO, "")
                            self.eye_renderer.set_radius(msg.radius)
                            self.eye_renderer.set_rotation_deg(msg.rotation_deg)
                            self.eye_renderer.set_eye_lid_position(msg.eye_lid_position)
                            self.eye_renderer.set_iris_color_rgb255(msg.iris_color)
                            self.eye_renderer.set_striation_color_rgb255(msg.cornea_color)
                            self.eye_renderer.set_is_cat_eye(msg.is_cat_eye)

                            if self.motors:
                                self.commanded_yaw = self.ramp_target(self.commanded_yaw, msg.yaw)
                                self.commanded_pitch = self.ramp_target(self.commanded_pitch, msg.pitch)
                                self.motors.set_motor_targets(motor_name=MotorName.BASE, speed=MotorSpeeds.FAST, position=self.commanded_yaw)
                                self.motors.set_motor_targets(motor_name=MotorName.EYE, speed=MotorSpeeds.FAST, position=self.commanded_pitch)

                except zmq.Again:
                    if connected and time() - last_msg_time > MESSAGE_TIMEOUT_SECONDS:
                        connected = False
                        print("[Main] Controller disconnected (timeout).")
                        self.eye_renderer.set_text(TextType.ERROR, "Data timeout!")
                except (json.JSONDecodeError, TypeError, KeyError) as e:
                    print(f"[Main] Bad message: {e}")

            sleep(0.005)

    ###############################################################################
    # General
    ###############################################################################

    def _deferred_init(self):
        sleep(0.3)  # Allow pyglet event loop to render first frame
        self._init_local()
        if self.eye_id:
            self._init_motors()
            self._init_socket()
            self._start()

    def run(self):
        self.init_eye_renderer()
        Thread(target=self._deferred_init, daemon=True).start()

        # Blocking
        self.eye_renderer.run()

    def shutdown(self):
        self.stop()
        if self.motors:
            try:
                self.motors.shutdown()
            except Exception as e:
                print(f"[Main] Error shutting down motors: {e}")
        try:
            self.eye_renderer.shutdown()
        except Exception as e:
            print(f"[Main] Error shutting down renderer: {e}")


###############################################################################
# Main Entry
###############################################################################
if __name__ == "__main__":
    eye = Eye()
    signal.signal(signal.SIGTERM, lambda sig, frame: (eye.shutdown(), sys.exit(0)))
    try:
        eye.run()
    except KeyboardInterrupt:
        eye.shutdown()
