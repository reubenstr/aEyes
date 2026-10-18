from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import yaml

from parameter_schema import parse_params
from monitoring.config_store import ConfigStore, ConflictError, ROOT
from monitoring.contracts import revision
from monitoring.server import create_app
from monitoring.service_control import ServiceControl
from monitoring.state import MonitorState


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'params.yaml'
        self.path.write_bytes((ROOT / 'params.defaults.yaml').read_bytes())
        self.store = ConfigStore(self.path)
        self.values = self.store.read()

    def client(self, **kwargs):
        return TestClient(create_app(store=self.store, start_workers=False, **kwargs))

    def test_strict_types_unknown_fields_and_nonfinite_values(self):
        for section, key, value in [('system', 'refresh_rate_hz', True),
                                     ('tracker', 'max_missing_confirmed', 2.5),
                                     ('kalman', 'acceleration_noise', float('inf')),
                                     ('eye_manager', 'is_cat_eye', 'false'),
                                     ('eye_manager', 'pupil_color', [256, 0, 0]),
                                     ('eye_manager', 'vein_seed', 'auto')]:
            raw = deepcopy(self.values)
            raw[section][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_params(raw)
        raw = deepcopy(self.values)
        raw['system']['surprise'] = 1
        with self.assertRaises(ValueError):
            parse_params(raw)

    def test_cross_fields_and_reserved_ports(self):
        raw = deepcopy(self.values)
        raw['eye_manager']['eyelid_far_distance_m'] = 0.1
        with self.assertRaises(ValueError):
            parse_params(raw)
        raw = deepcopy(self.values)
        raw['publisher']['socket_port'] = 9101
        with self.assertRaises(ValueError):
            self.store.save(raw, revision(self.values))

    def test_atomic_save_revision_backup_and_reset_baseline(self):
        original = self.path.read_bytes()
        raw = deepcopy(self.values)
        raw['eye_manager']['pupil_size'] = .7
        new_revision = self.store.save(raw, revision(self.values))
        self.assertEqual(self.path.with_suffix('.yaml.bak').read_bytes(), original)
        self.assertEqual(self.store.read()['eye_manager']['pupil_size'], .7)
        self.assertNotEqual(new_revision, revision(self.values))
        with self.assertRaises(ConflictError):
            self.store.save(self.values, revision(self.values))
        defaults = self.store.describe()['defaults']
        self.store.save(defaults, new_revision)
        self.assertEqual(self.store.read(), self.values)

    def test_failed_replace_leaves_original_intact(self):
        original = self.path.read_bytes()
        real_replace = __import__('os').replace
        def replace(source, target):
            if Path(target) == self.path:
                raise OSError('disk error')
            return real_replace(source, target)
        with patch('monitoring.config_store.os.replace', side_effect=replace):
            with self.assertRaises(OSError):
                self.store.save(self.values, revision(self.values))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob('.aeyes-*')), [])

    def test_api_settings_active_saved_conflicts_and_validation(self):
        state = MonitorState()
        state.source = {'active_config': self.values, 'timestamp': time.monotonic()}
        with self.client(state=state, service=ServiceControl(False)) as client:
            config = client.get('/api/config').json()
            self.assertFalse(config['pending_restart'])
            self.assertEqual(config['fields']['eye_manager']['vein_seed']['nullable'], True)
            raw = deepcopy(config['saved'])
            raw['tracker']['min_hits_to_confirm'] = 4
            response = client.put('/api/config', json={'values': raw, 'revision': config['revision']})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()['pending_restart'])
            self.assertEqual(response.json()['active']['tracker']['min_hits_to_confirm'], 30)
            self.assertEqual(client.put('/api/config', json={'values': raw, 'revision': config['revision']}).status_code, 409)
            raw['system']['refresh_rate_hz'] = False
            self.assertEqual(client.put('/api/config', json={'values': raw, 'revision': response.json()['revision']}).status_code, 422)

    def test_cross_origin_writes_are_rejected(self):
        payload = {'values': self.values, 'revision': revision(self.values)}
        with self.client() as client:
            self.assertEqual(client.put('/api/config', json=payload, headers={'Origin':'http://elsewhere.test'}).status_code, 403)
            self.assertEqual(client.put('/api/config', json=payload, headers={'Origin':'http://testserver'}).status_code, 200)

    def test_demo_source_can_save_settings_but_cannot_restart_main_service(self):
        state = MonitorState()
        state.source = {'source':'demo', 'active_config':self.values, 'timestamp':time.monotonic(),
                        'camera_available':False}
        service = ServiceControl(True)
        service.restart = AsyncMock()
        with self.client(state=state, service=service) as client:
            config = client.get('/api/config').json()
            self.assertEqual(config['source'], 'demo')
            self.assertFalse(config['restart_available'])
            raw = deepcopy(self.values)
            raw['system']['refresh_rate_hz'] = 10
            response = client.put('/api/config', json={'values':raw, 'revision':config['revision']})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['pending_restart'])
            restart = client.post('/api/controller/restart', json={'revision':response.json()['revision']})
            self.assertEqual(restart.status_code, 409)
            self.assertIn('demo.py', restart.json()['detail'])
        service.restart.assert_not_awaited()

    def test_active_configuration_is_unavailable_after_application_feed_stops(self):
        state = MonitorState()
        state.source = {'source':'main', 'active_config':self.values, 'timestamp':time.monotonic()-2}
        with self.client(state=state) as client:
            config = client.get('/api/config').json()
            self.assertIsNone(config['active'])
            self.assertIsNone(config['active_revision'])
            self.assertEqual(revision(config['saved']), revision(self.values))

    def test_restart_requires_installed_integration_and_current_revision(self):
        with self.client(service=ServiceControl(False)) as client:
            self.assertEqual(client.post('/api/controller/restart', json={'revision': revision(self.values)}).status_code, 503)
        service = ServiceControl(True)
        async def fake_restart():
            service.restarting = False
        service.restart = AsyncMock(side_effect=fake_restart)
        with self.client(service=service) as client:
            self.assertEqual(client.post('/api/controller/restart', json={'revision':'old'}).status_code, 409)
            self.assertEqual(client.post('/api/controller/restart', json={'revision':revision(self.values)}).status_code, 202)
        service.restart.assert_awaited_once()


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_fixed_unit_is_restarted_and_failure_is_reported(self):
        process = AsyncMock()
        process.returncode = 1
        process.communicate.return_value = (b'', b'restart denied')
        service = ServiceControl(True)
        service.restarting = True
        with patch('monitoring.service_control.asyncio.create_subprocess_exec', return_value=process) as spawn:
            with patch.object(service, 'inspect', new=AsyncMock()):
                await service.restart()
        self.assertEqual(spawn.call_args.args, ('/usr/bin/sudo', '-n', '/usr/bin/systemctl', 'restart', 'main.service'))
        self.assertIn('restart denied', service.error)
        self.assertFalse(service.restarting)
