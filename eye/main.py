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

# ------------------------------------------------------------
# Noise texture generation + upload (Shadertoy-style iChannel0)
# ------------------------------------------------------------

NOISE_SIZE = 256
noise_tex = gl.GLuint(0)

def _xorshift32(seed: int):
    """Simple deterministic PRNG (fast, no numpy required)."""
    x = seed & 0xFFFFFFFF
    while True:
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= (x >> 17) & 0xFFFFFFFF
        x ^= (x << 5) & 0xFFFFFFFF
        yield x

def create_noise_texture_rgba8(size: int = 256, seed: int = 12345) -> int:
    """
    Creates a GL_TEXTURE_2D RGBA8 noise texture.
    We'll fill RGBA with random-ish bytes; shader can read .yx like Shadertoy.
    """
    global noise_tex

    # Create byte buffer: size*size pixels * 4 channels
    gen = _xorshift32(seed)
    data = bytearray(size * size * 4)
    for i in range(0, len(data), 4):
        r = next(gen) & 0xFF
        g = (next(gen) >> 8) & 0xFF
        b = (next(gen) >> 16) & 0xFF
        a = 255
        data[i + 0] = r
        data[i + 1] = g
        data[i + 2] = b
        data[i + 3] = a

    # Upload to GPU
    tex = gl.GLuint(0)
    gl.glGenTextures(1, ctypes.byref(tex))
    gl.glBindTexture(gl.GL_TEXTURE_2D, tex)

    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)

    # Ensure tight packing
    gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)

    # Upload RGBA8
    buf = (gl.GLubyte * len(data)).from_buffer(data)
    gl.glTexImage2D(
        gl.GL_TEXTURE_2D,
        0,
        gl.GL_RGBA8,
        size,
        size,
        0,
        gl.GL_RGBA,
        gl.GL_UNSIGNED_BYTE,
        buf
    )

    gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
    noise_tex = tex
    return int(tex.value)

# Create once (after window/context exists)
create_noise_texture_rgba8(NOISE_SIZE, seed=1337)

# ------------------------------------------------------------
# Fullscreen quad
# ------------------------------------------------------------

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

# VAO
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
pupil_size = 1.0
pupil_size_change = 0.01

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

    # Bind noise texture to unit 0 (even if shader doesn't use it, it's harmless)
    gl.glActiveTexture(gl.GL_TEXTURE0)
    gl.glBindTexture(gl.GL_TEXTURE_2D, noise_tex)

    program.use()

    t = time.time() - start
    program["iTime"] = t
    program["iResolution"] = (float(window.width), float(window.height))
    program["rAmp"] = zoom
    program["blink"] = float(blink_value)
    program["pupilSize"] = pupil_size

    # Only set if the shader actually declares it
    if "iChannel0" in program.uniforms:
        program["iChannel0"] = 0

    gl.glBindVertexArray(vao)
    gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
    gl.glBindVertexArray(0)

    program.stop()

    # Unbind texture (optional hygiene)
    gl.glBindTexture(gl.GL_TEXTURE_2D, 0)

pyglet.app.run()
