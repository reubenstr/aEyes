from __future__ import annotations

import argparse
from pathlib import Path

import depthai as dai
import numpy as np
from depthai_nodes.node import ParsingNeuralNetwork
from depthai_nodes.node.host_spatials_calc import HostSpatialsCalc

"""
    https://models.luxonis.com/

    The visualizer may crash at resolutions if the camera
    does not emulates as a super-speed USB device.

    See attached devices and negotiated speeds:
        lsusb -t   

    See USB device events:
        dmesg | grep -i usb
"""


MODEL = "luxonis/yunet:640x480"
MODEL_ARCHIVE = (
    Path(__file__).resolve().parent / "models" / "yunet-s-480x640.rvc2.tar.xz"
)
FPS_LIMIT = 15
NN_SHAVES = 6
DEPTH_LOWER_THRESHOLD_MM = 200
DEPTH_UPPER_THRESHOLD_MM = 5000
SPATIAL_BBOX_SCALE = 0.5
HTTP_PORT = 8082


class Detector:
    """Standalone OAK-D face detector with depth-backed XYZ output."""

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
        self.depth_queue: dai.MessageQueue | None = None
        self.detections_queue: dai.MessageQueue | None = None
        self.host_spatials: HostSpatialsCalc | None = None
        self.latest_depth: dai.ImgFrame | None = None
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

        stereo = pipeline.create(dai.node.StereoDepth).build(
            True,
            dai.node.StereoDepth.PresetMode.FACE,
            fps=self.fps_limit,
        )
        stereo.setDepthAlign(dai.CameraBoardSocket.CAM_A)
        stereo.setLeftRightCheck(True)
        stereo.setSubpixel(False)

        nn_with_parser = pipeline.create(ParsingNeuralNetwork).build(
            rgb,
            nn_archive,
            fps=self.fps_limit,
        )
        # Leave enough SHAVEs for StereoDepth, ImageManip, and spatial calculation.
        nn_with_parser.setNNArchive(nn_archive, numShaves=NN_SHAVES)

        self.host_spatials = HostSpatialsCalc(
            self.device.readCalibration(),
            depthAlignmentSocket=dai.CameraBoardSocket.CAM_A,
            threshLow=DEPTH_LOWER_THRESHOLD_MM,
            threshHigh=DEPTH_UPPER_THRESHOLD_MM,
        )
        self.host_spatials.setDeltaRoi(5)

        if self.visualizer is not None:
            self.visualizer.addTopic("Video", nn_with_parser.passthrough, "images")
            self.visualizer.addTopic("Detections", nn_with_parser.out, "images")

        self.pipeline = pipeline
        self.depth_queue = stereo.depth.createOutputQueue(
            maxSize=4,
            blocking=False,
        )
        self.detections_queue = nn_with_parser.out.createOutputQueue(
            maxSize=4,
            blocking=False,
        )
        print("Pipeline created.")

    def run(self) -> None:
        if self.pipeline is None or self.depth_queue is None:
            raise RuntimeError("Detector pipeline was not created.")

        self.pipeline.start()
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
        if self.depth_queue is None or self.detections_queue is None:
            return

        for depth_frame in self.depth_queue.tryGetAll():
            self.latest_depth = depth_frame

        detections_msg = self.detections_queue.tryGet()
        if detections_msg is None or self.latest_depth is None:
            return

        faces = detections_msg.detections
        self.latest_faces_xyz_m = []
        if not faces:
            print("faces=0")
            return

        print(f"faces={len(faces)}")
        for idx, face in enumerate(faces):
            xyz = self._face_xyz_m(face, self.latest_depth)
            if xyz is None:
                print(f"  face[{idx}] conf={face.confidence:.2f} xyz_m=(no depth)")
                continue

            x_m, y_m, z_m = xyz
            self.latest_faces_xyz_m.append((x_m, y_m, z_m))
            print(
                f"  face[{idx}] conf={face.confidence:.2f} "
                f"xyz_m=({x_m:.3f}, {y_m:.3f}, {z_m:.3f})"
            )

    def _face_xyz_m(
        self,
        face: dai.ImgDetection,
        depth_frame: dai.ImgFrame,
    ) -> tuple[float, float, float] | None:
        if self.host_spatials is None:
            return None

        depth = depth_frame.getFrame()
        height, width = depth.shape[:2]
        roi = self._detection_roi(face, width, height)
        spatials = self.host_spatials.calcSpatials(
            depth_frame,
            roi,
            averagingMethod=np.median,
        )
        xyz_mm = (spatials["x"], spatials["y"], spatials["z"])
        if any(np.isnan(value) for value in xyz_mm):
            return None

        return tuple(value / 1000.0 for value in xyz_mm)

    def _detection_roi(
        self,
        detection: dai.ImgDetection,
        width: int,
        height: int,
    ) -> list[int]:
        shrink = (1.0 - SPATIAL_BBOX_SCALE) / 2.0
        xmin = detection.xmin + (detection.xmax - detection.xmin) * shrink
        ymin = detection.ymin + (detection.ymax - detection.ymin) * shrink
        xmax = detection.xmax - (detection.xmax - detection.xmin) * shrink
        ymax = detection.ymax - (detection.ymax - detection.ymin) * shrink

        if xmin >= xmax:
            center_x = (detection.xmin + detection.xmax) / 2.0
            xmin = center_x - 0.01
            xmax = center_x + 0.01
        if ymin >= ymax:
            center_y = (detection.ymin + detection.ymax) / 2.0
            ymin = center_y - 0.01
            ymax = center_y + 0.01

        return [
            self._normalized_to_index(xmin, width),
            self._normalized_to_index(ymin, height),
            self._normalized_to_index(xmax, width),
            self._normalized_to_index(ymax, height),
        ]

    @staticmethod
    def _normalized_to_index(value: float, limit: int) -> int:
        return min(max(int(value * limit), 0), limit - 1)

    def shutdown(self) -> None:
        if self.pipeline is not None and self.pipeline.isRunning():
            self.pipeline.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--visualizer",
        action="store_true",
        help="Enable DepthAI RemoteConnection image topics.",
    )
    return parser.parse_args()


###############################################################################
# Main Entry | Manual Testing
###############################################################################

if __name__ == "__main__":
    args = parse_args()
    detector = Detector(enable_visualizer=args.visualizer)
    try:
        detector.run()
    except KeyboardInterrupt:
        pass
    finally:
        detector.shutdown()
