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
            'faces':[face], 'eyes':eyes, 'geometry':geometry(),
            'observation':{'capture_key':capture, 'timestamp':now, 'sequence':1, 'faces':[face], 'eyes':eyes}}


class VideoTests(unittest.TestCase):
    def setUp(self):
        self.cache = VideoCache()
        self.cache.set_session('one')
        self.image = np.full((100,100,3), (50,100,150), np.uint8)

    def add(self, capture='1-10000000', now=10.):
        state = snapshot(now=now, capture=capture)
        self.cache.image({'session_id':'one','capture_key':capture,'timestamp':now}, self.image)
        self.cache.observe('one', state['observation'])
        self.cache.render(now)

    def test_pairing_deduplicates_shared_faces_and_preserves_raw_crop(self):
        self.add()
        self.assertEqual(len(self.cache.crops), 1)
        crop = self.cache.crop('one','1-10000000',0,now=10.1)
        decoded = cv2.imdecode(np.frombuffer(crop,np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, (50,50,3))
        self.assertIsNone(self.cache.crop('one','1-10000000',0,now=11.))
        self.assertIsNone(self.cache.crop('two','1-10000000',0,now=10.1))

    def test_image_before_metadata_does_not_invent_crop(self):
        self.cache.image({'session_id':'one','capture_key':'a','timestamp':10.}, self.image)
        self.cache.render(10.)
        self.assertIsNotNone(self.cache.jpeg)
        self.assertEqual(self.cache.crops,{})
        self.cache.observe('one', snapshot(capture='a')['observation'])
        self.cache.render(10.2)
        self.assertIsNotNone(self.cache.crop('one','a',0,now=10.2))

    def test_reused_sequence_cannot_pair_with_old_timestamp(self):
        self.add('1-10000000',10.)
        self.cache.image({'session_id':'one','capture_key':'1-10200000','timestamp':10.2}, self.image)
        self.cache.render(10.21)
        self.assertIsNone(self.cache.crop('one','1-10200000',0,now=10.21))

    def test_pairing_cache_and_crop_cache_are_bounded_and_session_clears(self):
        for i in range(30):
            self.add(f'{i}-{i}',10.+i*.25)
        self.assertLessEqual(len(self.cache.images),4)
        self.assertLessEqual(len(self.cache.observations),4)
        self.assertLessEqual(len(self.cache.crops),16)
        self.cache.set_session('two')
        self.assertIsNone(self.cache.jpeg)
        self.assertEqual(self.cache.latest_crops,{})

    def test_unassigned_or_unmatched_boxes_never_produce_crops(self):
        state = snapshot()
        state['observation']['eyes'] = []
        self.cache.observe('one',state['observation'])
        self.cache.image({'session_id':'one','capture_key':'1-10000000','timestamp':10.},self.image)
        self.cache.render(10.)
        self.assertEqual(self.cache.crops,{})


class StateTests(unittest.TestCase):
    def test_camera_and_controller_silence_go_stale_without_new_frames(self):
        state = MonitorState(); state.accept(snapshot())
        state.video.image({'session_id':'one','capture_key':'1-10000000','timestamp':10.}, np.zeros((10,10,3),np.uint8))
        state.video.render(10.)
        self.assertEqual(state.describe(now=10.1)['camera']['status'],'streaming')
        self.assertEqual(state.describe(now=12.)['camera']['status'],'stale')
        self.assertEqual(state.describe(now=12.)['crops'],{})
        self.assertEqual(state.describe(now=12.)['controller']['status'],'stale')

    def test_restart_cannot_be_overwritten_by_retired_session_or_old_timestamp(self):
        state=MonitorState(); state.accept(snapshot())
        state.accept(snapshot(now=11.,session='two'))
        state.accept(snapshot(now=12.,session='one'))
        state.accept(snapshot(now=10.,session='two'))
        self.assertEqual(state.source['session_id'],'two')
        self.assertEqual(state.source['timestamp'],11.)

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
        subprocess.run([sys.executable,'-c',code],check=True,cwd=Path(__file__).parent)

    def test_demo_api_and_websocket_produce_fresh_images_without_hardware(self):
        app=create_app(demo=True)
        with TestClient(app) as client:
            with client.websocket_connect('/api/ws') as ws:
                data=ws.receive_json()
                deadline=time.monotonic()+2
                while data['controller']['status'] != 'running' and time.monotonic()<deadline:
                    data=ws.receive_json()
                self.assertTrue(data['demo'])
                self.assertEqual(data['controller']['status'],'running')
            deadline=time.monotonic()+1
            while not app.state.monitor.video.crop_metadata(time.monotonic()) and time.monotonic()<deadline:
                time.sleep(.02)
            data=client.get('/api/state').json()
            self.assertEqual(len(data['eyes']),6)
            self.assertEqual(len(data['crops']),3)
            response=client.get(next(iter(data['crops'].values())))
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['content-type'],'image/jpeg')
            self.assertEqual(client.get('/api/health').json()['status'],'ok')

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
