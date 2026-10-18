"""Import real eye/motor code with hardware and display dependencies replaced."""
import importlib
import importlib.util
import json
import sys
import types
import unittest
from dataclasses import asdict
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import Mock, patch

from data_types import ControlMessage, EyeState

EYE_DIR = Path(__file__).resolve().parents[2] / 'eye'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class MotorControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package = types.ModuleType('motors')
        package.__path__ = [str(EYE_DIR / 'motors')]
        can = types.ModuleType('can')
        can.Message = object
        can_interface = types.ModuleType('can.interface')
        can_interface.Bus = object
        can.interface = can_interface
        rich = types.ModuleType('rich')
        rich.print = print
        renderer = types.ModuleType('eye_renderer')
        renderer.EyeRenderer = object
        renderer.TextType = SimpleNamespace(INFO='info', ERROR='error')
        with patch.dict(sys.modules, {'motors': package, 'can': can, 'can.interface': can_interface,
                                      'rich': rich, 'eye_renderer': renderer}):
            eye_types = load('data_types', EYE_DIR / 'data_types.py')
            cls.eye_module = load('eye_motor_main_test', EYE_DIR / 'main.py')
            cls.motor_module = importlib.import_module('motors.motor')
            cls.motors_module = importlib.import_module('motors.motors')
        cls.Eye = cls.eye_module.Eye
        cls.MotorName = cls.eye_module.MotorName

    def eye(self):
        eye = self.Eye()
        eye.eye_id = 1
        eye.eye_renderer = SimpleNamespace(set_text=Mock(), apply_control_message=Mock())
        return eye

    def home(self, mode='success', eye_id=1):
        now = [10.]
        eye = self.eye()
        eye.eye_id = eye_id
        def sample(name):
            elapsed = now[0] - 10.
            stop = 1. if name == self.MotorName.BASE else 1.4
            speed = 2. if mode == 'slow' else 20.
            raw = 10. + speed * (elapsed if mode in ('moving', 'slow') else min(elapsed, stop))
            timestamp = 10. if mode == 'stale' else now[0]
            if mode == 'refreshing' and elapsed < 0.05:
                timestamp = 9.
            return raw, raw + 5., timestamp
        motors = SimpleNamespace(get_position_sample=Mock(side_effect=sample),
                                 set_motor_targets=Mock(), set_enforce_position_limits=Mock(),
                                 set_position_offset=Mock(), disable_all_motors=Mock(return_value=True))
        motors.apply_home_offsets = Mock(side_effect=lambda offsets, speed:
                                        [motors.set_position_offset(name, value) for name, value in offsets.items()])
        def sleep(duration):
            now[0] += duration
            if mode == 'cancel' and now[0] > 10.7:
                eye.exit_event.set()
        with patch.object(self.eye_module, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(self.eye_module, 'sleep', side_effect=sleep):
            result = eye.home_motors(motors)
        return result, motors, eye

    def test_successful_homing_calibrates_both_after_they_stop(self):
        result, motors, _ = self.home()
        self.assertTrue(result)
        offsets = {call.args[0]: call.args[1] for call in motors.set_position_offset.call_args_list}
        self.assertAlmostEqual(offsets[self.MotorName.BASE], 67.5 - 30.)
        self.assertAlmostEqual(offsets[self.MotorName.EYE], 45. - 38.)
        motors.disable_all_motors.assert_not_called()

    def test_homing_timeout_disables_and_does_not_calibrate(self):
        result, motors, eye = self.home('moving')
        self.assertFalse(result)
        motors.set_position_offset.assert_not_called()
        motors.disable_all_motors.assert_called_once()
        for name in (self.MotorName.BASE, self.MotorName.EYE):
            self.assertIn((name, True), [call.args for call in motors.set_enforce_position_limits.call_args_list])
        self.assertIn('timed out', eye.eye_renderer.set_text.call_args.args[1])

    def test_cached_position_cannot_prove_a_homing_stop(self):
        result, motors, eye = self.home('stale')
        self.assertFalse(result)
        motors.set_position_offset.assert_not_called()
        motors.disable_all_motors.assert_called_once()
        self.assertIn('stale', eye.eye_renderer.set_text.call_args.args[1])

    def test_startup_waits_for_post_enable_fresh_feedback(self):
        result, motors, _ = self.home('refreshing')
        self.assertTrue(result)
        motors.apply_home_offsets.assert_called_once()

    def test_slow_continuous_motion_is_not_mistaken_for_a_stop(self):
        result, motors, _ = self.home('slow')
        self.assertFalse(result)
        motors.set_position_offset.assert_not_called()

    def test_cancelled_homing_does_not_calibrate(self):
        result, motors, _ = self.home('cancel')
        self.assertFalse(result)
        motors.set_position_offset.assert_not_called()
        motors.disable_all_motors.assert_called_once()

    def test_eye_two_preserves_reverse_base_homing_direction_and_offset(self):
        result, motors, _ = self.home(eye_id=2)
        self.assertTrue(result)
        first = motors.set_motor_targets.call_args_list[0].args
        self.assertEqual(first[2], 15. - 180.)
        offsets = {call.args[0]: call.args[1] for call in motors.set_position_offset.call_args_list}
        self.assertAlmostEqual(offsets[self.MotorName.BASE], -67.5 - 30.)

    def test_enable_failure_prevents_homing(self):
        eye = self.eye()
        motors = Mock()
        motors.enable_all_motors.return_value = False
        eye.home_motors = Mock()
        with patch.object(self.eye_module, 'Motors', return_value=motors):
            self.assertFalse(eye._init_motors())
        eye.home_motors.assert_not_called()
        self.assertTrue(motors.disable_all_motors.called)

    def test_unhomed_eye_does_not_start_subscriber(self):
        eye = self.eye()
        eye._init_local = Mock()
        eye._init_motors = Mock(return_value=False)
        eye._init_socket = Mock()
        eye._start = Mock()
        with patch.object(self.eye_module, 'sleep'):
            eye._deferred_init()
        eye._init_socket.assert_not_called()
        eye._start.assert_not_called()

    def collection(self):
        collection = self.motors_module.Motors.__new__(self.motors_module.Motors)
        collection.allow_enable = True
        collection.motors_enabled = False
        collection.data_lock = Lock()
        collection.target_positions = {}
        collection.target_speeds = {}
        collection.motor_enable_sequence_delay_seconds = 0.
        collection.motor_disable_sequence_delay_seconds = 0.
        collection.can_infos = {'fake': SimpleNamespace(lock=Lock())}
        collection.motors = {name: Mock(allow_motion=True) for name in ('BASE', 'EYE')}
        return collection

    def test_partial_enable_failure_rolls_back_every_motor_and_releases_lock(self):
        collection = self.collection()
        collection.motors['BASE'].cmd_motor_on.return_value = True
        collection.motors['EYE'].cmd_motor_on.return_value = False
        with patch.object(self.motors_module, 'sleep'):
            self.assertFalse(collection.enable_all_motors())
        for motor in collection.motors.values():
            motor.cmd_motor_off.assert_called_once()
        self.assertFalse(collection.motors_enabled)
        lock = collection.can_infos['fake'].lock
        self.assertTrue(lock.acquire(blocking=False))
        lock.release()

    def test_disable_attempts_all_axes_and_releases_lock_even_when_not_flagged_enabled(self):
        collection = self.collection()
        collection.motors['BASE'].cmd_motor_off.return_value = False
        collection.motors['EYE'].cmd_motor_off.return_value = True
        with patch.object(self.motors_module, 'sleep'):
            self.assertFalse(collection.disable_all_motors())
        collection.motors['EYE'].cmd_motor_off.assert_called_once()
        lock = collection.can_infos['fake'].lock
        self.assertTrue(lock.acquire(blocking=False))
        lock.release()

    def test_disable_continues_after_a_transport_exception(self):
        collection = self.collection()
        collection.motors['BASE'].cmd_motor_off.side_effect = RuntimeError('transport lost')
        with patch.object(self.motors_module, 'sleep'), patch('builtins.print'):
            self.assertFalse(collection.disable_all_motors())
        collection.motors['EYE'].cmd_motor_off.assert_called_once()

    def test_enable_transport_exception_also_rolls_back(self):
        collection = self.collection()
        collection.motors['EYE'].cmd_motor_on.side_effect = RuntimeError('transport lost')
        with patch.object(self.motors_module, 'sleep'), patch('builtins.print'):
            self.assertFalse(collection.enable_all_motors())
        for motor in collection.motors.values():
            motor.cmd_motor_off.assert_called_once()

    def test_only_correct_position_reply_refreshes_feedback_time(self):
        motor = self.motor_module.Motor(self.MotorName.BASE, 1, -45., 45., False, True, True, 'fake', Mock())
        motor.op_can_send_message = Mock(return_value=True)
        payload = [0x92] + list((30000).to_bytes(7, 'little', signed=True))
        motor.op_wait_for_reply = Mock(return_value=SimpleNamespace(arbitration_id=0x141, data=payload))
        with patch.object(self.motor_module, 'monotonic', return_value=12.3):
            motor.req_position()
        self.assertEqual(motor.position_sample_time, 12.3)
        self.assertEqual(motor.position_degrees, 30.)
        for reply in (None, SimpleNamespace(arbitration_id=0x142, data=payload),
                      SimpleNamespace(arbitration_id=0x141, data=[0xA4] + payload[1:])):
            motor.op_wait_for_reply.return_value = reply
            with patch.object(self.motor_module, 'monotonic', return_value=15.):
                motor.req_position()
            self.assertEqual(motor.position_sample_time, 12.3)

    def test_home_offsets_update_feedback_and_zero_targets_together(self):
        collection = self.collection()
        for motor in collection.motors.values():
            motor.raw_position_degrees = 10.
        collection.apply_home_offsets({'BASE': 57.5, 'EYE': 35.}, 300)
        self.assertEqual(collection.motors['BASE'].position_degrees, 67.5)
        self.assertEqual(collection.target_positions, {'BASE': 0., 'EYE': 0.})
        self.assertEqual(collection.target_speeds, {'BASE': 300, 'EYE': 300})

    def test_mount_inversion_updates_cached_position_and_hold_target(self):
        collection = self.collection()
        motor = collection.motors['BASE']
        motor.can_channel = 'fake'
        motor.inverse_rotation = True
        motor.raw_position_degrees = 10.
        motor.position_offset = 5.
        collection.target_speeds['BASE'] = 300
        collection.set_inversion_rotation('BASE', False)
        self.assertEqual(motor.raw_position_degrees, -10.)
        self.assertEqual(motor.position_degrees, -5.)
        self.assertEqual(collection.target_positions['BASE'], -5.)

    def test_ramp_scales_with_elapsed_time_and_never_overshoots(self):
        eye = self.eye()
        self.assertAlmostEqual(eye.ramp_target(0., 40., 0.01), 0.225)
        self.assertAlmostEqual(eye.ramp_target(0., 40., 0.1), 2.25)
        self.assertEqual(eye.ramp_target(0., 1., 0.1), 1.)
        self.assertEqual(eye.ramp_target(0., -1., 0.1), -1.)

    def test_motor_progress_between_messages_is_independent_of_message_rate(self):
        positions = []
        for rate in (1., 60.):
            now, next_message = [10.], [10.]
            eye = self.eye()
            eye.motors = Mock()
            eye.exit_event = Event()
            eye._flush_socket = Mock()
            payload = json.dumps({'1': asdict(ControlMessage.from_state(EyeState(eye_id=1, yaw=40., pitch=0.)))})
            def receive(**kwargs):
                if now[0] + 1e-9 >= next_message[0]:
                    next_message[0] += 1. / rate
                    return payload
                raise self.eye_module.zmq.Again()
            eye.socket = SimpleNamespace(recv_string=receive)
            def sleep(duration):
                now[0] += duration
                if now[0] >= 10.2:
                    eye.exit_event.set()
            with patch.object(self.eye_module, 'monotonic', side_effect=lambda: now[0]), \
                 patch.object(self.eye_module, 'sleep', side_effect=sleep):
                eye._worker()
            positions.append(eye.commanded_yaw)
        self.assertAlmostEqual(positions[0], positions[1])
        self.assertGreater(positions[0], 4.)


if __name__ == '__main__':
    unittest.main()
