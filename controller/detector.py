from __future__ import annotations

import argparse
import time
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import cv2

from data_types import Detection, Position3D, ControlMessage
from face_tracker import FaceTracker
from eye_manager import EyeManager
from config import EYE_CONFIGS, CAMERA_CONFIG
from publisher import Publisher

"""
    Face detections using Luxonis Oak-D Pro W depth camera.
"""

@dataclass
class FaceDetection:
    score: float
    bbox_xyxy: np.ndarray  # shape (4,) float32 in full color coords (640x480)




def _draw_detections(
    frame_bgr: np.ndarray,
    dets: List[FaceDetection],
    xyzs: List[Optional[Tuple[float, float, float]]],
) -> np.ndarray:
    """Draw bounding boxes (and optional XYZ labels) onto a copy of frame_bgr."""
    out = frame_bgr.copy()
    for det, xyz in zip(dets, xyzs):
        x1, y1, x2, y2 = det.bbox_xyxy.astype(int)
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)

        label = f"{det.score:.2f}"
        if xyz is not None:
            label += f"  {xyz[0]:.2f},{xyz[1]:.2f},{xyz[2]:.2f}m"

        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        ty = max(y1 - 4, th + 2)
        cv2.rectangle(out, (x1, ty - th - 2), (x1 + tw + 2, ty + 2), (0, 255, 0), -1)
        cv2.putText(
            out, label, (x1 + 1, ty),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA,
        )
    return out


class Detector:
    def __init__(self):
        pass

    def run_display(self):       

        try:
            while True:               

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
        finally:
            cv2.destroyAllWindows()

    def shutdown(self):
      pass


# ------------------------------------------------------------------ #
#  CLI entry-point                                                     #
# ------------------------------------------------------------------ #

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="")
    p.add_argument(
        "--display",
        action="store_true",
        default=False,
        help="Open an OpenCV window showing the live stream with bounding boxes.",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    detector = Detector()
    try:
        if args.display:
            detector.run_display()
        else:
            # Headless loop — print all detections each frame.
            frame_idx = 0
            while True:
                color_bgr, depth_u16, intr = detector.cam.get_aligned_frames()
                if color_bgr is None:
                    continue
                dets, _ = detector.det.detect(color_bgr)
                xyzs = [detector.cam.face_xyz(depth_u16, intr, f.bbox_xyxy) for f in dets]
                frame_idx += 1
                if frame_idx % PRINT_EVERY_N_FRAMES == 0:
                    print(f"[frame {frame_idx}] {len(dets)} face(s)")
                    for i, (f, xyz) in enumerate(zip(dets[:PRINT_TOP_K], xyzs[:PRINT_TOP_K])):
                        print(f"  [{i}] score={f.score:.3f}  xyz={xyz}")
    finally:
        detector.shutdown()