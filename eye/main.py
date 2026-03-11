import os
import zmq
import json
import struct
from eye_renderer import EyeRenderer
from threading import Thread, Event, Lock
from time import sleep

from interfaces import ControlMessage, MessageType
from motors.interfaces import MotorName, MotorSpeeds
from motors.motors import Motors


SOCKET_ADDRESS = "192.168.5.1"
SOCKET_PORT = 9000

class Eye:
    def __init__(self):
        pass

    ###############################################################################
    # Initializers
    ###############################################################################

    def init_eye_renderer(self):
        print("[Main] init eye renderer")
        self.eye_renderer = EyeRenderer()
        self.eye_renderer.window.on_close = self.shutdown
        self.eye_renderer.set_message(MessageType.INFO, 'Waiting for data.')

    def init_socket(self):
        print("[Main] init zmq")
        context = zmq.Context()
        self.socket = context.socket(zmq.SUB)
        address = f"tcp://{SOCKET_ADDRESS}:{SOCKET_PORT}"
        self.socket.connect(address)
        self.socket.setsockopt_string(zmq.SUBSCRIBE, "")
        print(f"[Main] Socket requested at address: {address}")

    def init_local(self):      
        print("[Main] initialize local variables")
        eye_id = os.getenv("EYE_ID", None)
        if eye_id is None:
            self.eye_renderer.set_message(MessageType.ERROR, "EYE_ID not found in ENV vars!")
        else:    
            self.eye_id = int(eye_id)

    def init_motors(self):
        print("[Main] initialize motors")
        self.motors = Motors(allow_enable=True)     
        self.motors.enable_all_motors()
        self.motors.set_motor_targets(motor_name=MotorName.BASE, speed=MotorSpeeds.SLOW, position=0)
        self.motors.set_motor_targets(motor_name=MotorName.EYE, speed=MotorSpeeds.SLOW, position=0)  
        sleep(3)
        return

        while(True):
            print("GO -")
            self.motors.set_motor_targets(motor_name=MotorName.BASE, speed=MotorSpeeds.MOTION, position=-30)
            sleep(3)
            print("GO +")
            self.motors.set_motor_targets(motor_name=MotorName.BASE, speed=MotorSpeeds.MOTION, position=30)
            sleep(3)


    ###############################################################################
    # Thread
    ###############################################################################

    def start(self):
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

        while not self.exit_event.is_set():
            if self.socket:
                try:
                    msg_raw = self.socket.recv_string(flags=zmq.NOBLOCK)
                    msg_json = json.loads(msg_raw)                   
                    messages = [ControlMessage(**msg) for msg in msg_json]
                  
                    if self.eye_id:  
                        msg = messages[self.eye_id]                  

                        self.eye_renderer.set_message(MessageType.INFO, '')
                        self.eye_renderer.set_radius(msg.radius)
                        self.eye_renderer.set_rotation_deg(msg.rotation_deg)
                        self.eye_renderer.set_eye_lid_position(msg.eye_lid_position)
                        self.eye_renderer.set_iris_color_rgb255(msg.iris_color)
                        self.eye_renderer.set_striation_color_rgb255(msg.cornea_color)
                        self.eye_renderer.set_is_cat_eye(msg.is_cat_eye)                          
                     
                        # print(msg.yaw, msg.pitch)

                        self.motors.set_motor_targets(motor_name=MotorName.BASE, speed=MotorSpeeds.MOTION, position=msg.yaw)
                        self.motors.set_motor_targets(motor_name=MotorName.EYE, speed=MotorSpeeds.MOTION, position=msg.pitch)
                       
                except zmq.Again:
                    # No message available.
                    pass 

            sleep(0.005)

    ###############################################################################
    # General
    ###############################################################################

    def run(self):
        self.init_eye_renderer()    
        self.init_socket()
        self.init_local()
        self.init_motors()
        self.start()

        # Blocking
        self.eye_renderer.run()

    def shutdown(self):
        try:
            self.eye_renderer.shutdown()
            self.motors.shutdown()
            self.stop()
        except Exception:
            pass
 

###############################################################################
# Main Entry
###############################################################################
if __name__ == "__main__":
    eye = Eye()
    try:
        eye.run()
    except KeyboardInterrupt:
        eye.shutdown()
