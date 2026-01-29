import zmq
import struct
import os
from pathlib import Path
from eye_renderer import EyeRenderer
from threading import Thread, Event, Lock
from pathlib import Path
from time import sleep
from utilities import crc16_ccitt
import serial
from interfaces import ControlMessage
import json

SOCKET_ADDRESS = "192.168.1.145"
SOCKET_PORT = 9000

SERIAL_PORT = "/dev/ttyAMA0"
SERIAL_BAUD = 115200


class Eye:
    def __init__(self):
        pass

    ###############################################################################
    # Initializers
    ###############################################################################

    def init_eye_renderer(self):
        self.eye_renderer = EyeRenderer()
        self.eye_renderer.window.on_close = self.shutdown
        self.eye_renderer.set_message('info', 'Waiting for data.')

    def init_serial(self):
        try:
            self.ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1)
            print(f"[Main] Serial port opened on device: {SERIAL_PORT}, baud: {SERIAL_BAUD}")
        except serial.SerialException as e:
            print(f"[Main] Failed to open serial port: {e}")
            self.ser = None

    def init_socket(self):
        context = zmq.Context()
        self.socket = context.socket(zmq.SUB)
        address = f"tcp://{SOCKET_ADDRESS}:{SOCKET_PORT}"
        self.socket.connect(address)
        self.socket.setsockopt_string(zmq.SUBSCRIBE, "")
        print(f"[Main] Socket requested at address: {address}")

    def init_local(self):
        eye_id = os.getenv("EYE_ID", None)
        if eye_id is None:
            self.eye_renderer.set_message("EYE_ID not found in ENV vars!")
        self.eye_id = int(eye_id)

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

                        self.eye_renderer.set_message('', '')
                        self.eye_renderer.set_radius(msg.radius)
                        self.eye_renderer.set_rotation_deg(msg.rotation_deg)
                        self.eye_renderer.set_eye_lid_position(msg.eye_lid_position)
                        self.eye_renderer.set_iris_color_rgb255(msg.iris_color)
                        self.eye_renderer.set_cornea_color_rgb255(msg.cornea_color)
                        self.eye_renderer.set_is_cat_eye(msg.is_cat_eye)   

                        self.send_driver_message(msg.motor_enable, msg.position_0, msg.position_1)
                       
                except zmq.Again:
                    # No message available.
                    pass 

            sleep(0.005)

    ###############################################################################
    # General
    ###############################################################################

    def run(self):
        self.init_eye_renderer()
        self.init_serial()
        self.init_socket()
        self.init_local()
        self.start()

        # Blocking
        self.eye_renderer.run()

    def shutdown(self):
        try:
            self.eye_renderer.window.close()
            self.stop()
        except Exception:
            pass

    ###############################################################################
    # Messages out
    ###############################################################################
    def send_driver_message(self, enable: bool, position_0: float, position_1: float) -> bytes:

        command_data = struct.pack("<Bff", int(enable), position_0, position_1)

        crc = crc16_ccitt(command_data)
        crc_bytes = struct.pack("<H", crc)
        packet = command_data + crc_bytes

        if self.ser:
            self.ser.write(packet)

        return packet


###############################################################################
# Main Entry
###############################################################################
if __name__ == "__main__":
    eye = Eye()
    try:
        eye.run()
    except KeyboardInterrupt:
        eye.shutdown()
