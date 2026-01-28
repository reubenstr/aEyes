import zmq
import struct
from pathlib import Path
from eye import EyeRenderer
from threading import Thread, Event, Lock
from pathlib import Path
from time import sleep
from utilities import crc16_ccitt
import serial

SOCKET_ADDRESS = '192.168.1.145'
SOCKET_PORT = 9000

SERIAL_PORT = '/dev/ttyAMA0'
SERIAL_BAUD = 115200


class Eye:
    def __init__(self):  
        pass

    ###############################################################################
    # Initializers
    ###############################################################################    

    def init_eye_renderer(self):
        ROOT = Path(__file__).resolve().parent

        self.eye_renderer = EyeRenderer(
            vert_path=ROOT / "shaders" / "eye.vert",
            frag_path=ROOT / "shaders" / "eye.frag",       
            update_hz=60.0,
        )
    
        self.eye_renderer.window.on_close = self.shutdown
    
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
                    msg = self.socket.recv_string(flags=zmq.NOBLOCK)
                    print("Received:", msg)
                except zmq.Again:
                    pass  # no message available

            sleep(0.010)

    ###############################################################################
    # General 
    ###############################################################################   

    def run(self):
        self.init_eye_renderer()

        self.init_serial()

        self.init_socket()
        
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
    def send_position_message(self, enable: bool, zero: bool, angle_base: float, angle_eye: float) -> bytes:
        
        command_data = struct.pack('<BBff', 
                                int(enable), 
                                int(zero), 
                                angle_base, 
                                angle_eye)
        
    
        crc = crc16_ccitt(command_data)  
        crc_bytes = struct.pack('<H', crc) 
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

