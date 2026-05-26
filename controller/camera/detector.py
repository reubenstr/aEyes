from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from time import sleep

import depthai as dai
from depthai_nodes.node import ParsingNeuralNetwork

from parameters import params as _params

"""
    Camera:
        Luxonis OAK-D W (wide)
        https://shop.luxonis.com/products/oak-d-w

    https://models.luxonis.com/

    The visualizer may crash at resolutions if the camera
    does not emulates as a super-speed USB device.

    See attached devices and negotiated speeds (after app is running):
        lsusb -t   

    See USB device events:
        dmesg | grep -i usb
"""


MODEL_ARCHIVE = (
    Path(__file__).resolve().parent / "models" / "YuNet-640x360.rvc2.tar.xz"
)
FPS_LIMIT = _params.system.refresh_rate_hz
NN_SHAVES = 6
DEPTH_LOWER_THRESHOLD_MM = 200
DEPTH_UPPER_THRESHOLD_MM = 5000
SPATIAL_BBOX_SCALE = 0.5
HTTP_PORT = 8082


@dataclass(frozen=True)
class DetectedFace:
    """A face detected by the OAK-D pipeline."""

    confidence: float
    xyz_m: tuple[float, float, float] | None


class Detector:
    """Standalone OAK-D face detector with device-side depth-backed XYZ output."""

    def __init__(
        self,
        model_archive: Path | str = MODEL_ARCHIVE,
        fps_limit: int = FPS_LIMIT,
        enable_visualizer: bool = False,
    ) -> None:
        self.model_archive = Path(model_archive)
        self.fps_limit = fps_limit
        self.enable_visualizer = enable_visualizer

        print("Creating OAK-D device...")
        self.visualizer = (
            dai.RemoteConnection(httpPort=HTTP_PORT) if self.enable_visualizer else None
        )
        self.device = dai.Device(dai.DeviceInfo())
        self.platform = self.device.getPlatformAsString()
        print(f"Platform: {self.platform}, USB speed: {self.device.getUsbSpeed()}")

        self.pipeline: dai.Pipeline | None = None
        self.spatial_detections_queue: dai.MessageQueue | None = None
        self.latest_faces_xyz_m: list[tuple[float, float, float]] = []
        self._build_pipeline()

    def _build_pipeline(self) -> None:
        print("Creating pipeline...")

        if not self.model_archive.exists():
            raise FileNotFoundError(f"Model archive not found: {self.model_archive}")

        pipeline = dai.Pipeline(self.device)
        nn_archive = dai.NNArchive(self.model_archive)

        cam = pipeline.create(dai.node.Camera)
        rgb = cam.build(dai.CameraBoardSocket.CAM_A)
        rgb_out = rgb.requestOutput(
            size=self._nn_input_size(nn_archive),
            type=self._nn_frame_type(),
            resizeMode=dai.ImgResizeMode.LETTERBOX,
            fps=self.fps_limit,
            enableUndistortion=True,
        )

        stereo = pipeline.create(dai.node.StereoDepth).build(
            True,
            dai.node.StereoDepth.PresetMode.FACE,
            fps=self.fps_limit,
        )
        stereo.setDepthAlign(dai.CameraBoardSocket.CAM_A)
        stereo.setLeftRightCheck(True)
        stereo.setSubpixel(False)

        nn_with_parser = pipeline.create(ParsingNeuralNetwork).build(
            rgb_out,
            nn_archive,
        )
        # Leave enough SHAVEs for StereoDepth, ImageManip, and spatial calculation.
        nn_with_parser.setNNArchive(nn_archive, numShaves=NN_SHAVES)

        # SpatialLocationCalculator requires matching transform metadata between
        # detections and depth, so align depth to the exact NN input frame.
        depth_align = pipeline.create(dai.node.ImageAlign)
        depth_align.setRunOnHost(False)
        depth_align.setOutKeepAspectRatio(False)
        stereo.depth.link(depth_align.input)
        nn_with_parser.passthrough.link(depth_align.inputAlignTo)

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
        depth_align.outputAligned.link(spatial_calc.inputDepth)
        nn_with_parser.out.link(spatial_calc.inputDetections)

        if self.visualizer is not None:
            self.visualizer.addTopic("Video", nn_with_parser.passthrough, "images")
            self.visualizer.addTopic(
                "Detections",
                spatial_calc.outputDetections,
                "images",
            )

        self.pipeline = pipeline
        self.spatial_detections_queue = spatial_calc.outputDetections.createOutputQueue(
            maxSize=1,
            blocking=False,
        )
        print("Pipeline created.")

    def start(self) -> None:
        if self.pipeline is None:
            raise RuntimeError("Detector pipeline was not created.")

        if not self.pipeline.isRunning():
            self.pipeline.start()

    def poll_faces(self) -> list[DetectedFace] | None:
        """Poll one detector frame.

        Returns None until a new spatial detection message is available. XYZ
        values are in the DepthAI camera frame:
        X=right, Y=down, Z=forward.
        """
        if self.spatial_detections_queue is None:
            raise RuntimeError("Detector queues were not created.")

        self.start()

        detection_msgs = self.spatial_detections_queue.tryGetAll()
        if not detection_msgs:
            return None

        detections_msg = detection_msgs[-1]
        faces: list[DetectedFace] = []
        self.latest_faces_xyz_m = []
        for face in detections_msg.detections:
            xyz = self._spatial_detection_xyz_m(face)
            if xyz is not None:
                self.latest_faces_xyz_m.append(xyz)
            faces.append(DetectedFace(confidence=face.confidence, xyz_m=xyz))

        return faces

    def poll_face_xyz_m(self) -> list[tuple[float, float, float]]:
        """Poll valid face positions in the DepthAI camera frame."""
        faces = self.poll_faces()
        if faces is None:
            return []
        return [face.xyz_m for face in faces if face.xyz_m is not None]

    def run(self) -> None:
        self.start()
        if self.visualizer is not None:
            self.visualizer.registerPipeline(self.pipeline)
            print("Detector running. Press q in the visualizer to quit.")
        else:
            print("Detector running without visualizer. Press Ctrl+C to quit.")
        print("XYZ is in the DepthAI camera frame: X=right, Y=down, Z=forward.")

        while self.pipeline.isRunning():
            self._print_face_xyz()

            if self.visualizer is not None:
                key = self.visualizer.waitKey(1)
                if key == ord("q"):
                    print("Got q key from the remote connection!")
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

    @staticmethod
    def _spatial_detection_xyz_m(
        face: dai.SpatialImgDetection,
    ) -> tuple[float, float, float] | None:
        coords = face.spatialCoordinates
        xyz_mm = (coords.x, coords.y, coords.z)
        if any(not math.isfinite(value) for value in xyz_mm) or coords.z <= 0:
            return None

        return tuple(value / 1000.0 for value in xyz_mm)

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
        if self.pipeline is not None and self.pipeline.isRunning():
            self.pipeline.stop()
   

###############################################################################
# Main Entry | Manual Testing
###############################################################################

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--visualizer",
        action="store_true",
        help="Enable DepthAI RemoteConnection image topics.",
    )  

    args = parser.parse_args()
    detector = Detector(enable_visualizer=args.visualizer)
    try:
        detector.run()
    except KeyboardInterrupt:
        pass
    finally:
        detector.shutdown()
