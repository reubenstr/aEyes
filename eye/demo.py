import math
import time
from threading import Thread
from time import sleep
from eye_renderer import EyeRenderer
from eye_renderer import TextType

"""
    Eye renderer demo.

    To run:
        cd ./aEyes/eye
        source ./.venv/bin/activate
        python3 ./demo.py 
"""

def loop(renderer: EyeRenderer) -> None:
    renderer.set_text(TextType.INFO, 'Demo info message.')
    sleep(1)
    renderer.set_text(TextType.ERROR, 'Demo error message.')
    sleep(1)
    renderer.set_text(TextType.INFO, '')

    while(True):
        t = time.time()

        # Iris radius: 0.3 → 0.8, slow pulse
        renderer.set_radius(0.55 + 0.25 * math.sin(t * 0.7))

        # Rotation: oscillate within [-15, 15] degrees
        renderer.set_rotation_deg(15.0 * math.sin(t * 0.5))

        # Eyelid: open (1.0) most of the time, quick blink every ~4 seconds
        blink_phase = (t % 4.0) / 4.0
        if blink_phase > 0.9:
            lid = 1.0 - math.sin((blink_phase - 0.9) / 0.1 * math.pi)
        else:
            lid = 1.0
        renderer.set_eye_lid_position(lid)

        # Iris color: cycle hue via RGB sinusoids
        r = int(127 + 127 * math.sin(t * 0.4))
        g = int(127 + 127 * math.sin(t * 0.4 + 2.094))   # 2π/3 offset
        b = int(127 + 127 * math.sin(t * 0.4 + 4.189))   # 4π/3 offset
        renderer.set_iris_color_rgb255((r, g, b))

        # Striation color: complementary hue
        renderer.set_striation_color_rgb255((255 - r, 255 - g, 255 - b))

        # Cat-eye: toggle every 6 seconds
        # renderer.set_is_cat_eye(int(t / 6.0) % 2 == 1)

        sleep(1 / 60.0)
    

if __name__ == "__main__":
    renderer = EyeRenderer()
    Thread(target=loop, args=(renderer,), daemon=True).start()
    try:
        renderer.run()
    except KeyboardInterrupt:
        pass