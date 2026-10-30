import importlib.util
import sys
import types
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class CameraAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dai = types.ModuleType('depthai')
        dai.Clock = SimpleNamespace(now=lambda: timedelta(seconds=250.))
        node = types.ModuleType('depthai_nodes.node')
        node.ParsingNeuralNetwork = object
        package = types.ModuleType('depthai_nodes')
        package.node = node
        name = 'camera_adapter_test'
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / 'camera' / 'detector.py')
        cls.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'depthai': dai, 'depthai_nodes': package, 'depthai_nodes.node': node,
                                      name: cls.module}):
            spec.loader.exec_module(cls.module)

    def face(self, z=2000.):
        return SimpleNamespace(confidence=0.85, xmin=0.2, ymin=0.3, xmax=0.4, ymax=0.6,
                               spatialCoordinates=SimpleNamespace(x=100., y=-200., z=z))

    def detector(self, messages):
        detector = self.module.Detector.__new__(self.module.Detector)
        detector.start = Mock()
        detector.spatial_detections_queue = SimpleNamespace(tryGetAll=lambda: messages)
        return detector

    def message(self, faces):
        return SimpleNamespace(detections=faces, getTimestamp=lambda: timedelta(seconds=249.8),
                               getSequenceNum=lambda: 17)

    def test_timestamp_translation_preserves_capture_age_and_metadata(self):
        detector = self.detector([self.message([self.face()])])
        with patch.object(self.module, 'monotonic', return_value=1000.):
            frame = detector.poll_frame()
        self.assertAlmostEqual(frame.timestamp, 999.8)
        self.assertEqual(frame.sequence, 17)
        self.assertEqual(frame.capture_key, '17-249800000')
        self.assertEqual(frame.faces[0].bbox, (0.2, 0.3, 0.4, 0.6))
        self.assertEqual(frame.faces[0].xyz_m, (0.1, -0.2, 2.))
        self.assertEqual(frame.faces[0].confidence, 0.85)

    def test_absent_message_and_observed_empty_frame_are_distinct(self):
        self.assertIsNone(self.detector([]).poll_frame())
        self.assertEqual(self.detector([self.message([])]).poll_frame().faces, [])

    def test_invalid_depth_does_not_remove_detected_face_or_box(self):
        frame = self.detector([self.message([self.face(0.)])]).poll_frame()
        self.assertEqual(len(frame.faces), 1)
        self.assertIsNone(frame.faces[0].xyz_m)
        self.assertIsNotNone(frame.faces[0].bbox)

    def test_spatial_depth_range_and_finite_values_are_checked(self):
        for depth in (float('nan'), 199., 5001.):
            self.assertIsNone(self.module.Detector._spatial_detection_xyz_m(self.face(depth)))
        for depth in (200., 5000.):
            self.assertIsNotNone(self.module.Detector._spatial_detection_xyz_m(self.face(depth)))

    def test_bad_image_box_does_not_discard_valid_xyz(self):
        face = self.face()
        face.xmin = float('nan')
        result = self.detector([self.message([face])]).poll_frame().faces[0]
        self.assertIsNone(result.bbox)
        self.assertIsNotNone(result.xyz_m)

    def test_reused_sequence_still_has_distinct_capture_identity(self):
        first = self.message([])
        second = self.message([])
        second.getTimestamp = lambda: timedelta(seconds=249.9)
        self.assertNotEqual(self.detector([first]).poll_frame().capture_key,
                            self.detector([second]).poll_frame().capture_key)

    def test_pipeline_consumes_yunet_on_host_with_latest_only_inputs(self):
        for preview in (False, True):
            with self.subTest(preview=preview):
                detector = self.module.Detector.__new__(self.module.Detector)
                detector.model_archive = Path(__file__)
                detector.device = object()
                detector.fps_limit = 15
                detector.enable_preview = preview
                detector.visualizer = None
                detector._nn_input_size = Mock(return_value=(640, 360))
                detector._nn_frame_type = Mock(return_value='BGR888p')
                dai = Mock()
                pipeline, camera, stereo, nn, align, spatial = [Mock() for _ in range(6)]
                dai.Pipeline.return_value = pipeline
                camera.build.return_value = camera
                stereo.build.return_value = stereo
                nn.build.return_value = nn
                # setNNArchive rebuilds the parser; configure the final instance.
                old_parser, parser = Mock(), Mock()
                nn.getParser.return_value = old_parser
                nn.setNNArchive.side_effect = lambda *a, **kw: setattr(nn.getParser, 'return_value', parser)
                nodes = {dai.node.Camera: camera, dai.node.StereoDepth: stereo,
                         self.module.ParsingNeuralNetwork: nn, dai.node.ImageAlign: align,
                         dai.node.SpatialLocationCalculator: spatial}
                pipeline.create.side_effect = nodes.__getitem__

                with patch.object(self.module, 'dai', dai):
                    detector._build_pipeline()

                spatial.setRunOnHost.assert_called_once_with(True)
                align.setRunOnHost.assert_called_once_with(False)
                for input_queue in (nn.input, parser.input, align.input, align.inputAlignTo,
                                    spatial.inputDepth, spatial.inputDetections):
                    input_queue.setBlocking.assert_called_once_with(False)
                    input_queue.setMaxSize.assert_called_once_with(1)
                old_parser.input.setBlocking.assert_not_called()
                nn.out.link.assert_called_once_with(spatial.inputDetections)
                align.outputAligned.link.assert_called_once_with(spatial.inputDepth)
                spatial.outputDetections.createOutputQueue.assert_called_once_with(maxSize=1, blocking=False)
                if preview:
                    nn.passthrough.createOutputQueue.assert_called_once_with(maxSize=4, blocking=False)
                else:
                    nn.passthrough.createOutputQueue.assert_not_called()
                pipeline.start.assert_not_called()

    def test_shutdown_releases_camera_even_if_pipeline_stop_fails(self):
        detector = self.module.Detector.__new__(self.module.Detector)
        detector.pipeline = Mock()
        detector.pipeline.isRunning.return_value = True
        detector.pipeline.stop.side_effect = RuntimeError('stop error')
        detector.device = Mock()
        with self.assertRaises(RuntimeError):
            detector.shutdown()
        detector.device.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
