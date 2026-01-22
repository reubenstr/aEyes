#!/usr/bin/env python3
"""
Raspberry Pi shader demo using pyglet (often runs via XWayland in a Wayland session).

What this file does:
- Requests an OpenGL ES context (tries 3.1 -> 3.0 -> 2.0).
- Compiles a simple full-screen fragment shader.
- Animates with a u_time uniform and uses u_resolution (kept "live" via gl_FragCoord).

Notes:
- On many Wayland desktops, pyglet uses X11/XWayland. If you have no XWayland, pyglet may fail.
- Requires pyglet >= 2.0.
"""

import ctypes
import time

import pyglet

# Important for many GLES environments (including Raspberry Pi):
pyglet.options.shadow_window = False

from pyglet import gl
from pyglet.graphics.shader import Shader, ShaderProgram


def gl_string(name) -> str:
    """Safely fetch a GL string (ctypes pointer -> Python str)."""
    p = gl.glGetString(name)
    if not p:
        return "<null>"
    return ctypes.string_at(p).decode("utf-8", errors="replace")


def create_window():
    """Try to create a pyglet window with a GLES context. Falls back by version."""
    display = pyglet.display.get_display()
    screen = display.get_default_screen()

    base = screen.get_best_config()

    # Try a few GLES versions, highest first.
    for major, minor in [(3, 1), (3, 0), (2, 0)]:
        try:
            cfg = base
            cfg.opengl_api = "gles"
            cfg.major_version = major
            cfg.minor_version = minor

            win = pyglet.window.Window(
                width=960,
                height=540,
                caption=f"pyglet GLES {major}.{minor} shader demo (Pi)",
                resizable=True,
                config=cfg,
                vsync=True,
            )
            return win
        except Exception as e:
            last = e

    raise RuntimeError(f"Could not create any GLES context. Last error: {last!r}")


window = create_window()

print("XDG_SESSION_TYPE:", __import__("os").environ.get("XDG_SESSION_TYPE"))
print("WAYLAND_DISPLAY :", __import__("os").environ.get("WAYLAND_DISPLAY"))
print("DISPLAY         :", __import__("os").environ.get("DISPLAY"))
print("GL_VERSION      :", gl_string(gl.GL_VERSION))
print("GL_RENDERER     :", gl_string(gl.GL_RENDERER))
print("GL_VENDOR       :", gl_string(gl.GL_VENDOR))
print("GLSL            :", gl_string(gl.GL_SHADING_LANGUAGE_VERSION))

# Full-screen triangle (clip-space)
POSITIONS = (
    -1.0, -1.0,
     3.0, -1.0,
    -1.0,  3.0
)

# GLES 3.0 shaders. (Works for GLES 3.x contexts.)
VERTEX_SRC = """
#version 300 es
precision mediump float;

in vec2 position;
out vec2 v_uv;

void main() {
    v_uv = position * 0.5 + 0.5;
    gl_Position = vec4(position, 0.0, 1.0);
}
"""

FRAG_SRC = """
#version 300 es
precision mediump float;

in vec2 v_uv;
out vec4 fragColor;

uniform float u_time;
uniform vec2  u_resolution;

void main() {
    // Make u_resolution definitely "live" so it isn't optimized out:
    vec2 frag = gl_FragCoord.xy / max(u_resolution, vec2(1.0));

    float t = u_time;
    float wave = 0.5 + 0.5 * sin(10.0 * frag.x + t) * cos(10.0 * frag.y + t * 0.7);

    // Color is based on normalized pixel coords + wave
    vec3 col = vec3(frag.x, frag.y, wave);

    // Simple vignette
    vec2 p = frag * 2.0 - 1.0;
    float v = smoothstep(1.2, 0.2, dot(p, p));
    col *= v;

    fragColor = vec4(col, 1.0);
}
"""

program = ShaderProgram(
    Shader(VERTEX_SRC, "vertex"),
    Shader(FRAG_SRC, "fragment"),
)

# Print active uniforms so you can confirm names the driver kept:
try:
    print("Active uniforms:", list(program.uniforms.keys()))
except Exception:
    # Not critical if pyglet internals differ slightly across versions
    pass

tri = program.vertex_list(
    3,
    gl.GL_TRIANGLES,
    position=("f", POSITIONS),
)

DRAW_MODE = gl.GL_TRIANGLES
start = time.perf_counter()


def set_uniform_safe(prog, name, value):
    """Avoid crashing while iterating on shaders; comment this out if you prefer hard fail."""
    try:
        prog[name] = value
    except Exception:
        pass


@window.event
def on_draw():
    window.clear()

    now = time.perf_counter() - start
    set_uniform_safe(program, "u_time", float(now))
    set_uniform_safe(program, "u_resolution", (float(window.width), float(window.height)))

    # pyglet 2.x requires the mode here:
    tri.draw(DRAW_MODE)


@window.event
def on_key_press(symbol, modifiers):
    if symbol == pyglet.window.key.ESCAPE:
        pyglet.app.exit()


if __name__ == "__main__":
    pyglet.app.run()
