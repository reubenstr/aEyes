
def srgb_to_linear(c: float) -> float:
    return c ** 2.2  # approximation

def rgb255_srgb_to_linear(r: int, g: int, b: int) -> tuple[float, float, float]:
    return tuple(srgb_to_linear(x / 255.0) for x in (r, g, b))


def crc16_ccitt(data: bytes) -> int:
    """Calculate CRC16-CCITT checksum"""
    crc = 0xFFFF
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            crc = (crc << 1) ^ 0x1021 if (crc & 0x8000) else crc << 1
            crc &= 0xFFFF
    return crc