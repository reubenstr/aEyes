from __future__ import annotations

import argparse
import cv2
import numpy as np
import depthai as dai
from blobconverter import from_zoo
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import time 


PRINT_EVERY_N_FRAMES = 30
PRINT_TOP_K = 4
RGB_WIDTH = 640
RGB_HEIGHT = 480
NN_WIDTH = 300
NN_HEIGHT = 300
DEPTH_MM_MIN = 100
DEPTH_MM_MAX = 10000
DEFAULT_CONFIDENCE = 0.55
MODEL_NAME = "face-detection-retail-0004"


@dataclass
class FaceDetection:
    score: float
    bbox_xyxy: np.ndarray  # shape (4,) float32 in full color coords (640x480)


def _draw_detections(
    frame_bgr: np.ndarray,
    dets: List[FaceDetection],
    xyzs: List[Optional[Tuple[float, float, float]]],
) -> np.ndarray:
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
        cv2.putText(out, label, (x1 + 1, ty),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return out


class Detector:
    def __init__(self, confidence: float = DEFAULT_CONFIDENCE) -> None:
        self._device = dai.Device(self._build_pipeline(confidence))
        self._rgb_queue = self._device.getOutputQueue(name="rgb", maxSize=4, blocking=False)
        self._depth_queue = self._device.getOutputQueue(name="depth", maxSize=4, blocking=False)
        self._det_queue = self._device.getOutputQueue(name="detections", maxSize=4, blocking=False)

        # Removed confusing aliases
        # self.cam = self
        # self.det = self

        self._last_color: Optional[np.ndarray] = None
        self._last_depth: Optional[np.ndarray] = None
        self._last_intrinsics: Optional[Dict[str, float]] = None

    def _build_pipeline(self, confidence: float) -> dai.Pipeline:
        blob_path = from_zoo(name=MODEL_NAME, zoo_type="depthai", shaves=6)

        pipeline = dai.Pipeline()

        cam = pipeline.createColorCamera()
        cam.setBoardSocket(dai.CameraBoardSocket.RGB)
        cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
        cam.setVideoSize(RGB_WIDTH, RGB_HEIGHT)
        cam.setPreviewSize(NN_WIDTH, NN_HEIGHT)
        cam.setInterleaved(False)
        cam.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)

        left = pipeline.createMonoCamera()
        left.setBoardSocket(dai.CameraBoardSocket.LEFT)
        left.setResolution(dai.MonoCameraProperties.SensorResolution.THE_720_P)

        right = pipeline.createMonoCamera()
        right.setBoardSocket(dai.CameraBoardSocket.RIGHT)
        right.setResolution(dai.MonoCameraProperties.SensorResolution.THE_720_P)

        stereo = pipeline.createStereoDepth()
        stereo.setConfidenceThreshold(200)
        stereo.setDepthAlign(dai.CameraBoardSocket.RGB)
        stereo.setOutputDepth(True)
        left.out.link(stereo.left)
        right.out.link(stereo.right)

        nn = pipeline.createMobileNetSpatialDetectionNetwork()
        nn.setBlobPath(blob_path)
        nn.setConfidenceThreshold(confidence)
        nn.setBoundingBoxScaleFactor(0.3)
        nn.setDepthLowerThreshold(DEPTH_MM_MIN)
        nn.setDepthUpperThreshold(DEPTH_MM_MAX)
        cam.preview.link(nn.input)
        stereo.depth.link(nn.inputDepth)

        xout_rgb = pipeline.createXLinkOut()
        xout_rgb.setStreamName("rgb")
        cam.video.link(xout_rgb.input)

        xout_depth = pipeline.createXLinkOut()
        xout_depth.setStreamName("depth")
        stereo.depth.link(xout_depth.input)

        xout_detections = pipeline.createXLinkOut()
        xout_detections.setStreamName("detections")
        nn.out.link(xout_detections.input)

        return pipeline

    def get_aligned_frames(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[Dict[str, float]]]:
        rgb_frame = self._rgb_queue.tryGetLatest()
        depth_frame = self._depth_queue.tryGetLatest()

        if rgb_frame is not None:
            self._last_color = rgb_frame.getCvFrame()

            # <<< changed: request intrinsics for the resized video stream
            try:
                intr = rgb_frame.getCameraIntrinsics(RGB_WIDTH, RGB_HEIGHT)
                self._last_intrinsics = {
                    "fx": float(intr[0][0]),
                    "fy": float(intr[1][1]),
                    "ppx": float(intr[0][2]),
                    "ppy": float(intr[1][2]),
                }
            except Exception:
                self._last_intrinsics = None

        if depth_frame is not None:
            self._last_depth = depth_frame.getCvFrame()  # <<< changed

        return self._last_color, self._last_depth, self._last_intrinsics

    def detect(self) -> Tuple[List[FaceDetection], Optional[np.ndarray]]:
        det_packet = self._det_queue.tryGetLatest()
        if det_packet is None:
            return [], None

        detections: List[FaceDetection] = []
        for det in det_packet.detections:
            x1 = int(det.xmin * RGB_WIDTH)
            y1 = int(det.ymin * RGB_HEIGHT)
            x2 = int(det.xmax * RGB_WIDTH)
            y2 = int(det.ymax * RGB_HEIGHT)

            detections.append(
                FaceDetection(
                    score=float(det.confidence),
                    bbox_xyxy=np.array([x1, y1, x2, y2], dtype=np.float32),
                )
            )

        return detections, None

    @staticmethod
    def face_xyz(
        depth_u16: Optional[np.ndarray],
        intr: Optional[Dict[str, float]],
        bbox_xyxy: np.ndarray,
    ) -> Optional[Tuple[float, float, float]]:
        if depth_u16 is None or intr is None:
            return None

        x1, y1, x2, y2 = bbox_xyxy.astype(int)
        cx = int(np.clip((x1 + x2) // 2, 0, depth_u16.shape[1] - 1))
        cy = int(np.clip((y1 + y2) // 2, 0, depth_u16.shape[0] - 1))
        z_mm = int(depth_u16[cy, cx])
        if z_mm == 0 or z_mm < DEPTH_MM_MIN or z_mm > DEPTH_MM_MAX:
            return None

        z_m = z_mm / 1000.0
        x_m = (cx - intr["ppx"]) * z_m / intr["fx"]
        y_m = (cy - intr["ppy"]) * z_m / intr["fy"]
        return x_m, y_m, z_m

    def run_display(self) -> None:
        try:
            while True:
                color_bgr, depth_u16, intr = self.get_aligned_frames()
                if color_bgr is None:
                    time.sleep(0.001)  # <<< added to prevent busy-loop
                    continue

                dets, _ = self.detect()
                xyzs = [self.face_xyz(depth_u16, intr, f.bbox_xyxy) for f in dets]
                vis = _draw_detections(color_bgr, dets, xyzs)
                cv2.imshow("OAK-D Face Detection", vis)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
        finally:
            cv2.destroyAllWindows()

    def shutdown(self) -> None:
        self._device.close()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="OAK-D face detection demo")
    p.add_argument("--display", action="store_true", default=False)
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    detector = Detector()
    try:
        if args.display:
            detector.run_display()
        else:
            frame_idx = 0
            while True:
                color_bgr, depth_u16, intr = detector.get_aligned_frames()
                if color_bgr is None:
                    time.sleep(0.001)  # <<< added
                    continue

                dets, _ = detector.detect()
                xyzs = [detector.face_xyz(depth_u16, intr, f.bbox_xyxy) for f in dets]
                frame_idx += 1
                if frame_idx % PRINT_EVERY_N_FRAMES == 0:
                    print(f"[frame {frame_idx}] {len(dets)} face(s)")
                    for i, (f, xyz) in enumerate(zip(dets[:PRINT_TOP_K], xyzs[:PRINT_TOP_K])):
                        print(f"  [{i}] score={f.score:.3f}  xyz={xyz}")
    finally:
        detector.shutdown()
