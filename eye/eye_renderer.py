import time
import ctypes
from enum import Enum, auto
from pathlib import Path

from data_types import ControlMessage

import pyglet
# IMPORTANT: set options BEFORE importing pyglet.gl or pyglet.graphics.shader
pyglet.options.shadow_window = False
pyglet.options["backend"] = "egl"  # Raspberry Pi EGL
from pyglet import gl
from pyglet.graphics.shader import Shader, ShaderProgram


class TextType(Enum):
    INFO = auto()
    ERROR = auto()


class EyeRenderer:
    def __init__(self): 

        self._start_time = time.monotonic()

        # Render controls
        self.radius: float = 1.0
        self.curvature: float = 0.2
        self.iris_size: float = 0.5
        self.pupil_size: float = 0.5
        self.vein_count: int = 8
        self.vein_seed: int = 1
        self.rotation_deg: float = 0.0
        self.eye_lid_position: float = 0.85
        self.iris_color = rgb255_to_normalized(128, 128, 128)
        self.iris_accent_color = rgb255_to_normalized(128, 128, 128)
        self.iris_center_color = rgb255_to_normalized(128, 128, 128)
        self.striation_color = rgb255_to_normalized(0, 0, 0)
        self.pupil_color = rgb255_to_normalized(0, 0, 0)
        self.sclera_color = rgb255_to_normalized(214, 207, 199)
        self.vein_color = rgb255_to_normalized(184, 23, 23)
        self.is_cat_eye: bool = False

        self._program: ShaderProgram | None = None
        self._vao = gl.GLuint(0)
        self._vbo = gl.GLuint(0)   

        # Window configuration.
        display = pyglet.display.get_display()
        screen = display.get_default_screen()
        config = screen.get_best_config(gl.Config(
            opengl_api="gles", major_version=3, minor_version=1, double_buffer=True,
        ))

        self.window = pyglet.window.Window(fullscreen=True, style=pyglet.window.Window.WINDOW_STYLE_BORDERLESS, config=config)
        self.window.set_mouse_visible(False)
        print(
            f"[Renderer] {self.window.width}x{self.window.height}, "
            f"double_buffer={self.window.config.double_buffer}, "
            f"GL={self.window.context.get_info().get_version_string()}",
            flush=True,
        )

        self.pending_text = None
        self.pending_text_type = TextType.INFO
        self.text_label = pyglet.text.Label(
            "",
            font_name="Monospace",
            font_size=18,
            x=self.window.width // 2,
            y=self.window.height // 2,
            width=self.window.width,
            multiline=True,
            anchor_x="center",
            anchor_y="center",
            align="center",
            color=(255, 80, 80, 255),
        )

        # Attach handlers.
        self.window.on_draw = self._on_draw
        self.window.on_key_press = self._on_key_press

        # GL resources + shaders
        self.init_geometry()
        self.reload_shaders()

        pyglet.clock.schedule_interval(self._update, 1/60.0)
    
    ###############################################################################
    # API
    ###############################################################################
    def set_radius(self, v: float) -> None:
        self.radius = max(1e-4, float(v))

    def set_curvature(self, v: float) -> None:
        self.curvature = clamp01(v)

    def set_iris_size(self, v: float) -> None:
        self.iris_size = clamp01(v)

    def set_pupil_size(self, v: float) -> None:
        self.pupil_size = clamp01(v)

    def set_vein_count(self, v: int) -> None:
        self.vein_count = max(0, min(24, int(v)))

    def set_vein_seed(self, v: int) -> None:
        self.vein_seed = int(v)

    def set_rotation_deg(self, v: float) -> None:
        self.rotation_deg = float(v)

    def set_eye_lid_position(self, v: float) -> None:
        self.eye_lid_position = clamp01(v)
  
    def set_iris_color_rgb255(self, rgb: tuple[int, int, int]) -> None:
        self.iris_color = rgb255_to_normalized(*rgb)

    def set_iris_accent_color_rgb255(self, rgb: tuple[int, int, int]) -> None:
        self.iris_accent_color = rgb255_to_normalized(*rgb)

    def set_iris_center_color_rgb255(self, rgb: tuple[int, int, int]) -> None:
        self.iris_center_color = rgb255_to_normalized(*rgb)

    def set_striation_color_rgb255(self, rgb: tuple[int, int, int]) -> None:
        self.striation_color = rgb255_to_normalized(*rgb)

    def set_pupil_color_rgb255(self, rgb: tuple[int, int, int]) -> None:
        self.pupil_color = rgb255_to_normalized(*rgb)

    def set_sclera_color_rgb255(self, rgb: tuple[int, int, int]) -> None:
        self.sclera_color = rgb255_to_normalized(*rgb)

    def set_vein_color_rgb255(self, rgb: tuple[int, int, int]) -> None:
        self.vein_color = rgb255_to_normalized(*rgb)

    def set_is_cat_eye(self, value: bool) -> None:
        self.is_cat_eye = bool(value)

    def apply_control_message(self, msg: ControlMessage) -> None:
        self.set_radius(msg.radius)
        self.set_rotation_deg(msg.rotation_deg)
        self.set_eye_lid_position(msg.eye_lid_position)
        self.set_iris_color_rgb255(msg.iris_color)
        self.set_striation_color_rgb255(msg.striation_color)
        self.set_is_cat_eye(msg.is_cat_eye)
        self.set_iris_accent_color_rgb255(msg.iris_accent_color)
        self.set_iris_center_color_rgb255(msg.iris_center_color)
        self.set_pupil_color_rgb255(msg.pupil_color)
        self.set_sclera_color_rgb255(msg.sclera_color)
        self.set_vein_color_rgb255(msg.vein_color)
        self.set_iris_size(msg.iris_size)
        self.set_pupil_size(msg.pupil_size)
        self.set_curvature(msg.curvature)
        self.set_vein_count(msg.vein_count)
        self.set_vein_seed(msg.vein_seed)

    def set_text(self, msgType: TextType, text: str) -> None:
        self.pending_text_type = msgType
        self.pending_text = text

    def run(self) -> None:
        print("[Renderer] running app")
        pyglet.app.run()

    def shutdown(self) -> None:
        print("[Renderer] shutdown")
        self.window.close()
        pyglet.app.exit()        

    ###############################################################################
    #
    ###############################################################################
    def build_program(self) -> ShaderProgram:
        ROOT = Path(__file__).resolve().parent
        self.vert_path = ROOT / "shaders" / "eye.vert"
        self.frag_path = ROOT / "shaders" / "eye.frag"
        vert_src = self.vert_path.read_text(encoding="utf-8")
        frag_src = self.frag_path.read_text(encoding="utf-8")

        return ShaderProgram(
            Shader(vert_src, "vertex"),
            Shader(frag_src, "fragment"),
        )

    def init_geometry(self) -> None:
        quad = [
            -1.0,
            -1.0,
            1.0,
            -1.0,
            1.0,
            1.0,
            -1.0,
            -1.0,
            1.0,
            1.0,
            -1.0,
            1.0,
        ]

        gl.glGenBuffers(1, ctypes.byref(self._vbo))
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo)
        data = (gl.GLfloat * len(quad))(*quad)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, ctypes.sizeof(data), data, gl.GL_STATIC_DRAW)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glGenVertexArrays(1, ctypes.byref(self._vao))

    def bind_geometry_to_program(self, prog: ShaderProgram) -> None:
        gl.glBindVertexArray(self._vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo)

        pos_loc = prog.attributes["position"]["location"]
        gl.glEnableVertexAttribArray(pos_loc)
        gl.glVertexAttribPointer(pos_loc, 2, gl.GL_FLOAT, gl.GL_FALSE, 0, ctypes.c_void_p(0))

        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glBindVertexArray(0)

    def reload_shaders(self) -> None:
        try:
            new_prog = self.build_program()
            self.bind_geometry_to_program(new_prog)
            old_prog = self._program
            self._program = new_prog
            if old_prog is not None:
                old_prog.delete()
            print("Shaders reloaded.")
        except Exception as e:
            print(f"Shader compile/link failed: {e}")

    ###############################################################################
    # Handlers
    ###############################################################################

    def _on_key_press(self, symbol, modifiers):       
        if symbol == pyglet.window.key.R:
            self.reload_shaders()       

    def _update(self, dt: float) -> None:
        self.window.invalid = True
  
    def _on_draw(self):
        self.window.clear()

        if self.pending_text:
            self.text_label.color = (255, 80, 80, 255) if self.pending_text_type == TextType.ERROR else (225, 225, 225, 255)
            self.text_label.x = self.window.width // 2
            self.text_label.y = self.window.height // 2
            self.text_label.width = self.window.width
            self.text_label.text = self.pending_text
            self.text_label.draw()
            return

        if self._program is None:
            return

        prog = self._program
        prog.use()
      
        prog["iTime"] = float(time.monotonic() - self._start_time)
        prog["iResolution"] = (float(self.window.width), float(self.window.height))
        prog["radius"] = self.radius
        prog["curved"] = self.curvature
        prog["irisSize"] = self.iris_size
        prog["pupilSize"] = self.pupil_size
        prog["numVeins"] = float(self.vein_count)
        prog["veinSeed"] = float(self.vein_seed)
        prog["eyeLidPosition"] = self.eye_lid_position
        prog["rotation"] = float(self.rotation_deg)
        prog["irisColor"] = self.iris_color
        prog["irisAccentColor"] = self.iris_accent_color
        prog["irisCenterColor"] = self.iris_center_color
        prog["striationColor"] = self.striation_color
        prog["pupilColor"] = self.pupil_color
        prog["scleraColor"] = self.sclera_color
        prog["veinColor"] = self.vein_color
        prog["isCatEye"] = self.is_cat_eye

        gl.glBindVertexArray(self._vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
        gl.glBindVertexArray(0)

        prog.stop()

###############################################################################
# Helpers
###############################################################################

def clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def rgb255_to_normalized(r: int, g: int, b: int) -> tuple[float, float, float]:
    return tuple(clamp01(x / 255.0) for x in (r, g, b))


###############################################################################
# Main : for testing only with default parameters and no programic input.
###############################################################################
if __name__ == "__main__":
    eye = EyeRenderer()
    try:
        eye.run()
    except KeyboardInterrupt:
        pass
