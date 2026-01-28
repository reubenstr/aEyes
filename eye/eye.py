import time
import ctypes
import math
from dataclasses import dataclass
from pathlib import Path

import pyglet

# IMPORTANT: set options BEFORE importing pyglet.gl or pyglet.graphics.shader
pyglet.options.shadow_window = False
pyglet.options["backend"] = "egl"   # Raspberry Pi EGL

from pyglet import gl
from pyglet.graphics.shader import Shader, ShaderProgram


def srgb_to_linear(c: float) -> float:
    return c ** 2.2  # approximation

def rgb255_srgb_to_linear(r: int, g: int, b: int) -> tuple[float, float, float]:
    return tuple(srgb_to_linear(x / 255.0) for x in (r, g, b))


@dataclass
class EyeControls:
    rAmp: float = 0.2
    rotation_deg: float = 0.0
    blink: float = 0.0
    pupil_size: float = 1.0
    iris_color: tuple[float, float, float] = rgb255_srgb_to_linear(0, 255, 0)
    cornea_color: tuple[float, float, float] = rgb255_srgb_to_linear(255, 0, 0)
    isCatEye: bool = False


class EyeRenderer:
    def __init__(
        self,
        vert_path: Path,
        frag_path: Path,
        size: tuple[int, int] = (720, 720),       
        update_hz: float = 60.0,
        gles_major: int = 3,
        gles_minor: int = 1,
    ):
        self.vert_path = vert_path
        self.frag_path = frag_path
        self.controls = EyeControls()

        self._program: ShaderProgram | None = None
        self._last_compile_error: str | None = None

        self._vao = gl.GLuint(0)
        self._vbo = gl.GLuint(0)

        self._start_time = time.time()
  
        # blink scheduling state
        self._blink_start_t: float | None = None
        self._next_blink_t: float = 3.0

        # ---- create window + config here ----
        display = pyglet.display.get_display()
        screen = display.get_default_screen()
        config = screen.get_best_config()
        config.opengl_api = "gles"
        config.major_version = gles_major
        config.minor_version = gles_minor

        self.window = pyglet.window.Window(
            fullscreen=True,        
            resizable=True,
            config=config
        )

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
      
        # attach handlers (no decorators needed)     
        self.window.on_draw = self._on_draw
        self.window.on_key_press = self._on_key_press

        # GL resources + shaders
        self._init_geometry()
        self.reload_shaders()

        # schedule update
        pyglet.clock.schedule_interval(self.update, 1.0 / update_hz)

    # -------- public API (for your future control class) --------
    def set_rAmp(self, v: float) -> None:
        self.controls.rAmp = float(v)

    def set_rotation_deg(self, v: float) -> None:
        self.controls.rotation_deg = float(v)

    def set_iris_color_rgb255(self, r: int, g: int, b: int) -> None:
        self.controls.iris_color = rgb255_srgb_to_linear(r, g, b)

    def set_cornea_color_rgb255(self, r: int, g: int, b: int) -> None:
        self.controls.cornea_color = rgb255_srgb_to_linear(r, g, b)

    def set_is_cat_eye(self, value: bool) -> None:
        self.controls.isCatEye = bool(value)

    def trigger_blink(self) -> None:
        self._blink_start_t = self.now()

    def set_message(self, text: str) -> None:
        self.pending_text = text

    def now(self) -> float:
        return time.time() - self._start_time

    def run(self) -> None:
        pyglet.app.run()

    # -------- internal: geometry/shaders --------
    def _build_program(self) -> ShaderProgram:
        vert_src = self.vert_path.read_text(encoding="utf-8")
        frag_src = self.frag_path.read_text(encoding="utf-8")

        return ShaderProgram(
            Shader(vert_src, "vertex"),
            Shader(frag_src, "fragment"),
    )

    def _init_geometry(self) -> None:
        quad = [
            -1.0, -1.0,
             1.0, -1.0,
             1.0,  1.0,
            -1.0, -1.0,
             1.0,  1.0,
            -1.0,  1.0,
        ]

        gl.glGenBuffers(1, ctypes.byref(self._vbo))
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo)
        data = (gl.GLfloat * len(quad))(*quad)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, ctypes.sizeof(data), data, gl.GL_STATIC_DRAW)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)

        gl.glGenVertexArrays(1, ctypes.byref(self._vao))

    def _bind_geometry_to_program(self, prog: ShaderProgram) -> None:
        gl.glBindVertexArray(self._vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo)
       
        pos_loc = prog.attributes["position"]["location"]
        gl.glEnableVertexAttribArray(pos_loc)
        gl.glVertexAttribPointer(pos_loc, 2, gl.GL_FLOAT, gl.GL_FALSE, 0, ctypes.c_void_p(0))

        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glBindVertexArray(0)

    def reload_shaders(self) -> None:
        try:
            new_prog = self._build_program()
            self._bind_geometry_to_program(new_prog)
            self._program = new_prog
            self._last_compile_error = None
            print("✅ Shaders reloaded.")
        except Exception as e:
            self._last_compile_error = str(e)
            print("❌ Shader compile/link failed:\n", self._last_compile_error)

    # -------- internal: blink/update --------
    @staticmethod
    def _blink_envelope(t: float) -> float:
        close_d = 0.5
        open_d = 0.5
        total = close_d + open_d

        if t < 0.0:
            return 0.0
        if t < close_d:
            x = t / close_d
            return x * x * (3 - 2 * x)
        if t < total:
            x = (t - close_d) / open_d
            return 1.0 - (x * x * (3 - 2 * x))
        return 0.0

    def update(self, dt: float) -> None:
        now = self.now()

        # auto-blink
        if now >= self._next_blink_t:
            self._blink_start_t = now
            jitter = 0.5 + 0.5 * math.sin(now * 12.345)
            self._next_blink_t = now + 2.5 + 2.5 * jitter

        if self._blink_start_t is not None:
            self.controls.blink = self._blink_envelope(now - self._blink_start_t)
            if self.controls.blink <= 0.0 and (now - self._blink_start_t) > 0.25:
                self._blink_start_t = None
        else:
            self.controls.blink = 0.0
       
    # -------- internal: events --------
    def _on_key_press(self, symbol, modifiers):
        if symbol == pyglet.window.key.SPACE:
            self.trigger_blink()
        elif symbol == pyglet.window.key.R:
            self.reload_shaders()
        elif symbol == pyglet.window.key.A:
            self.controls.rAmp += 0.2
        elif symbol == pyglet.window.key.D:
            self.controls.rAmp -= 0.2
        elif symbol == pyglet.window.key.Q:
            self.controls.rotation_deg += 1.0
        elif symbol == pyglet.window.key.W:
            self.controls.rotation_deg -= 1.0

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
        
        prog["iTime"] = self.now()
        prog["iResolution"] = (float(self.window.width), float(self.window.height))
        prog["rAmp"] = float(self.controls.rAmp)
        prog["blink"] = float(self.controls.blink)
        prog["rotation"] = float(self.controls.rotation_deg)
        prog["irisColor"] = self.controls.iris_color
        prog["corneaColor"] = self.controls.cornea_color
        prog["isCatEye"] = self.controls.isCatEye
   
        gl.glBindVertexArray(self._vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
        gl.glBindVertexArray(0)

        prog.stop()


if __name__ == "__main__":
    ROOT = Path(__file__).resolve().parent
    app = EyeRenderer(
        vert_path=ROOT / "shaders" / "eye.vert",
        frag_path=ROOT / "shaders" / "eye.frag",     
        update_hz=60.0,
    )
    app.run()
