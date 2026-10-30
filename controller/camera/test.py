from __future__ import annotations

import argparse
import math
import signal
import sys
from pathlib import Path
from time import perf_counter, sleep

import depthai as dai
from depthai_nodes.node import ParsingNeuralNetwork


DEFAULT_MODEL_ARCHIVE = (
    Path(__file__).resolve().parent / "models" / "YuNet-640x360.rvc2.tar.xz"
)

DEFAULT_RGB_FPS = 30
DEFAULT_DEPTH_FPS = 30
DEFAULT_NN_SHAVES = 4
DEFAULT_MONO_WIDTH = 640
DEFAULT_MONO_HEIGHT = 400

DEPTH_LOWER_THRESHOLD_MM = 200
DEPTH_UPPER_THRESHOLD_MM = 5000
SPATIAL_BBOX_SCALE = 0.5


class OakSpatialNoImageAlignTest:
    """RVC2 spatial face-detection test without ImageAlign.

    Pipeline:

        CAM_A RGB 640x360 -> YuNet parser -> 2D detections

        CAM_A RGB 640x360 -> StereoDepth.inputAlignTo

        CAM_B/C 640x400 -> StereoDepth FACE -> depth aligned by StereoDepth

        YuNet detections + aligned depth -> SpatialLocationCalculator -> host

    This intentionally excludes:

        - ImageAlign
        - RemoteConnection visualizer
        - stereo.setDepthAlign(CAM_A)

    Purpose:

        Test whether replacing ImageAlign with StereoDepth.inputAlignTo fixes the
        X_LINK_ERROR crash.
    """

    def __init__(
        self,
        model_archive: Path,
        rgb_fps: float,
        depth_fps: float,
        nn_shaves: int,
        mono_width: int,
        mono_height: int,
        preset: str,
        undistort: bool,
        queue_size: int,
        emit_2d_queue: bool,
        emit_depth_queue: bool,
    ) -> None:
        self.model_archive = Path(model_archive)
        self.rgb_fps = float(rgb_fps)
        self.depth_fps = float(depth_fps)
        self.nn_shaves = int(nn_shaves)
        self.mono_width = int(mono_width)
        self.mono_height = int(mono_height)
        self.preset = preset
        self.undistort = bool(undistort)
        self.queue_size = int(queue_size)
        self.emit_2d_queue = bool(emit_2d_queue)
        self.emit_depth_queue = bool(emit_depth_queue)

        self.device: dai.Device | None = None
        self.pipeline: dai.Pipeline | None = None

        self.detections_queue: dai.MessageQueue | None = None
        self.depth_queue: dai.MessageQueue | None = None
        self.spatial_queue: dai.MessageQueue | None = None
        self.syslog_queue: dai.MessageQueue | None = None

        self._stop_requested = False

    def build(self) -> None:
        if not self.model_archive.exists():
            raise FileNotFoundError(f"Model archive not found: {self.model_archive}")

        print("Creating OAK device...")
        self.device = dai.Device(dai.DeviceInfo())

        platform = self.device.getPlatformAsString()

        print(f"Platform: {platform}")
        print(f"USB speed: {self.device.getUsbSpeed()}")
        print(f"Model: {self.model_archive}")
        print(f"RGB FPS: {self.rgb_fps}")
        print(f"Depth FPS: {self.depth_fps}")
        print(f"Mono size: {self.mono_width}x{self.mono_height}")
        print(f"Stereo preset: {self.preset}")
        print(f"NN SHAVES: {self.nn_shaves}")
        print(f"RGB undistortion: {self.undistort}")
        print("ImageAlign: disabled")
        print("StereoDepth.inputAlignTo: enabled")
        print("SpatialLocationCalculator: enabled")
        print(f"2D queue: {self.emit_2d_queue}")
        print(f"Depth queue: {self.emit_depth_queue}")

        pipeline = dai.Pipeline(self.device)
        nn_archive = dai.NNArchive(self.model_archive)

        # ---------------------------------------------------------------------
        # RGB -> YuNet parser
        # ---------------------------------------------------------------------
        rgb_cam_node = pipeline.create(dai.node.Camera)
        rgb_cam = rgb_cam_node.build(dai.CameraBoardSocket.CAM_A)

        rgb_out = rgb_cam.requestOutput(
            size=self._nn_input_size(nn_archive),
            type=self._nn_frame_type(platform),
            resizeMode=dai.ImgResizeMode.LETTERBOX,
            fps=self.rgb_fps,
            enableUndistortion=self.undistort,
        )

        nn_with_parser = pipeline.create(ParsingNeuralNetwork).build(
            rgb_out,
            nn_archive,
        )

        nn_with_parser.setNNArchive(
            nn_archive,
            numShaves=self.nn_shaves,
        )

        if self.emit_2d_queue:
            self.detections_queue = nn_with_parser.out.createOutputQueue(
                maxSize=self.queue_size,
                blocking=False,
            )

        # ---------------------------------------------------------------------
        # Stereo 400P -> StereoDepth
        # ---------------------------------------------------------------------
        left_cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_B)
        right_cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_C)

        left_cap = dai.ImgFrameCapability()
        left_cap.size.fixed((self.mono_width, self.mono_height))
        left_cap.fps.fixed(self.depth_fps)
        left_cap.type = dai.ImgFrame.Type.GRAY8

        right_cap = dai.ImgFrameCapability()
        right_cap.size.fixed((self.mono_width, self.mono_height))
        right_cap.fps.fixed(self.depth_fps)
        right_cap.type = dai.ImgFrame.Type.GRAY8

        left_out = left_cam.requestOutput(left_cap, True)
        right_out = right_cam.requestOutput(right_cap, True)

        stereo = pipeline.create(dai.node.StereoDepth)

        if self.preset == "FACE":
            stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.FACE)
        elif self.preset == "FAST_ACCURACY":
            stereo.setDefaultProfilePreset(
                dai.node.StereoDepth.PresetMode.FAST_ACCURACY
            )
        elif self.preset == "FAST_DENSITY":
            stereo.setDefaultProfilePreset(
                dai.node.StereoDepth.PresetMode.FAST_DENSITY
            )
        else:
            raise ValueError(f"Unsupported preset: {self.preset}")

        stereo.setLeftRightCheck(True)
        stereo.setSubpixel(False)

        left_out.link(stereo.left)
        right_out.link(stereo.right)

        # ---------------------------------------------------------------------
        # RVC2-style alignment.
        #
        # Do not use ImageAlign.
        # Do not also call stereo.setDepthAlign(CAM_A).
        #
        # The RGB output metadata is used as the alignment target.
        # ---------------------------------------------------------------------
        rgb_out.link(stereo.inputAlignTo)

        if self.emit_depth_queue:
            self.depth_queue = stereo.depth.createOutputQueue(
                maxSize=self.queue_size,
                blocking=False,
            )

        # ---------------------------------------------------------------------
        # SpatialLocationCalculator
        # ---------------------------------------------------------------------
        spatial_calc = pipeline.create(dai.node.SpatialLocationCalculator)
        spatial_calc.setRunOnHost(False)

        spatial_calc.initialConfig.setDepthThresholds(
            DEPTH_LOWER_THRESHOLD_MM,
            DEPTH_UPPER_THRESHOLD_MM,
        )
        spatial_calc.initialConfig.setBoundingBoxScaleFactor(SPATIAL_BBOX_SCALE)
        spatial_calc.initialConfig.setCalculationAlgorithm(
            dai.SpatialLocationCalculatorAlgorithm.MEDIAN
        )

        stereo.depth.link(spatial_calc.inputDepth)
        nn_with_parser.out.link(spatial_calc.inputDetections)

        self.spatial_queue = spatial_calc.outputDetections.createOutputQueue(
            maxSize=self.queue_size,
            blocking=False,
        )

        # ---------------------------------------------------------------------
        # Telemetry
        # ---------------------------------------------------------------------
        sys_logger = pipeline.create(dai.node.SystemLogger)
        sys_logger.setRate(1)

        self.syslog_queue = sys_logger.out.createOutputQueue(
            maxSize=4,
            blocking=False,
        )

        self.pipeline = pipeline
        print("Pipeline created.")

    def run(self) -> None:
        if self.pipeline is None:
            self.build()

        if self.pipeline is None or self.spatial_queue is None:
            raise RuntimeError("Pipeline was not created correctly.")

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        print("Starting pipeline...")
        self.pipeline.start()
        print("Running spatial test without ImageAlign.")
        print("Press Ctrl+C to stop.")
        print()

        window_t0 = perf_counter()
        total_t0 = window_t0

        det_msgs_window = 0
        depth_msgs_window = 0
        spatial_msgs_window = 0

        det_count_window = 0
        spatial_det_count_window = 0
        positioned_count_window = 0

        det_msgs_total = 0
        depth_msgs_total = 0
        spatial_msgs_total = 0

        det_count_total = 0
        spatial_det_count_total = 0
        positioned_count_total = 0

        last_depth_size = None
        last_spatial_count = 0
        last_positioned_count = 0
        last_xyz_m = None

        while self.pipeline.isRunning() and not self._stop_requested:
            try:
                det_msgs = (
                    self.detections_queue.tryGetAll()
                    if self.detections_queue is not None
                    else []
                )
                depth_msgs = (
                    self.depth_queue.tryGetAll()
                    if self.depth_queue is not None
                    else []
                )
                spatial_msgs = self.spatial_queue.tryGetAll()
            except RuntimeError as exc:
                print()
                print(f"Queue read failed: {exc}")
                break

            if det_msgs:
                det_msgs_window += len(det_msgs)
                det_msgs_total += len(det_msgs)

                for msg in det_msgs:
                    count = self._count_detections(msg)
                    det_count_window += count
                    det_count_total += count

            if depth_msgs:
                depth_msgs_window += len(depth_msgs)
                depth_msgs_total += len(depth_msgs)

                last_depth = depth_msgs[-1]
                last_depth_size = (last_depth.getWidth(), last_depth.getHeight())

            if spatial_msgs:
                spatial_msgs_window += len(spatial_msgs)
                spatial_msgs_total += len(spatial_msgs)

                for msg in spatial_msgs:
                    spatial_count, positioned_count, xyz_m = (
                        self._summarize_spatial_detections(msg)
                    )

                    spatial_det_count_window += spatial_count
                    positioned_count_window += positioned_count

                    spatial_det_count_total += spatial_count
                    positioned_count_total += positioned_count

                    last_spatial_count = spatial_count
                    last_positioned_count = positioned_count
                    if xyz_m is not None:
                        last_xyz_m = xyz_m

            now = perf_counter()
            elapsed = now - window_t0

            if elapsed >= 1.0:
                det_fps = det_msgs_window / elapsed
                depth_fps = depth_msgs_window / elapsed
                spatial_fps = spatial_msgs_window / elapsed

                print(
                    f"2d_fps={det_fps:5.1f} "
                    f"depth_fps={depth_fps:5.1f} "
                    f"spatial_fps={spatial_fps:5.1f} "
                    f"2d_msgs={det_msgs_window:3d} "
                    f"depth_msgs={depth_msgs_window:3d} "
                    f"spatial_msgs={spatial_msgs_window:3d} "
                    f"2d_detections={det_count_window:3d} "
                    f"spatial_detections={spatial_det_count_window:3d} "
                    f"positioned={positioned_count_window:3d} "
                    f"last_spatial={last_spatial_count} "
                    f"last_positioned={last_positioned_count} "
                    f"depth_size={last_depth_size} "
                    f"last_xyz_m={self._format_xyz(last_xyz_m)}"
                )

                self._print_syslog_if_available()

                window_t0 = now

                det_msgs_window = 0
                depth_msgs_window = 0
                spatial_msgs_window = 0

                det_count_window = 0
                spatial_det_count_window = 0
                positioned_count_window = 0

            sleep(0.001)

        total_elapsed = max(perf_counter() - total_t0, 1e-9)

        print()
        print("Stopped.")
        print(f"Total 2D FPS: {det_msgs_total / total_elapsed:.2f}")
        print(f"Total depth FPS: {depth_msgs_total / total_elapsed:.2f}")
        print(f"Total spatial FPS: {spatial_msgs_total / total_elapsed:.2f}")
        print(f"Total 2D messages: {det_msgs_total}")
        print(f"Total depth messages: {depth_msgs_total}")
        print(f"Total spatial messages: {spatial_msgs_total}")
        print(f"Total 2D detections: {det_count_total}")
        print(f"Total spatial detections: {spatial_det_count_total}")
        print(f"Total positioned detections: {positioned_count_total}")

    def shutdown(self) -> None:
        if self.pipeline is not None and self.pipeline.isRunning():
            self.pipeline.stop()

    def _handle_signal(self, signum: int, frame: object) -> None:
        self._stop_requested = True

    def _print_syslog_if_available(self) -> None:
        if self.syslog_queue is None:
            return

        try:
            msg = self.syslog_queue.tryGet()
        except RuntimeError as exc:
            print(f"syslog read failed: {exc}")
            return

        if msg is None:
            return

        mib = 1024 * 1024
        temp = msg.chipTemperature

        print(
            "  oak "
            f"ddr={msg.ddrMemoryUsage.used / mib:.1f}/"
            f"{msg.ddrMemoryUsage.total / mib:.1f}MiB "
            f"cmx={msg.cmxMemoryUsage.used / mib:.2f}/"
            f"{msg.cmxMemoryUsage.total / mib:.2f}MiB "
            f"temp={temp.average:.1f}C "
            f"css={msg.leonCssCpuUsage.average * 100:.1f}% "
            f"mss={msg.leonMssCpuUsage.average * 100:.1f}%"
        )

    @staticmethod
    def _count_detections(msg: object) -> int:
        detections = getattr(msg, "detections", None)
        if detections is None:
            return 0
        return len(detections)

    @staticmethod
    def _summarize_spatial_detections(
        msg: object,
    ) -> tuple[int, int, tuple[float, float, float] | None]:
        detections = getattr(msg, "detections", None)
        if detections is None:
            return 0, 0, None

        spatial_count = len(detections)
        positioned_count = 0
        first_xyz_m = None

        for detection in detections:
            xyz_m = OakSpatialNoImageAlignTest._spatial_detection_xyz_m(detection)

            if xyz_m is None:
                continue

            positioned_count += 1

            if first_xyz_m is None:
                first_xyz_m = xyz_m

        return spatial_count, positioned_count, first_xyz_m

    @staticmethod
    def _spatial_detection_xyz_m(
        detection: object,
    ) -> tuple[float, float, float] | None:
        coords = getattr(detection, "spatialCoordinates", None)
        if coords is None:
            return None

        x = float(coords.x)
        y = float(coords.y)
        z = float(coords.z)

        if any(not math.isfinite(v) for v in (x, y, z)):
            return None

        if z <= 0:
            return None

        return (x / 1000.0, y / 1000.0, z / 1000.0)

    @staticmethod
    def _format_xyz(xyz_m: tuple[float, float, float] | None) -> str:
        if xyz_m is None:
            return "None"

        x, y, z = xyz_m
        return f"({x:.3f},{y:.3f},{z:.3f})"

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

    @staticmethod
    def _nn_frame_type(platform: str) -> dai.ImgFrame.Type:
        if platform == "RVC4":
            return dai.ImgFrame.Type.BGR888i

        return dai.ImgFrame.Type.BGR888p


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "OAK-D spatial face detection test using StereoDepth.inputAlignTo "
            "instead of ImageAlign."
        )
    )

    parser.add_argument(
        "--model",
        type=Path,
        default=DEFAULT_MODEL_ARCHIVE,
        help="Path to YuNet .tar.xz model archive.",
    )

    parser.add_argument(
        "--rgb-fps",
        type=float,
        default=DEFAULT_RGB_FPS,
    )

    parser.add_argument(
        "--depth-fps",
        type=float,
        default=DEFAULT_DEPTH_FPS,
    )

    parser.add_argument(
        "--nn-shaves",
        type=int,
        default=DEFAULT_NN_SHAVES,
    )

    parser.add_argument(
        "--mono-width",
        type=int,
        default=DEFAULT_MONO_WIDTH,
    )

    parser.add_argument(
        "--mono-height",
        type=int,
        default=DEFAULT_MONO_HEIGHT,
    )

    parser.add_argument(
        "--preset",
        choices=["FACE", "FAST_ACCURACY", "FAST_DENSITY"],
        default="FACE",
    )

    parser.add_argument(
        "--no-undistort",
        action="store_true",
        help="Disable RGB undistortion. Default is enabled.",
    )

    parser.add_argument(
        "--queue-size",
        type=int,
        default=60,
    )

    parser.add_argument(
        "--no-2d-queue",
        action="store_true",
        help="Do not expose the parsed 2D detections as a separate host queue.",
    )

    parser.add_argument(
        "--depth-queue",
        action="store_true",
        help="Also expose StereoDepth.depth as a host queue.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    test = OakSpatialNoImageAlignTest(
        model_archive=args.model,
        rgb_fps=args.rgb_fps,
        depth_fps=args.depth_fps,
        nn_shaves=args.nn_shaves,
        mono_width=args.mono_width,
        mono_height=args.mono_height,
        preset=args.preset,
        undistort=not args.no_undistort,
        queue_size=args.queue_size,
        emit_2d_queue=not args.no_2d_queue,
        emit_depth_queue=args.depth_queue,
    )

    try:
        test.build()
        test.run()
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        test.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())