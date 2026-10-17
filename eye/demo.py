import colorsys
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

    renderer.set_radius(1.0)
    renderer.set_curvature(0.2)
    renderer.set_sclera_color_rgb255((214, 207, 199))
    renderer.set_vein_color_rgb255((184, 23, 23))
    renderer.set_pupil_color_rgb255((0, 0, 0))
    renderer.set_vein_seed(1)
    start = time.monotonic()

    while(True):
        t = time.monotonic() - start

        renderer.set_iris_size(0.5 + 0.3 * math.sin(t * 0.7))
        renderer.set_pupil_size(0.5 + 0.4 * math.sin(t * 0.4))
        renderer.set_vein_count((8, 0, 24)[int(t / 8.0) % 3])

        # Rotation: oscillate within [-15, 15] degrees
        renderer.set_rotation_deg(15.0 * math.sin(t * 0.5))

        # Preview resting openness from 0.5 to 1.0 with a complete blink every 4 seconds.
        rest = 0.75 + 0.25 * math.sin(t * 0.3)
        blink_phase = (t % 4.0) / 4.0
        if blink_phase > 0.9:
            lid = rest * (1.0 - math.sin((blink_phase - 0.9) / 0.1 * math.pi))
        else:
            lid = rest
        renderer.set_eye_lid_position(lid)

        # Iris color: cycle hue via RGB sinusoids
        r = int(127 + 127 * math.sin(t * 0.4))
        g = int(127 + 127 * math.sin(t * 0.4 + 2.094))   # 2π/3 offset
        b = int(127 + 127 * math.sin(t * 0.4 + 4.189))   # 4π/3 offset
        renderer.set_iris_color_rgb255((r, g, b))

        hue = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)[0]
        for setter, offset, lightness, saturation in (
            (renderer.set_iris_accent_color_rgb255, 0.06, 0.30, 0.55),
            (renderer.set_iris_center_color_rgb255, -0.12, 0.55, 0.75),
            (renderer.set_striation_color_rgb255, 0.03, 0.76, 0.65),
        ):
            rgb = colorsys.hls_to_rgb((hue + offset) % 1.0, lightness, saturation)
            setter(tuple(round(c * 255) for c in rgb))

        renderer.set_is_cat_eye(int(t / 12.0) % 2 == 1)

        sleep(1 / 60.0)
    

if __name__ == "__main__":
    renderer = EyeRenderer()
    Thread(target=loop, args=(renderer,), daemon=True).start()
    try:
        renderer.run()
    except KeyboardInterrupt:
        pass
