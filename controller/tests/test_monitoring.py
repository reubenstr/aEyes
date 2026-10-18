import asyncio
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from data_types import Detection, Position3D
from face_tracker import FaceTracker
from monitoring.bridge import MonitorBridge
from monitoring.compute import ComputeInspector
from monitoring.config_store import ConfigStore
from monitoring.contracts import capture_key, geometry, revision
from monitoring.eye_health import ping_eye
from monitoring.server import create_app
from monitoring.state import MonitorState, FeedSubscriber
from monitoring.video import VideoCache


def snapshot(now=10., session='one', capture='1-10000000'):
    face = {'id': 0, 'status': 'confirmed', 'position': {'x': 2., 'y':0., 'z':0.},
            'bbox':[.25,.25,.75,.75], 'confidence':.9, 'last_seen':now, 'last_depth_seen':now,
            'visible':True, 'is_static':False}
    eyes = [{'eye_id':i, 'face_id':0, 'iris_color':[100,150,200],
             'target_iris_color':[100,150,200]} for i in range(1,7)]
    return {'schema_version':1, 'session_id':session, 'timestamp':now,
            'source':'main', 'camera_available':True,
            'timing':{'capture_fps':15., 'publish_hz':15., 'dropped_snapshots':0},
            'faces':[face], 'eyes':eyes, 'geometry':geometry(),
            'observation':{'capture_key':capture, 'timestamp':now, 'sequence':1, 'faces':[face], 'eyes':eyes}}


