import zmq
import time
import json  
import math
from dataclasses import dataclass, asdict
from utilities import lerp, lerp_rgb, smoothstep, srgb_to_linear, rgb255_srgb_to_linear

SOCKET_ADDRESS = '*'
SOCKET_PORT = 9000

REFRESH_RATE_HZ = 60

@dataclass
class ControlMessage:
    radius: float
    rotation_deg: float
    blink: float 
    pupil_size: float 
    iris_color: tuple[float, float, float]
    cornea_color: tuple[float, float, float] 
    is_cat_eye: bool

class Controller:
    def __init__(self):
        self.running = True

        self.init_socket()

    ###############################################################################
    # Initializers
    ###############################################################################   

    def init_socket(self):
        context = zmq.Context()
        self.socket = context.socket(zmq.PUB)
        address = f"tcp://{SOCKET_ADDRESS}:{SOCKET_PORT}"
        self.socket.bind(address) 

    ###############################################################################
    # Main Loop
    ###############################################################################

    def stop(self):
        self.running = False

    def run(self):
        palette = [
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (255, 255, 0)]
        i = 0
        cycle_duration = 4.0


        while self.running:
            t = time.time()
          
            phase = (t / cycle_duration) % len(palette)
            i0 = int(phase)
            i1 = (i0 + 1) % len(palette)
        
            u = phase - i0
            u = smoothstep(u)
        
            r0, g0, b0 = palette[i0]
            r1, g1, b1 = palette[i1]
            r, g, b = lerp_rgb((r0, g0, b0), (r1, g1, b1), u)

                  
            iris_color = tuple([int(r), int(g), int(b)])
            cornea_color = tuple([255 - int(r), 255-int(g), 255-int(b)])
                  
            radius = 0.25 + 0.20 * math.sin(t * 0.8)          
            rotation_deg = 10.0 * math.sin(t * 0.3)

            message = ControlMessage(
                radius=radius,
                rotation_deg=rotation_deg,
                blink=False,
                pupil_size=5.0,
                iris_color=iris_color,
                cornea_color=cornea_color,
                is_cat_eye=False
            )

            message_str = json.dumps(asdict(message))
            self.socket.send_string(message_str)
            print("Sent:", message_str)
                
            time.sleep(1 / REFRESH_RATE_HZ)  
            

###############################################################################
# Main Entry
###############################################################################
if __name__ == "__main__":
    controller = Controller()
    try:
        controller.run()
    except KeyboardInterrupt:
        pass
