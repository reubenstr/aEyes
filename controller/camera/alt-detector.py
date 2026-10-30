from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter, sleep

import depthai as dai
import numpy as np
from depthai_nodes.node import ParsingNeuralNetwork

from parameters import params as _params

"""
    Camera:
        Luxonis OAK-D W

    Stable pipeline used here:

        CAM_A RGB -> YuNet parser -> host detections
        CAM_B/C 400P -> StereoDepth -> host depth

    XYZ is estimated on the host from the latest raw depth frame.

    This file intentionally does not create device-side spatial detection or
    image alignment nodes, because those paths were isolated as unstable on this
    RVC2 pipeline.
"""


MODEL_ARCHIVE = (
    Path(__file__).resolve().parent / "models" / "YuNet-640x360.rvc2.tar.xz"
)

FPS_LIMIT = 30
NN_SHAVES = 4

MONO_400P_SIZE = (640, 400)

DEPTH_LOWER_THRESHOLD_MM = 200
DEPTH_UPPER_THRESHOLD_MM = 5000
SPATIAL_BBOX_SCALE = 0.5

STREAM_TIMEOUT_S = 2.0


@dataclass(frozen=True)
class DetectedFace:
    """A face detected by the OAK-D pipeline."""

    confidence: float
    xyz_m: tuple[float, float, float] | None


class OakStreamError(RuntimeError):
    """Raised when the OAK stream stops producing frames."""