class VideoTests(unittest.TestCase):
    def setUp(self):
        self.cache = VideoCache()
        self.cache.set_session('one')
        self.cache.set_assignments('one', {0})
        self.image = np.full((100,100,3), (50,100,150), np.uint8)

    def add(self, capture='1-10000000', now=10.):
        state = snapshot(now=now, capture=capture)
        self.cache.image({'session_id':'one','capture_key':capture,'timestamp':now}, self.image)
        self.cache.observe('one', state['observation'])
        self.cache.render(now)

    def test_pairing_deduplicates_shared_faces_and_preserves_raw_crop(self):
        self.add()
        self.assertEqual(len(self.cache.crops), 1)
        crop = self.cache.crop('one','1-10000000',0)
        decoded = cv2.imdecode(np.frombuffer(crop,np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, (50,50,3))
        self.cache.render(100.)
        self.assertEqual(self.cache.crop('one','1-10000000',0), crop)
        self.assertIn('0', self.cache.crop_metadata())
        self.assertIsNone(self.cache.crop('two','1-10000000',0))

    def test_image_before_metadata_does_not_invent_crop(self):
        self.cache.image({'session_id':'one','capture_key':'a','timestamp':10.}, self.image)
        self.cache.render(10.)
        self.assertIsNone(self.cache.jpeg)
        self.cache.render(10.21)
        self.assertIsNotNone(self.cache.jpeg)
        self.assertEqual(self.cache.crops,{})
        self.cache.observe('one', snapshot(capture='a')['observation'])
        self.cache.render(10.32)
        self.assertIsNotNone(self.cache.crop('one','a',0))

    def test_delayed_detections_keep_boxes_and_crops_while_newer_images_arrive(self):
        for index in range(20):
            captured = 10. + index * .11
            raw = np.full((100,100,3), (20 + index,60,90), np.uint8)
            self.cache.image({'session_id':'one','capture_key':str(index),
                              'timestamp':captured}, raw)
            if index:
                previous = 10. + (index - 1) * .11
                self.cache.observe('one', snapshot(now=previous, capture=str(index - 1))['observation'])
            self.cache.render(captured + .01)
            if not index:
                continue
            self.assertEqual(self.cache.rendered, (str(index - 1), True))
            self.assertAlmostEqual(self.cache.timestamp, previous)
            preview = cv2.imdecode(np.frombuffer(self.cache.jpeg,np.uint8), cv2.IMREAD_COLOR)
            # Interior pixels identify the selected capture; the border must be annotated.
            np.testing.assert_allclose(preview[50,50], (19 + index,60,90), atol=3)
            self.assertGreater(int(preview[50,25,0]), 70)
            self.assertIn('0', self.cache.crop_metadata())

    def test_missing_metadata_has_bounded_wait_without_borrowing_old_boxes(self):
        self.add('a',10.)
        for key, captured in [('b',10.11), ('c',10.22)]:
            self.cache.image({'session_id':'one','capture_key':key,'timestamp':captured}, self.image)
            self.cache.render(captured)
            self.assertEqual(self.cache.rendered, ('a', True))
        self.cache.image({'session_id':'one','capture_key':'d','timestamp':10.33}, self.image)
        self.cache.render(10.33)
        self.assertEqual(self.cache.rendered, ('d', False))
        preview = cv2.imdecode(np.frombuffer(self.cache.jpeg,np.uint8), cv2.IMREAD_COLOR)
        np.testing.assert_allclose(preview[50,25], self.image[50,25], atol=3)
        self.assertIsNone(self.cache.crop('one','d',0))

    def test_crop_updates_even_when_its_pair_is_not_rendered(self):
        self.add('a',10.)
        self.cache.image({'session_id':'one','capture_key':'b','timestamp':10.25}, self.image)
        self.cache.image({'session_id':'one','capture_key':'c','timestamp':10.26}, self.image)
        empty = snapshot(now=10.26, capture='c')['observation']
        empty['faces'] = []
        self.cache.observe('one', empty)
        self.cache.render(10.26)
        self.assertEqual(self.cache.rendered, ('c', True))

        self.cache.observe('one', snapshot(now=10.25, capture='b')['observation'])
        self.cache.render(10.28)
        self.assertEqual(self.cache.rendered, ('c', True))
        self.assertAlmostEqual(self.cache.timestamp, 10.26)
        self.assertIsNotNone(self.cache.crop('one','b',0))
        self.assertIn('capture=b', self.cache.crop_metadata()['0'])
        self.cache.render(10.40)
        self.assertEqual(self.cache.rendered, ('c', True))
        self.cache.render(100.)
        self.assertIsNotNone(self.cache.crop('one','b',0))
        self.assertIn('capture=b', self.cache.crop_metadata()['0'])

    def test_delayed_pairs_restore_annotations_after_raw_video_fallback(self):
        self.add('a',10.)
        for key, captured in [('b',10.11), ('c',10.22), ('d',10.33)]:
            self.cache.image({'session_id':'one','capture_key':key,'timestamp':captured}, self.image)
            self.cache.render(captured)
        self.assertEqual(self.cache.rendered, ('d', False))
        self.cache.render(10.44)
        self.assertEqual(self.cache.rendered, ('d', False))

        # C is a new completed pair, even though raw D was already displayed.
        self.cache.observe('one', snapshot(now=10.22, capture='c')['observation'])
        self.cache.render(10.45)
        self.assertEqual(self.cache.rendered, ('c', True))
        self.assertIsNotNone(self.cache.crop('one','c',0))
        # Still older results cannot replay pairs behind completed C.
        self.cache.observe('one', snapshot(now=10.11, capture='b')['observation'])
        self.cache.render(10.56)
        self.assertEqual(self.cache.rendered, ('c', True))
        self.cache.image({'session_id':'one','capture_key':'e','timestamp':10.44}, self.image)
        self.cache.observe('one', snapshot(now=10.33, capture='d')['observation'])
        self.cache.render(10.57)
        self.assertEqual(self.cache.rendered, ('d', True))

    def test_empty_detection_result_clears_boxes_without_waiting(self):
        self.add('a',10.)
        empty = snapshot(now=10.21, capture='b')['observation']
        empty.update(faces=[], detections=[])
        self.cache.observe('one', empty)
        self.cache.image({'session_id':'one','capture_key':'b','timestamp':10.21}, self.image)
        self.cache.render(10.21)
        self.assertEqual(self.cache.rendered, ('b', True))
        preview = cv2.imdecode(np.frombuffer(self.cache.jpeg,np.uint8), cv2.IMREAD_COLOR)
        np.testing.assert_allclose(preview[50,25], self.image[50,25], atol=3)
        self.assertIsNone(self.cache.crop('one','b',0))

    def test_stale_pair_cannot_create_a_fresh_crop(self):
        self.cache.image({'session_id':'one','capture_key':'a','timestamp':10.}, self.image)
        self.cache.observe('one', snapshot(capture='a')['observation'])
        self.cache.render(11.1)
        self.assertEqual(self.cache.crop_metadata(), {})
        self.assertIsNone(self.cache.crop('one','a',0))

    def test_reused_sequence_cannot_pair_with_old_timestamp(self):
        self.add('1-10000000',10.)
        self.cache.image({'session_id':'one','capture_key':'1-10200000','timestamp':10.2}, self.image)
        self.cache.render(10.21)
        self.assertIsNone(self.cache.crop('one','1-10200000',0))

    def test_last_crop_survives_history_eviction_by_another_assigned_face(self):
        self.cache.set_assignments('one', {0, 1})
        self.add('a',10.)
        retained = self.cache.crop('one','a',0)
        for index in range(20):
            captured = 10.25 + index * .25
            key = f'other-{index}'
            observation = snapshot(now=captured, capture=key)['observation']
            observation['faces'][0]['id'] = 1
            for eye in observation['eyes']:
                eye['face_id'] = 1
            self.cache.observe('one', observation)
            self.cache.image({'session_id':'one','capture_key':key,'timestamp':captured}, self.image)
            self.cache.render(captured)
        self.assertNotIn(('one','a',0), self.cache.crops)
        self.assertEqual(self.cache.crop('one','a',0), retained)
        self.assertIn('capture=a', self.cache.crop_metadata()['0'])
        self.assertEqual(len(self.cache.latest_crops), 2)
        self.assertLessEqual(len(self.cache.crops), 16)

    def test_releasing_assignment_removes_crops_even_with_old_observations_cached(self):
        self.add('a',10.)
        self.cache.set_assignments('one', {1})
        self.cache.render(10.3)
        self.assertEqual(self.cache.crop_metadata(), {})
        self.assertEqual(self.cache.crops, {})
        self.assertIsNone(self.cache.crop('one','a',0))

    def test_pairing_cache_and_crop_cache_are_bounded_and_session_clears(self):
        for i in range(30):
            self.add(f'{i}-{i}',10.+i*.25)
        self.assertLessEqual(len(self.cache.images),4)
        self.assertLessEqual(len(self.cache.observations),4)
        self.assertLessEqual(len(self.cache.crops),16)
        self.cache.set_session('two')
        self.assertIsNone(self.cache.jpeg)
        self.assertEqual(self.cache.latest_crops,{})
        restarted = snapshot(now=1., session='two', capture='restart')
        self.cache.set_assignments('two', {0})
        self.cache.observe('two', restarted['observation'])
        self.cache.image({'session_id':'two','capture_key':'restart','timestamp':1.}, self.image)
        self.cache.render(1.)
        self.assertEqual(self.cache.rendered, ('restart', True))
        self.assertIsNotNone(self.cache.crop('two','restart',0))

    def test_unassigned_or_unmatched_boxes_never_produce_crops(self):
        state = snapshot()
        state['observation']['eyes'] = []
        self.cache.observe('one',state['observation'])
        self.cache.image({'session_id':'one','capture_key':'1-10000000','timestamp':10.},self.image)
        self.cache.render(10.)
        self.assertEqual(self.cache.crops,{})


class StateTests(unittest.TestCase):
    def test_current_assignments_retain_and_release_crops_without_new_camera_frames(self):
        state = MonitorState()
        state.accept(snapshot())
        state.video.image({'session_id':'one','capture_key':'1-10000000','timestamp':10.},
                          np.zeros((100,100,3),np.uint8))
        state.video.render(10.)
        retained = state.video.crop('one','1-10000000',0)
        for timestamp in (20., 100.):
            current = snapshot(now=timestamp)
            current['observation'] = None
            for eye in current['eyes'][1:]:
                eye['face_id'] = None
            state.accept(current)
            description = state.describe(now=timestamp+.1)
            self.assertEqual(description['camera']['status'], 'stale')
            self.assertEqual(description['controller']['status'], 'running')
            self.assertIn('0', description['crops'])
            self.assertEqual(state.video.crop('one','1-10000000',0), retained)

        released = snapshot(now=101.)
        # Frame metadata still describes the old assignment; current eyes take precedence.
        released['observation'] = snapshot()['observation']
        for eye in released['eyes']:
            eye['face_id'] = None
        state.accept(released)
        state.video.render(101.)
        self.assertEqual(state.describe(now=101.1)['crops'], {})
        self.assertEqual(state.video.latest_crops, {})
        self.assertIsNone(state.video.crop('one','1-10000000',0))

    def test_camera_and_controller_silence_go_stale_without_new_frames(self):
        state = MonitorState(); state.accept(snapshot())
        state.video.image({'session_id':'one','capture_key':'1-10000000','timestamp':10.}, np.zeros((10,10,3),np.uint8))
        state.video.render(10.)
        self.assertEqual(state.describe(now=10.1)['camera']['status'],'streaming')
        self.assertEqual(state.describe(now=12.)['camera']['status'],'stale')
        self.assertEqual(state.describe(now=12.)['crops'],{})
        self.assertEqual(state.describe(now=12.)['controller']['status'],'stale')
        stale = state.describe(now=12.)
        self.assertEqual(stale['faces'], [])
        self.assertEqual(stale['eyes'], [])
        self.assertIsNone(stale['timing'])
        self.assertIsNone(stale['active_config'])

    def test_stale_process_metrics_are_hidden_while_host_health_remains(self):
        state = MonitorState()
        state.accept(snapshot())
        state.compute = {'cpu_percent': 12, 'process': {'pid': 123}}
        state.health[0]['status'] = 'reachable'
        current = state.describe(now=12.)
        self.assertEqual(current['system']['cpu_percent'], 12)
        self.assertIsNone(current['system']['process'])
        self.assertEqual(current['eye_health'][0]['status'], 'reachable')
        self.assertIsNotNone(state.compute['process'])

    def test_restart_cannot_be_overwritten_by_retired_session_or_old_timestamp(self):
        state=MonitorState(); state.accept(snapshot())
        state.accept(snapshot(now=11.,session='two'))
        state.accept(snapshot(now=12.,session='one'))
        state.accept(snapshot(now=10.,session='two'))
        self.assertEqual(state.source['session_id'],'two')
        self.assertEqual(state.source['timestamp'],11.)

    def test_switching_between_main_and_demo_resets_video_and_source_capabilities(self):
        state = MonitorState()
        state.accept(snapshot())
        state.video.image({'session_id':'one', 'capture_key':'1-10000000', 'timestamp':10.},
                          np.zeros((10,10,3), np.uint8))
        state.video.render(10.)
        demo = snapshot(now=10.2, session='demo')
        demo.update(source='demo', camera_available=False, observation=None)
        state.accept(demo)
        current = state.describe(now=10.3)
        self.assertEqual(current['source'], 'demo')
        self.assertEqual(current['controller']['status'], 'running')
        self.assertEqual(current['camera']['status'], 'unavailable')
        self.assertIsNone(current['camera']['capture_key'])
        self.assertEqual(current['crops'], {})
        self.assertIsNone(state.video.preview()[1])
        state.accept(snapshot(now=10.4, session='new-main'))
        current = state.describe(now=10.5)
        self.assertEqual(current['source'], 'main')
        self.assertTrue(current['camera']['available'])
        self.assertEqual(current['crops'], {})

    def test_tracker_diagnostics_are_copied_and_do_not_advance_filters(self):
        tracker=FaceTracker(); tracker.min_hits_to_confirm=1
        tracker.update([Detection(Position3D(2,0,0),bbox=(.2,.2,.4,.4))],timestamp=1.)
        original=tracker.tracks[0].kalman.state.copy()
        diagnostics=tracker.get_diagnostics(1.2)
        diagnostics[0]['position']['x']=999
        diagnostics[0]['bbox'][0]=999
        np.testing.assert_array_equal(tracker.tracks[0].kalman.state,original)
        self.assertEqual(tracker.tracks[0].bbox[0],.2)

    def test_bridge_drops_old_snapshots_without_serializing_or_waiting(self):
        with patch('monitoring.bridge.Thread.start'):
            bridge=MonitorBridge()
        with patch('json.dumps',side_effect=AssertionError('serialization on caller')):
            for i in range(100): bridge.offer_snapshot({'i':i})
        self.assertEqual(bridge.pending.qsize(),1)
        self.assertEqual(bridge.pending.get_nowait(),{'i':99})
        self.assertEqual(bridge.dropped,99)

    def test_backend_import_does_not_load_hardware_or_live_parameters(self):
        code="import monitoring.server,sys; assert not set(['depthai','parameters','main','publisher','face_tracker']).intersection(sys.modules)"
        subprocess.run([sys.executable,'-c',code],check=True,cwd=Path(__file__).resolve().parents[1])

    def test_api_and_websocket_wait_for_an_application_without_generating_data(self):
        app=create_app(start_workers=False)
        with TestClient(app) as client:
            with client.websocket_connect('/api/ws') as ws:
                data=ws.receive_json()
                self.assertIsNone(data['source'])
                self.assertNotIn('demo', data)
                self.assertEqual(data['controller']['status'],'offline')
                self.assertEqual(data['faces'], [])
                self.assertEqual(data['eyes'], [])
            self.assertIsNone(app.state.monitor.video.preview()[1])
            self.assertEqual(client.get('/api/health').json()['status'],'ok')

    def test_api_serves_camera_images_only_from_a_fresh_application(self):
        state = MonitorState()
        now = time.monotonic()
        state.accept(snapshot(now=now))
        state.video.image({'session_id':'one', 'capture_key':'1-10000000', 'timestamp':now},
                          np.zeros((100,100,3), np.uint8))
        state.video.render(now)
        app = create_app(state=state, start_workers=False)
        with TestClient(app) as client:
            data=client.get('/api/state').json()
            self.assertEqual(data['source'], 'main')
            self.assertEqual(data['camera']['status'], 'streaming')
            self.assertEqual(len(data['eyes']),6)
            self.assertEqual(len(data['crops']),1)
            crop_url = next(iter(data['crops'].values()))
            response=client.get(crop_url)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['content-type'],'image/jpeg')
            with patch('monitoring.state.time.monotonic', return_value=now+2):
                self.assertEqual(client.get('/api/state').json()['eyes'], [])
                self.assertEqual(client.get(crop_url).status_code, 404)

    def test_api_keeps_assigned_crop_available_during_camera_gaps_and_rejects_released_crops(self):
        state = MonitorState()
        now = time.monotonic()
        state.accept(snapshot(now=now))
        state.video.image({'session_id':'one','capture_key':'1-10000000','timestamp':now},
                          np.zeros((100,100,3),np.uint8))
        state.video.render(now)
        app = create_app(state=state, start_workers=False)
        with TestClient(app) as client:
            crop_url = client.get('/api/state').json()['crops']['0']
            original = client.get(crop_url).content
            current = snapshot(now=now+10)
            current['observation'] = None
            state.accept(current)
            with patch('monitoring.state.time.monotonic', return_value=now+10.1):
                data = client.get('/api/state').json()
                self.assertEqual(data['camera']['status'], 'stale')
                self.assertEqual(data['crops']['0'], crop_url)
                response = client.get(crop_url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, original)
                self.assertEqual(client.get(crop_url.replace('session=one','session=other')).status_code, 404)
                self.assertEqual(client.get(crop_url.replace('capture=1-10000000','capture=missing')).status_code, 404)

            released = snapshot(now=now+10.2)
            released['observation'] = None
            for eye in released['eyes']:
                eye['face_id'] = None
            state.accept(released)
            with patch('monitoring.state.time.monotonic', return_value=now+10.3):
                self.assertEqual(client.get('/api/state').json()['crops'], {})
                self.assertEqual(client.get(crop_url).status_code, 404)

            state.accept(snapshot(now=now+11, session='two'))
            with patch('monitoring.state.time.monotonic', return_value=now+11.1):
                self.assertEqual(client.get(crop_url).status_code, 404)

    def test_main_monitoring_is_enabled_by_default_and_can_be_disabled(self):
        from main import Controller
        detector = Mock()
        with patch.dict(sys.modules, {'camera.detector': SimpleNamespace(Detector=detector)}), \
             patch('main.FaceTracker'), patch('main.EyeManager'), patch('main.Publisher'), \
             patch('monitoring.bridge.MonitorBridge') as bridge:
            controller = Controller()
            detector.assert_called_with(enable_visualizer=False, enable_preview=True)
            bridge.assert_called_once()
            controller.shutdown()
            bridge.reset_mock()
            controller = Controller(monitor=False)
            detector.assert_called_with(enable_visualizer=False, enable_preview=False)
            bridge.assert_not_called()
            controller.shutdown()

    def test_demo_publishes_real_pipeline_state_on_the_monotonic_clock_and_closes(self):
        from main import Controller
        now = time.monotonic()
        with patch('main.Publisher') as publisher, \
             patch('monitoring.bridge.Thread.start'), patch('time.monotonic', return_value=now):
            demo = Controller(demo=True)
            demo.tracker.min_hits_to_confirm = 1
            with patch('main.time.sleep', side_effect=lambda _: setattr(demo, 'running', False)):
                demo.run()
            packet = demo.monitor.pending.get_nowait()
            state = MonitorState()
            state.accept(packet)
            current = state.describe(now=now+.01)
            self.assertEqual(current['source'], 'demo')
            self.assertEqual(current['controller']['status'], 'running')
            self.assertEqual(current['camera']['status'], 'unavailable')
            self.assertFalse(current['camera']['available'])
            self.assertEqual(current['crops'], {})
            self.assertTrue(any(face['visible'] for face in current['faces']))
            self.assertTrue(all(face['observation_age_s'] < .02 for face in current['faces']))
            commands = publisher.return_value.send.call_args.args[0]
            for eye in current['eyes']:
                self.assertEqual(eye['yaw'], commands[eye['eye_id']].yaw)
                self.assertEqual(eye['pitch'], commands[eye['eye_id']].pitch)
            self.assertTrue(demo.monitor.pending.empty())
            self.assertEqual(state.describe(now=now+2)['faces'], [])
            with patch.object(demo.monitor.worker, 'join'):
                demo.shutdown()
            self.assertTrue(demo.monitor.stop_event.is_set())
            publisher.return_value.close.assert_called_once()

    def test_demo_monitoring_failure_does_not_interrupt_command_publication(self):
        from main import Controller
        with patch('main.Publisher'), patch('monitoring.bridge.MonitorBridge'):
            demo = Controller(demo=True)
            demo.monitor.offer.side_effect = RuntimeError('observer failure')
            with patch('main.time.sleep', side_effect=lambda _: setattr(demo, 'running', False)):
                with self.assertLogs(level='ERROR'):
                    demo.run()
            demo.publisher.send.assert_called_once()
            demo.shutdown()

    def test_snapshot_failure_does_not_interrupt_controller_publication(self):
        from main import Controller
        controller=Controller.__new__(Controller)
        controller.running=True
        controller.detector=SimpleNamespace(poll_frame=lambda:None)
        controller.tracker=Mock()
        controller.tracker.get_output.return_value={}
        controller.eye_mgr=SimpleNamespace(update=Mock(return_value={}))
        controller.publisher=Mock()
        controller.monitor=SimpleNamespace(offer=Mock(side_effect=RuntimeError('observer failure')))
        with patch('main.time.monotonic',return_value=1.), patch('main.time.sleep',side_effect=lambda _:setattr(controller,'running',False)):
            with self.assertLogs(level='ERROR'):
                controller.run()
        controller.publisher.send.assert_called_once_with({})
        controller.tracker.update.assert_not_called()

    def test_real_transport_delivers_latest_state_and_survives_a_producer_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            state=MonitorState()
            endpoint=f'ipc://{directory}/feed.sock'
            subscriber=FeedSubscriber(state,endpoint)
            subscriber.start()
            bridge=MonitorBridge(endpoint=endpoint)
            try:
                for session in ('one','two'):
                    if session == 'two':
                        bridge.close()
                        bridge=MonitorBridge(endpoint=endpoint)
                    deadline=time.monotonic()+3
                    while time.monotonic()<deadline:
                        bridge.offer_snapshot(snapshot(now=time.monotonic(),session=session))
                        with state.lock:
                            arrived=bool(state.source and state.source['session_id']==session)
                        if arrived:
                            break
                        time.sleep(.03)
                    self.assertTrue(arrived)
            finally:
                bridge.close()
                subscriber.close()


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_ping_success_failure_missing_command_and_timeout(self):
        for result,expected in [(0,'reachable'),(1,'unreachable')]:
            process=Mock(returncode=result); process.wait=AsyncMock(return_value=result)
            with patch('monitoring.eye_health.asyncio.create_subprocess_exec',return_value=process):
                self.assertEqual((await ping_eye(1))['status'],expected)
        with patch('monitoring.eye_health.asyncio.create_subprocess_exec',side_effect=FileNotFoundError()):
            self.assertEqual((await ping_eye(1))['status'],'unknown')
        process=Mock(returncode=None); process.wait=AsyncMock(return_value=0)
        async def timeout(awaitable, duration):
            awaitable.close()
            raise asyncio.TimeoutError
        with patch('monitoring.eye_health.asyncio.create_subprocess_exec',return_value=process):
            with patch('monitoring.eye_health.asyncio.wait_for',side_effect=timeout):
                self.assertEqual((await ping_eye(1))['status'],'unreachable')
        process.kill.assert_called_once()

    async def test_compute_handles_missing_process_and_temperature(self):
        inspector=ComputeInspector()
        with patch('monitoring.compute.psutil.sensors_temperatures',return_value={}):
            sample=inspector.sample(999999999)
        self.assertIsNone(sample['process'])
        self.assertIsNone(sample['temperature_c'])
        self.assertGreater(sample['ram_total_bytes'],0)
