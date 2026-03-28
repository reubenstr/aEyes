import zmq
import time
import json
import math
from dataclasses import dataclass, asdict
from interfaces import ControlMessage
from utilities import lerp, lerp_rgb, smoothstep, srgb_to_linear, rgb255_srgb_to_linear

SOCKET_ADDRESS = "*"
SOCKET_PORT = 9000

REFRESH_RATE_HZ = 15


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

    def run(self):
        palette = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
        i = 0
        cycle_duration = 4.0

        yaw = 0.0
        pitch = 0.0

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

            # radius = 0.25 + 0.20 * math.sin(t * 0.8)
            radius = (math.sin(t * 4) + 1) / 2

            rotation_deg = 10.0 * math.sin(t * 0.3)
            eye_lid_position = (math.sin(t) + 1) / 2
            iris_color = tuple([int(r), int(g), int(b)])
            cornea_color = tuple([255 - int(r), 255 - int(g), 255 - int(b)])

            ###################################
            radius = 0
            rotation_deg = 0
            eye_lid_position = 1

            iris_color = tuple([0, 157, 0])
            #cornea_color = tuple([0, 157, 0])
            ###################################

            yaw = ((math.sin(t) + 1) / 2) * 90 - 45
            pitch = ((math.sin(t) + 1) / 2) * 90 - 45

            messages = {}
            for eye_id in range(1, 7):
                messages[eye_id] = asdict(ControlMessage(
                    radius=radius,
                    rotation_deg=rotation_deg,
                    eye_lid_position=eye_lid_position,
                    iris_color=iris_color,
                    cornea_color=cornea_color,
                    is_cat_eye=False,
                    yaw=yaw,
                    pitch=pitch,
                ))

            message_str = json.dumps(messages)
            self.socket.send_string(message_str)
            # print("Sent:", message_str)

            time.sleep(1 / REFRESH_RATE_HZ)

    def shutdown(self):
        self.running = False     


###############################################################################
# Main Entry
###############################################################################
if __name__ == "__main__":
    controller = Controller()
    try:
        controller.run()
    except KeyboardInterrupt:
        pass
    finally:
        controller.shutdown()