class Detector:
    """Standalone OAK-D face detector with host-side depth-backed XYZ output."""

    def __init__(
        self,
        model_archive: Path | str = MODEL_ARCHIVE,
        fps_limit: int = FPS_LIMIT,
        enable_visualizer: bool = False,
        stream_timeout_s: float = STREAM_TIMEOUT_S,
    ) -> None:
        self.model_archive = Path(model_archive)
        self.fps_limit = int(fps_limit)
        self.enable_visualizer = False
        self.stream_timeout_s = float(stream_timeout_s)

        print("Creating OAK-D device...")
        self.device = dai.Device(dai.DeviceInfo())

        try:
            self.device.setMaxReconnectionAttempts(0)
        except Exception:
            try:
                self.device.setMaxReconnectionAttempts(1)
            except Exception:
                pass

        self.platform = self.device.getPlatformAsString()
        self.calibration = self.device.readCalibration()

        print(f"Platform: {self.platform}, USB speed: {self.device.getUsbSpeed()}")
        print(f"Detector target FPS: {self.fps_limit}")
        print("Detector version: HOST_RAW_DEPTH_NO_DEVICE_SPATIAL")

        self.pipeline: dai.Pipeline | None = None
        self.detections_queue: dai.MessageQueue | None = None
        self.depth_queue: dai.MessageQueue | None = None

        self.nn_input_size: tuple[int, int] | None = None
        self.latest_depth_frame_mm: np.ndarray | None = None
        self.latest_faces_xyz_m: list[tuple[float, float, float]] = []

        self._intrinsics_cache: dict[tuple[int, int], tuple[float, float, float, float]] = {}
        self._last_oak_msg_time: float | None = None
        self._failed = False

        self._build_pipeline()

    def _build_pipeline(self) -> None:
        print("Creating pipeline...")

        if not self.model_archive.exists():
            raise FileNotFoundError(f"Model archive not found: {self.model_archive}")

        pipeline = dai.Pipeline(self.device)
        nn_archive = dai.NNArchive(self.model_archive)

        self.nn_input_size = self._nn_input_size(nn_archive)

        # ------------------------------------------------------------------
        # RGB -> YuNet parser -> host detections
        # ------------------------------------------------------------------
        cam = pipeline.create(dai.node.Camera)
        rgb = cam.build(dai.CameraBoardSocket.CAM_A)

        rgb_out = rgb.requestOutput(
            size=self.nn_input_size,
            type=self._nn_frame_type(),
            resizeMode=dai.ImgResizeMode.LETTERBOX,
            fps=float(self.fps_limit),
            enableUndistortion=False,
        )

        nn_with_parser = pipeline.create(ParsingNeuralNetwork).build(
            rgb_out,
            nn_archive,
        )

        nn_with_parser.setNNArchive(
            nn_archive,
            numShaves=NN_SHAVES,
        )

        self.detections_queue = nn_with_parser.out.createOutputQueue(
            maxSize=1,
            blocking=False,
        )

        # ------------------------------------------------------------------
        # Explicit 400P stereo -> host depth
        # ------------------------------------------------------------------
        left_cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_B)
        right_cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_C)

        left_cap = dai.ImgFrameCapability()
        left_cap.size.fixed(MONO_400P_SIZE)
        left_cap.fps.fixed(float(self.fps_limit))
        left_cap.type = dai.ImgFrame.Type.GRAY8

        right_cap = dai.ImgFrameCapability()
        right_cap.size.fixed(MONO_400P_SIZE)
        right_cap.fps.fixed(float(self.fps_limit))
        right_cap.type = dai.ImgFrame.Type.GRAY8

        left_out = left_cam.requestOutput(left_cap, True)
        right_out = right_cam.requestOutput(right_cap, True)

        stereo = pipeline.create(dai.node.StereoDepth)
        stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.FACE)
        stereo.setLeftRightCheck(True)
        stereo.setSubpixel(False)

        left_out.link(stereo.left)
        right_out.link(stereo.right)

        self.depth_queue = stereo.depth.createOutputQueue(
            maxSize=1,
            blocking=False,
        )

        self.pipeline = pipeline
        print("Pipeline created.")
        print("Active queues: detections_queue, depth_queue only")

    def start(self) -> None:
        if self.pipeline is None:
            raise RuntimeError("Detector pipeline was not created.")

        if self._failed:
            raise OakStreamError("OAK-D detector is in a failed state.")

        if not self.pipeline.isRunning():
            self.pipeline.start()
            self._last_oak_msg_time = perf_counter()

    def poll_faces(self) -> list[DetectedFace] | None:
        """Poll one detector frame.

        Returns None until a new 2D detection message is available.

        XYZ values are estimated on the host:
        X=right, Y=down, Z=forward.
        """
        if self.detections_queue is None or self.depth_queue is None:
            raise RuntimeError("Detector queues were not created.")

        self.start()

        got_oak_msg = False

        try:
            got_oak_msg = self._poll_latest_depth_frame()

            detection_msgs = self.detections_queue.tryGetAll()
            if detection_msgs:
                got_oak_msg = True

        except RuntimeError as exc:
            self._mark_failed()
            raise OakStreamError(f"OAK-D stream failure: {exc}") from exc

        if got_oak_msg:
            self._last_oak_msg_time = perf_counter()
        else:
            self._check_stream_watchdog()

        if not detection_msgs:
            return None

        detections_msg = detection_msgs[-1]

        faces: list[DetectedFace] = []
        self.latest_faces_xyz_m = []

        for face in getattr(detections_msg, "detections", []):
            confidence = float(getattr(face, "confidence", 0.0))
            xyz = self._host_spatial_detection_xyz_m(face)

            if xyz is not None:
                self.latest_faces_xyz_m.append(xyz)

            faces.append(
                DetectedFace(
                    confidence=confidence,
                    xyz_m=xyz,
                )
            )

        return faces

    def poll_face_xyz_m(self) -> list[tuple[float, float, float]]:
        """Poll valid face positions in the DepthAI-style camera frame."""
        faces = self.poll_faces()
        if faces is None:
            return []

        return [face.xyz_m for face in faces if face.xyz_m is not None]

    def run(self) -> None:
        self.start()
        print("Detector running without visualizer. Press Ctrl+C to quit.")
        print("XYZ is host-estimated: X=right, Y=down, Z=forward.")

        while self.pipeline is not None and self.pipeline.isRunning():
            try:
                self._print_face_xyz()
            except OakStreamError as exc:
                print(f"Detector stopped after stream failure: {exc}")
                break

    def _print_face_xyz(self) -> None:
        faces = self.poll_faces()

        if faces is None:
            sleep(0.005)
            return

        if not faces:
            print("faces=0")
            return

        print(f"faces={len(faces)}")

        for idx, face in enumerate(faces):
            if face.xyz_m is None:
                print(f"  face[{idx}] conf={face.confidence:.2f} xyz_m=(no depth)")
                continue

            x_m, y_m, z_m = face.xyz_m
            print(
                f"  face[{idx}] conf={face.confidence:.2f} "
                f"xyz_m=({x_m:.3f}, {y_m:.3f}, {z_m:.3f})"
            )

    def _poll_latest_depth_frame(self) -> bool:
        if self.depth_queue is None:
            return False

        depth_msgs = self.depth_queue.tryGetAll()
        if not depth_msgs:
            return False

        self.latest_depth_frame_mm = depth_msgs[-1].getFrame()
        return True

    def _check_stream_watchdog(self) -> None:
        if self._last_oak_msg_time is None:
            return

        elapsed = perf_counter() - self._last_oak_msg_time
        if elapsed <= self.stream_timeout_s:
            return

        self._mark_failed()
        raise OakStreamError(
            f"No OAK-D messages received for {elapsed:.2f}s. "
            "Device stream appears stalled."
        )

    def _mark_failed(self) -> None:
        self._failed = True

        try:
            if self.device is not None:
                self.device.close()
        except Exception:
            pass

    def _host_spatial_detection_xyz_m(
        self,
        detection: object,
    ) -> tuple[float, float, float] | None:
        if self.latest_depth_frame_mm is None:
            return None

        bbox_norm = self._detection_bbox_norm(detection)
        if bbox_norm is None:
            return None

        depth = self.latest_depth_frame_mm
        depth_h, depth_w = depth.shape[:2]

        xmin, ymin, xmax, ymax = bbox_norm

        x0 = xmin * depth_w
        y0 = ymin * depth_h
        x1 = xmax * depth_w
        y1 = ymax * depth_h

        roi = self._scaled_clipped_roi(
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            frame_w=depth_w,
            frame_h=depth_h,
            scale=SPATIAL_BBOX_SCALE,
        )

        if roi is None:
            return None

        ix0, iy0, ix1, iy1 = roi
        roi_depth = depth[iy0:iy1, ix0:ix1]

        if roi_depth.size == 0:
            return None

        valid = roi_depth[
            (roi_depth >= DEPTH_LOWER_THRESHOLD_MM)
            & (roi_depth <= DEPTH_UPPER_THRESHOLD_MM)
        ]

        if valid.size == 0:
            return None

        z_mm = float(np.median(valid))

        if not math.isfinite(z_mm) or z_mm <= 0:
            return None

        u = (x0 + x1) * 0.5
        v = (y0 + y1) * 0.5

        fx, fy, cx, cy = self._intrinsics_for_depth_frame(depth_w, depth_h)

        z_m = z_mm / 1000.0
        x_m = ((u - cx) * z_m) / fx
        y_m = ((v - cy) * z_m) / fy

        if any(not math.isfinite(value) for value in (x_m, y_m, z_m)):
            return None

        return (x_m, y_m, z_m)

    def _intrinsics_for_depth_frame(
        self,
        width: int,
        height: int,
    ) -> tuple[float, float, float, float]:
        key = (width, height)

        cached = self._intrinsics_cache.get(key)
        if cached is not None:
            return cached

        try:
            intrinsics = self.calibration.getCameraIntrinsics(
                dai.CameraBoardSocket.CAM_C,
                width,
                height,
            )

            fx = float(intrinsics[0][0])
            fy = float(intrinsics[1][1])
            cx = float(intrinsics[0][2])
            cy = float(intrinsics[1][2])

        except Exception:
            fx = float(width)
            fy = float(width)
            cx = float(width) * 0.5
            cy = float(height) * 0.5

        result = (fx, fy, cx, cy)
        self._intrinsics_cache[key] = result
        return result

    @staticmethod
    def _scaled_clipped_roi(
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        frame_w: int,
        frame_h: int,
        scale: float,
    ) -> tuple[int, int, int, int] | None:
        if x1 <= x0 or y1 <= y0:
            return None

        cx = (x0 + x1) * 0.5
        cy = (y0 + y1) * 0.5

        w = (x1 - x0) * scale
        h = (y1 - y0) * scale

        sx0 = max(0.0, cx - w * 0.5)
        sy0 = max(0.0, cy - h * 0.5)
        sx1 = min(float(frame_w), cx + w * 0.5)
        sy1 = min(float(frame_h), cy + h * 0.5)

        ix0 = int(math.floor(sx0))
        iy0 = int(math.floor(sy0))
        ix1 = int(math.ceil(sx1))
        iy1 = int(math.ceil(sy1))

        ix0 = max(0, min(ix0, frame_w - 1))
        iy0 = max(0, min(iy0, frame_h - 1))
        ix1 = max(ix0 + 1, min(ix1, frame_w))
        iy1 = max(iy0 + 1, min(iy1, frame_h))

        return (ix0, iy0, ix1, iy1)

    @staticmethod
    def _detection_bbox_norm(
        detection: object,
    ) -> tuple[float, float, float, float] | None:
        xmin = Detector._first_attr(detection, ("xmin", "xMin", "x_min"))
        ymin = Detector._first_attr(detection, ("ymin", "yMin", "y_min"))
        xmax = Detector._first_attr(detection, ("xmax", "xMax", "x_max"))
        ymax = Detector._first_attr(detection, ("ymax", "yMax", "y_max"))

        if None in (xmin, ymin, xmax, ymax):
            return None

        values = [float(xmin), float(ymin), float(xmax), float(ymax)]

        if any(not math.isfinite(value) for value in values):
            return None

        xmin_f, ymin_f, xmax_f, ymax_f = values

        xmin_f = max(0.0, min(1.0, xmin_f))
        ymin_f = max(0.0, min(1.0, ymin_f))
        xmax_f = max(0.0, min(1.0, xmax_f))
        ymax_f = max(0.0, min(1.0, ymax_f))

        if xmax_f <= xmin_f or ymax_f <= ymin_f:
            return None

        return (xmin_f, ymin_f, xmax_f, ymax_f)

    @staticmethod
    def _first_attr(obj: object, names: tuple[str, ...]) -> object | None:
        for name in names:
            if hasattr(obj, name):
                return getattr(obj, name)
        return None

    @staticmethod
    def _nn_input_size(nn_archive: dai.NNArchive) -> tuple[int, int]:
        inputs = nn_archive.getConfig().model.inputs

        if len(inputs) != 1:
            raise ValueError(f"Expected one model input, got {len(inputs)}.")

        shape = inputs[0].shape
        layout = inputs[0].layout

        if layout == "NCHW":
            return (shape[3], shape[2])

        if layout == "NHWC":
            return (shape[2], shape[1])

        raise ValueError(f"Unsupported model input layout: {layout}")

    def _nn_frame_type(self) -> dai.ImgFrame.Type:
        if self.platform == "RVC4":
            return dai.ImgFrame.Type.BGR888i

        return dai.ImgFrame.Type.BGR888p

    def shutdown(self) -> None:
        self._failed = True

        try:
            if self.detections_queue is not None:
                self.detections_queue.close()
        except Exception:
            pass

        try:
            if self.depth_queue is not None:
                self.depth_queue.close()
        except Exception:
            pass

        try:
            if self.pipeline is not None and self.pipeline.isRunning():
                self.pipeline.stop()
        except Exception:
            pass

        try:
            if self.device is not None:
                self.device.close()
        except Exception:
            pass


###############################################################################
# Main Entry | Manual Testing
###############################################################################

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--visualizer",
        action="store_true",
        help="Ignored in this stable detector version.",
    )

    parser.add_argument(
        "--fps",
        type=int,
        default=FPS_LIMIT,
        help="Detector target FPS.",
    )

    parser.add_argument(
        "--stream-timeout",
        type=float,
        default=STREAM_TIMEOUT_S,
        help="Seconds without OAK messages before raising OakStreamError.",
    )

    args = parser.parse_args()

    detector = Detector(
        fps_limit=args.fps,
        enable_visualizer=False,
        stream_timeout_s=args.stream_timeout,
    )

    try:
        detector.run()
    except KeyboardInterrupt:
        pass
    finally:
        detector.shutdown()