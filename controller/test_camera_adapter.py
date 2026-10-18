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
        spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / 'camera' / 'detector.py')
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


if __name__ == '__main__':
    unittest.main()
