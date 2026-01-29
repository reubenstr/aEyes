def lerp(a, b, t):
        return a + (b - a) * t
def lerp_rgb(c0, c1, t):
    return tuple(lerp(c0[i], c1[i], t) for i in range(3))

def smoothstep(t):
    return t * t * (3 - 2 * t)

def srgb_to_linear(c: float) -> float:
    return c ** 2.2  # approximation

def rgb255_srgb_to_linear(r: int, g: int, b: int) -> tuple[float, float, float]:
    return tuple(srgb_to_linear(x / 255.0) for x in (r, g, b))