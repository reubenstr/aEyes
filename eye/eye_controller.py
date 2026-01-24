import time
import math

from eye import Eye, rgb255_srgb_to_linear

class EyeController:
    def __init__(self, app: Eye):
        self.app = app
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        palette = [
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (255, 255, 0)]
        i = 0
        cycle_duration = 4.0

        # self.app.set_message("Waiting for controller to send data.")

        self.app.set_is_cat_eye(True)

        while self._running:
            t = time.time()
          
            phase = (t / cycle_duration) % len(palette)
            i0 = int(phase)
            i1 = (i0 + 1) % len(palette)
        
            u = phase - i0
            u = smoothstep(u)
        
            r0, g0, b0 = palette[i0]
            r1, g1, b1 = palette[i1]
            r, g, b = lerp_rgb((r0, g0, b0), (r1, g1, b1), u)
        
            self.app.controls.iris_color = rgb255_srgb_to_linear(
                int(r), int(g), int(b)
            )
            self.app.controls.cornea_color = rgb255_srgb_to_linear(
                255 - int(r), 255-int(g), 255-int(b)
            )


            # Example: animate rAmp smoothly
            t = self.app.now()
            self.app.controls.rAmp = 0.25 + 0.20 * math.sin(t * 0.8)

            # Example: slowly rotate (degrees)
            self.app.controls.rotation_deg = 10.0 * math.sin(t * 0.3)

            i += 1
            time.sleep(.1)  # controller tick
            

###############################################################################
# Helpers
###############################################################################

@staticmethod
def lerp(a, b, t):
        return a + (b - a) * t

@staticmethod
def lerp_rgb(c0, c1, t):
    return tuple(lerp(c0[i], c1[i], t) for i in range(3))

@staticmethod
def smoothstep(t):
    return t * t * (3 - 2 * t)