from typing import Tuple

def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

def lerp_rgb(
    c0: Tuple[float, float, float],
    c1: Tuple[float, float, float],
    t: float
) -> Tuple[float, float, float]:
    return tuple(lerp(c0[i], c1[i], t) for i in range(3))

def smoothstep(t: float) -> float:
    return t * t * (3 - 2 * t)

def srgb_to_linear(c: float) -> float:
    return c ** 2.2  # approximation

def rgb255_srgb_to_linear(r: int, g: int, b: int) -> Tuple[float, float, float]:
    return tuple(srgb_to_linear(x / 255.0) for x in (r, g, b))