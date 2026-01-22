import time
import ctypes
import math
from pathlib import Path

import pyglet
from pyglet import gl
from pyglet.graphics.shader import Shader, ShaderProgram

ROOT = Path(__file__).resolve().parent
VERT_PATH = ROOT / "shaders" / "eye.vert"
FRAG_PATH = ROOT / "shaders" / "eye.frag"

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def build_program() -> ShaderProgram:
    vert_src = read_text(VERT_PATH)
    frag_src = read_text(FRAG_PATH)
    return ShaderProgram(
        Shader(vert_src, "vertex"),
        Shader(frag_src, "fragment"),
    )

window = pyglet.window.Window(800, 800, "Eye + Blink (file-based GLSL)", resizable=True)

# Fullscreen quad
quad = [
    -1.0, -1.0,
     1.0, -1.0,
     1.0,  1.0,
    -1.0, -1.0,
     1.0,  1.0,
    -1.0,  1.0,
]

# VBO
vbo = gl.GLuint(0)
gl.glGenBuffers(1, ctypes.byref(vbo))
gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
data = (gl.GLfloat * len(quad))(*quad)
gl.glBufferData(gl.GL_ARRAY_BUFFER, ctypes.sizeof(data), data, gl.GL_STATIC_DRAW)

# VAO (we’ll recreate VAO attribute binding on reload, since location can change)
vao = gl.GLuint(0)
gl.glGenVertexArrays(1, ctypes.byref(vao))

program = None
last_compile_error = None

def bind_geometry_to_program(prog: ShaderProgram):
    """Bind VBO -> VAO using the attribute location for this program."""
    gl.glBindVertexArray(vao)
    gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)

    pos_loc = prog.attributes["position"]["location"]
    gl.glEnableVertexAttribArray(pos_loc)
    gl.glVertexAttribPointer(pos_loc, 2, gl.GL_FLOAT, gl.GL_FALSE, 0, ctypes.c_void_p(0))

    gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
    gl.glBindVertexArray(0)

def reload_shaders():
    """Compile/link shaders from files; keep running if compile fails."""
    global program, last_compile_error
    try:
        new_prog = build_program()
        bind_geometry_to_program(new_prog)
        program = new_prog
        last_compile_error = None
        print("✅ Shaders reloaded.")
    except Exception as e:
        last_compile_error = str(e)
        print("❌ Shader compile/link failed:\n", last_compile_error)

reload_shaders()

start = time.time()

# Blink controller
blink_value = 0.0
blink_start_t = None
next_blink_t = 1.5

# Pupil Size Control
pupil_size = 1.0  # Initial value
pupil_size_change = 0.01  # Rate of change

zoom = 0.2

def trigger_blink(now_t: float):
    global blink_start_t
    blink_start_t = now_t

def blink_envelope(t: float) -> float:
    close_d = 0.06
    open_d = 0.10
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

def update(dt):
    global blink_value, blink_start_t, next_blink_t
    global pupil_size, pupil_size_change
    now = time.time() - start

    if now >= next_blink_t:
        trigger_blink(now)
        jitter = 0.5 + 0.5 * math.sin(now * 12.345)
        next_blink_t = now + 2.5 + 2.5 * jitter

    if blink_start_t is not None:
        blink_value = blink_envelope(now - blink_start_t)
        if blink_value <= 0.0 and (now - blink_start_t) > 0.25:
            blink_start_t = None
    else:
        blink_value = 0.0
 
    pupil_size = max(0.1, min(pupil_size, 1.0)) 

pyglet.clock.schedule_interval(update, 1 / 120.0)

@window.event
def on_key_press(symbol, modifiers):
    global zoom
    if symbol == pyglet.window.key.SPACE:
        trigger_blink(time.time() - start)
    if symbol == pyglet.window.key.R:
        reload_shaders()
    if symbol == pyglet.window.key.A:
        zoom += 0.2
    if symbol == pyglet.window.key.D:
        zoom -= 0.2

@window.event
def on_draw():
    global zoom
    window.clear()

    if program is None:
        return

    program.use()

    t = time.time() - start
    program["iTime"] = t
    program["iResolution"] = (float(window.width), float(window.height))
    program["rAmp"] = zoom
    program["blink"] = float(blink_value)
    program["pupilSize"] = pupil_size 

    gl.glBindVertexArray(vao)
    gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
    gl.glBindVertexArray(0)

    program.stop()

pyglet.app.run()
