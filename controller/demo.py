"""Synthetic project-frame detections for ``main.py --demo``.

The controller owns timing, tracking, publication and monitoring. This module has
no camera, rendering or network dependencies.
"""

import math

from data_types import Detection, Position3D


def get_detections(frame: int) -> list[Detection]:
    """Return the set of Detection objects for a given frame number.

    All positions stay within: x[1, 3], y[-2.0, 2.0], z[-1.0, 1.0].
    """
    t = frame * 0.05

    face_a = Detection(position=Position3D(
        x=1.5 + 0.3 * math.sin(t),
        y=0.0 + 0.4 * math.cos(t),
        z=0.0 + 0.3 * math.sin(t * 0.5),
    ))
    face_b = Detection(position=Position3D(
        x=2.2 + 0.4 * math.cos(t * 0.7),
        y=0.8 + 0.5 * math.sin(t * 0.9),
        z=-0.3 + 0.4 * math.sin(t * 0.3),
    ))
    face_c = Detection(position=Position3D(
        x=1.2 + 0.15 * math.sin(t * 1.3),
        y=-1.0 + 0.5 * math.cos(t * 0.6),
        z=0.5 + 0.3 * math.sin(t * 0.4),
    ))
    face_d = Detection(position=Position3D(
        x=2.7 + 0.25 * math.sin(t * 0.8),
        y=0.0 + 0.6 * math.cos(t * 1.1),
        z=-0.5 + 0.3 * math.sin(t * 0.7),
    ))
    face_e = Detection(position=Position3D(
        x=1.8 + 0.3 * math.sin(t * 1.5),
        y=-0.5 + 0.4 * math.cos(t * 1.2),
        z=0.2 + 0.3 * math.sin(t * 0.8),
    ))
    face_static = Detection(position=Position3D(
        x=1.5,
        y=0.4,
        z=0.3,
    ))

    if frame < 10:
        return [face_static, face_a, face_b, face_c, face_d]
    elif frame < 20:
        return [face_static, face_b, face_c, face_d]
    elif frame < 30:
        return [face_static, face_b, face_c, face_d, face_e]
    elif frame < 40:
        return [face_static, face_b, face_d, face_e]
    elif frame < 100:
        return [face_static, face_b, face_a]
    elif frame < 130:
        return [face_static, face_b]
    else:
        return [face_static, face_b, face_a]
