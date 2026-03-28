import os
import zmq
import json
from eye_renderer import EyeRenderer, TextType
from threading import Thread, Event
from time import sleep, time

from data_types import ControlMessage
from motors.data_types import MotorName, MotorSpeeds
from motors.motors import Motors
from motors.motor_list import motor_list


SOCKET_ADDRESS = "192.168.5.1"
SOCKET_PORT = 9000
MESSAGE_TIMEOUT_SECONDS = 3.0

class Eye:
    def __init__(self):
        self.eye_id = None
        self.motors = None
        self.motors_zeroed = False
        self.socket = None
        self.thread_handle = None

    ###############################################################################
    # Initializers
    ###############################################################################

    def init_eye_renderer(self):
        print("[Main] init eye renderer")
        self.eye_renderer = EyeRenderer()
        self.eye_renderer.window.on_close = self.shutdown
        self.eye_renderer.set_text(TextType.INFO, 'Waiting for data.')
   
    def _init_local(self):      
        print("[Main] initialize local variables")
        eye_id = os.getenv("EYE_ID", None)
        if eye_id is None:
            self.eye_renderer.set_text(TextType.ERROR, "EYE_ID not found in ENV vars!")
        else:    
            self.eye_id = int(eye_id)

    def _init_motors(self):
        print("[Main] initialize motors")
        if os.path.exists(".motors-zeroed"):
            self.motors_zeroed = True
        else:
            print("[Main] ERROR: .motors-zeroed file not found. Run zero.py first to zero the motors!")
            self.motors_zeroed = False
            return        
       
        if self.motors_zeroed == True:
            self.eye_renderer.set_text(TextType.INFO, 'Zeroing motors...')

            self.motors = Motors(allow_enable=self.motors_zeroed)
            self.motors.enable_all_motors()
            self.motors.set_motor_targets(motor_name=MotorName.BASE, speed=MotorSpeeds.SLOW, position=0)

            # Home EYE motor against endstop.
            # Increase min and max positions for homing operation to accommodate any starting position. 
            eye_motor = next(m for m in motor_list() if m.name == MotorName.EYE)
            self.motors.motors[MotorName.EYE].min_position = -180.0
            self.motors.motors[MotorName.EYE].max_position = 180.0
            self.motors.set_motor_targets(motor_name=MotorName.EYE, speed=MotorSpeeds.SLOW, position=-180.0)

            sleep(0.5)  # Allow motor to start moving before polling.
            prev_pos = self.motors.get_motor_position(MotorName.EYE)
            start = time()
            operation_timeout_seconds = 5.0
            home_started = None
            home_duration = 0.5
            home_threshold_deg = 0.25
            while time() - start < operation_timeout_seconds:
                sleep(0.050)
                pos = self.motors.get_motor_position(MotorName.EYE)
                print(pos)
                if abs(pos - prev_pos) < home_threshold_deg:
                    if home_started is None:
                        home_started = time()
                    elif time() - home_started >= home_duration:
                        break
                else:
                    home_started = None
                prev_pos = pos

            current_pos = self.motors.motors[MotorName.EYE].position_degrees
            self.motors.motors[MotorName.EYE].set_position_offset(-current_pos - eye_motor.home_position)
            self.motors.motors[MotorName.EYE].min_position = eye_motor.min_position
            self.motors.motors[MotorName.EYE].max_position = eye_motor.max_position
            self.motors.set_motor_targets(motor_name=MotorName.EYE, speed=MotorSpeeds.SLOW, position=0)            
            sleep(3)

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
            while True:
                self.socket.recv_string(flags=zmq.NOBLOCK)
        except zmq.Again:
            pass

    def adaptive_speed(self, motor_name, target):
        CLOSE_DEG = 5.0   # below this → full fast speed
        FAR_DEG   = 20.0  # above this → full slow speed
        current = self.motors.get_motor_position(motor_name)
        if current is None:
            return MotorSpeeds.SLOW
        delta = abs(target - current)
        t = max(0.0, min(1.0, (delta - CLOSE_DEG) / (FAR_DEG - CLOSE_DEG)))
        t = 1.0 - (1.0 - t) ** 2   # ease-out: smooth transition near FAR_DEG
        return int(MotorSpeeds.FAST + t * (MotorSpeeds.SLOW - MotorSpeeds.FAST))


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
        self.eye_renderer.set_text(TextType.INFO, 'Waiting for data.')
        self._flush_socket()

        while not self.exit_event.is_set():
            if not self.motors_zeroed:
                self.eye_renderer.set_text(TextType.ERROR, 'Motors not zeroed!')
            elif self.socket:
                try:
                    msg_raw = self.socket.recv_string(flags=zmq.NOBLOCK)
                    msg_json = json.loads(msg_raw)

                    if self.eye_id is not None:
                        if str(self.eye_id) not in msg_json:
                            print(f"[Main] WARNING: eye_id {self.eye_id} not found in message.")
                            self.eye_renderer.set_text(TextType.ERROR, f'Eye ID {self.eye_id} not found in message!')
                        else:
                            msg = ControlMessage(**msg_json[str(self.eye_id)])

                            last_msg_time = time()
                            if not connected:
                                connected = True
                                print("[Main] Controller connected.")

                            self.eye_renderer.set_text(TextType.INFO, '')
                            self.eye_renderer.set_radius(msg.radius)
                            self.eye_renderer.set_rotation_deg(msg.rotation_deg)
                            self.eye_renderer.set_eye_lid_position(msg.eye_lid_position)
                            self.eye_renderer.set_iris_color_rgb255(msg.iris_color)
                            self.eye_renderer.set_striation_color_rgb255(msg.cornea_color)
                            self.eye_renderer.set_is_cat_eye(msg.is_cat_eye)

                            if self.motors:                                
                                self.motors.set_motor_targets(motor_name=MotorName.BASE, speed=self.adaptive_speed(MotorName.BASE, msg.yaw), position=msg.yaw)
                                self.motors.set_motor_targets(motor_name=MotorName.EYE, speed=self.adaptive_speed(MotorName.EYE, msg.pitch), position=msg.pitch)

                except zmq.Again:
                    if connected and time() - last_msg_time > MESSAGE_TIMEOUT_SECONDS:
                        connected = False
                        print("[Main] Controller disconnected (timeout).")
                        self.eye_renderer.set_text(TextType.ERROR, 'Data timeout!')
                except (json.JSONDecodeError, TypeError, KeyError) as e:
                    print(f"[Main] Bad message: {e}")

            sleep(0.005)

    ###############################################################################
    # General
    ###############################################################################

    def _deferred_init(self):
        sleep(0.3)  # Allow pyglet event loop to render first frame       
        self._init_local()
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
        if self.motors_zeroed and self.motors:
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
    try:
        eye.run()
    except KeyboardInterrupt:
        eye.shutdown()
