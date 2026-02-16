import time
import ctypes
from pathlib import Path

import pyglet
# IMPORTANT: set options BEFORE importing pyglet.gl or pyglet.graphics.shader
pyglet.options.shadow_window = False
pyglet.options["backend"] = "egl"  # Raspberry Pi EGL
from pyglet import gl
from pyglet.graphics.shader import Shader, ShaderProgram


class EyeRenderer:
    def __init__(self): 

        # Render controls
        self.radius: float = 0.2
        self.rotation_deg: float = 0.0
        self.eye_lid_position: float = 0.0
        self.iris_color: tuple[float, float, float] = rgb255_srgb_to_linear(0, 255, 0)
        self.cornea_color: tuple[float, float, float] = rgb255_srgb_to_linear(255, 0, 0)
        self.is_cat_eye: bool = False

        self._program: ShaderProgram | None = None
        self._vao = gl.GLuint(0)
        self._vbo = gl.GLuint(0)   

        # Window configuration.
        display = pyglet.display.get_display()
        screen = display.get_default_screen()
        config = screen.get_best_config()
        config.opengl_api = "gles"
        config.major_version = 3
        config.minor_version = 1

        self.window = pyglet.window.Window(fullscreen=True, resizable=True, config=config)

        self.pending_text = None
        self.message_label = pyglet.text.Label(
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

    ###############################################################################
    # API
    ###############################################################################
    def set_radius(self, v: float) -> None:
        self.radius = float(v)

    def set_rotation_deg(self, v: float) -> None:
        self.rotation_deg = float(v)

    def set_eye_lid_position(self, v: float) -> None:
        self.eye_lid_position = float(v)
  
    def set_iris_color_rgb255(self, rgb: tuple[int, int, int]) -> None:
        self.iris_color = rgb255_srgb_to_linear(*rgb)

    def set_cornea_color_rgb255(self, rgb: tuple[int, int, int]) -> None:
        self.cornea_color = rgb255_srgb_to_linear(*rgb)

    def set_is_cat_eye(self, value: bool) -> None:
        self.is_cat_eye = bool(value)

    def set_message(self, msgType: str,  text: str) -> None:
        if msgType == 'error':
            self.message_label.color = color=(255, 80, 80, 255)
        else:
            self.message_label.color = color=(225, 225, 225, 255)
        self.pending_text = text

    def run(self) -> None:
        print("[Renderer] running app")
        pyglet.app.run()

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
            self._program = new_prog
            print("Shaders reloaded.")
        except Exception as e:
            print("Shader compile/link failed")

    ###############################################################################
    # Handlers
    ###############################################################################

    def _on_key_press(self, symbol, modifiers):       
        if symbol == pyglet.window.key.R:
            self.reload_shaders()       

    def _on_draw(self):
        self.window.clear()

        if self.pending_text:
            self.message_label.text = self.pending_text
            self.message_label.draw()
            return

        if self._program is None:
            return

        prog = self._program
        prog.use()

        prog["iTime"] = time.time()
        prog["iResolution"] = (float(self.window.width), float(self.window.height))
        prog["radius"] = float(self.radius)
        prog["eyeLidPosition"] = self.eye_lid_position
        prog["rotation"] = float(self.rotation_deg)
        prog["irisColor"] = self.iris_color
        prog["corneaColor"] = self.cornea_color
        prog["isCatEye"] = self.is_cat_eye

        gl.glBindVertexArray(self._vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
        gl.glBindVertexArray(0)

        prog.stop()

###############################################################################
# Helpers
###############################################################################

@staticmethod
def srgb_to_linear(c: float) -> float:
    return c ** 2.2  # approximation

@staticmethod
def rgb255_srgb_to_linear(r: int, g: int, b: int) -> tuple[float, float, float]:
    return tuple(srgb_to_linear(x / 255.0) for x in (r, g, b))


###############################################################################
# Main : for testing only with default parameters and no programic input.
###############################################################################
if __name__ == "__main__":
    eye = EyeRenderer()
    try:
        eye.run()
    except KeyboardInterrupt:
        pass
