import json
import math
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from conversions import Conversions
from data_types import CameraConfig, Detection, EyeConfig, Position3D
from face_tracker import FaceTracker
from main import Controller, main
from demo import get_detections
from replay import evaluate


class ControllerTimingTests(unittest.TestCase):
    def test_demo_runs_without_camera_or_gui_and_records_replayable_project_detections(self):
        now = [1.]
        with patch.dict('sys.modules', {'camera.detector': None, 'depthai': None,
                                       'PySide6': None, 'pyqtgraph': None, 'matplotlib': None}), \
             patch('main.Publisher') as publisher:
            controller = Controller(demo=True, monitor=False)
            controller.tracker.min_hits_to_confirm = 1
            sleeps = []

            def sleep(duration):
                sleeps.append(duration)
                now[0] += duration
                if len(sleeps) == 3:
                    controller.running = False

            try:
                with tempfile.TemporaryDirectory() as directory:
                    recording = Path(directory) / 'demo.jsonl'
                    with patch('main.time.monotonic', side_effect=lambda: now[0]), \
                         patch('main.time.sleep', side_effect=sleep):
                        controller.run(str(recording))
                    records = [json.loads(line) for line in recording.read_text().splitlines()]
                self.assertEqual([r['sequence'] for r in records], [0, 1, 2])
                for index, record in enumerate(records):
                    self.assertEqual(record['detections'], [asdict(d) for d in get_detections(index)])
                    self.assertAlmostEqual(record['timestamp'], 1. + index / 15)
                self.assertEqual(evaluate(records)['frames'], 3)
                self.assertEqual(publisher.return_value.send.call_count, 3)
                self.assertEqual(set(publisher.return_value.send.call_args.args[0]), set(range(1, 7)))
                for duration in sleeps:
                    self.assertAlmostEqual(duration, 1 / 15)
            finally:
                controller.shutdown()
            publisher.return_value.close.assert_called_once()

    def test_demo_cli_shares_recording_monitoring_and_shutdown_options(self):
        with patch('main.Controller') as controller, patch('main.signal.signal'):
            controller.return_value.run.side_effect = KeyboardInterrupt
            main(['--demo', '--no-monitor', '--record', '/tmp/demo.jsonl'])
            controller.assert_called_once_with(monitor=False, demo=True)
            controller.return_value.run.assert_called_once_with(record_path='/tmp/demo.jsonl')
            controller.return_value.shutdown.assert_called_once()

    def test_no_frame_is_not_a_miss_and_processing_time_is_subtracted_from_sleep(self):
        now = [1.]
        controller = Controller.__new__(Controller)
        controller.running = True
        controller.tracker = Mock()
        controller.tracker.get_output.return_value = {}
        controller.eye_mgr = SimpleNamespace(update=Mock(return_value={}))
        controller.publisher = SimpleNamespace(send=Mock())
        face = SimpleNamespace(xyz_m=(0., 0., 2.), bbox=(0.2, 0.2, 0.4, 0.4), confidence=0.9)
        frames = iter([SimpleNamespace(sequence=1, timestamp=0.98, faces=[face]), None,
                       SimpleNamespace(sequence=1, timestamp=1.11, faces=[])])
        def poll():
            now[0] += 0.01
            return next(frames)
        sleeps = []
        def sleep(duration):
            sleeps.append(duration)
            now[0] += duration
            if len(sleeps) == 3:
                controller.running = False
        controller.detector = SimpleNamespace(poll_frame=poll)
        with tempfile.TemporaryDirectory() as directory:
            recording = Path(directory) / 'captures.jsonl'
            with patch('main.time.monotonic', side_effect=lambda: now[0]), patch('main.time.sleep', side_effect=sleep):
                controller.run(str(recording))
            records = [json.loads(line) for line in recording.read_text().splitlines()]
        self.assertEqual(controller.tracker.update.call_count, 2)
        self.assertEqual(controller.tracker.update.call_args_list[1].args[0], [])
        self.assertEqual(controller.publisher.send.call_count, 3)
        for duration in sleeps:
            self.assertAlmostEqual(duration, 1 / 15 - 0.01)
        self.assertEqual(len(records), 2)
        # Capture time remains authoritative when a camera reuses sequence IDs.
        self.assertEqual([record['sequence'] for record in records], [1, 1])
        self.assertEqual(records[0]['detections'][0]['position'], {'x': 2., 'y': -0., 'z': -0.})
        self.assertEqual(records[0]['detections'][0]['confidence'], 0.9)

    def test_invalid_depth_keeps_box_and_confidence(self):
        result = Controller._camera_xyz_to_detection(None, bbox=(0., 0., 0.5, 0.5), confidence=0.8)
        self.assertIsNone(result.position)
        self.assertEqual(result.confidence, 0.8)
        self.assertEqual(result.depth_quality, 0.)
        self.assertIsNotNone(result.bbox)

    def test_yaw_uses_all_gimbal_translation_components(self):
        eye = EyeConfig(1, Position3D(0.3, -0.2, 0.))
        conversions = Conversions([eye], CameraConfig(0.1, 0., 0.))
        yaw, pitch = conversions.get_pitch_yaw(1, Position3D(1., 0.2, 0.))
        self.assertAlmostEqual(yaw, math.degrees(math.atan2(0.4, 0.8)))
        self.assertAlmostEqual(pitch, 0.)


class ReplayTests(unittest.TestCase):
    def frame(self, timestamp, detections, truth=None):
        result = {'timestamp': timestamp, 'detections': [asdict(d) for d in detections]}
        if truth is not None:
            result['truth'] = [{'id': identity, 'position': asdict(position)} for identity, position in truth]
        return result

    def test_crossing_with_irregular_timing_and_short_dropout_preserves_identity(self):
        tracker = FaceTracker()
        tracker.min_hits_to_confirm = 2
        timestamps = np.cumsum([0.05, 0.09, 0.06, 0.07] * 30)
        frames = []
        for index, timestamp in enumerate(timestamps):
            positions = [('a', Position3D(2., -0.6 + timestamp * 0.15, 0.)),
                         ('b', Position3D(2.8, 0.6 - timestamp * 0.15, 0.))]
            detections = [Detection(position) for identity, position in positions
                          if not (identity == 'a' and 50 <= index < 53)]
            if index % 2:
                detections.reverse()
            frames.append(self.frame(float(timestamp), detections, positions))
        metrics = evaluate(frames, tracker)
        self.assertEqual(metrics['id_switches'], 0)
        self.assertEqual(metrics['fragmentations'], 0)
        self.assertEqual(metrics['track_ids_created'], 2)
        self.assertLess(metrics['mean_position_error_m'], 0.04)
        self.assertLess(metrics['mean_target_angle_error_deg'], 1.)

    def test_unlabelled_recordings_do_not_claim_identity_accuracy(self):
        metrics = evaluate([self.frame(0., [Detection(Position3D(2, 0, 0))])])
        self.assertEqual(metrics['frames'], 1)
        self.assertIsNone(metrics['id_switches'])
        self.assertIsNone(metrics['mean_target_angle_error_deg'])

    def test_replay_validates_timestamp_order(self):
        with self.assertRaises(ValueError):
            evaluate([self.frame(1., []), self.frame(1., [])])


if __name__ == '__main__':
    unittest.main()
