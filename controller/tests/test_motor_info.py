"""Verify the diagnostic's read-only CAN traffic and reply handling without hardware."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[2] / "eye" / "motor-info.py"


def frame(arbitration_id=0x141, data=b"\x30\x00\x05\x05\x32\x28\x32\x32", **flags):
    attributes = dict(arbitration_id=arbitration_id, data=bytearray(data), dlc=len(data),
                      is_rx=True, is_extended_id=False, is_error_frame=False, is_remote_frame=False)
    attributes.update(flags)
    return SimpleNamespace(**attributes)


class FakeBus:
    payloads = {
        0x30: bytes([0x30, 0, 5, 5, 50, 40, 50, 50]),
        0x33: bytes([0x33, 0, 0, 0]) + (3600).to_bytes(4, "little", signed=True),
        0x92: bytes([0x92]) + (-1234500).to_bytes(7, "little", signed=True),
        0x9A: bytes([0x9A, 35, 0x60, 0x09, 0, 0, 0, 0x89]),
        0x9C: bytes([0x9C, 35, 0, 0xFC, 0x88, 0xFF, 0x34, 0x12]),
    }

    def __init__(self, missing=(), noise=()):
        self.missing = missing
        self.noise = noise
        self.queue = []
        self.sent = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def send(self, message, timeout):
        self.sent.append(message)
        self.queue.extend(self.noise)
        if message.data[0] not in self.missing:
            if message.data[0] == 0x40:
                parameter_id = message.data[1]
                # Include uint16 PID values that cannot fit the old byte-sized layout.
                data = bytes([0x40, parameter_id, 0x34, 0x12, 0x78, 0x56, 0xBC, 0x9A])
            else:
                data = self.payloads[message.data[0]]
            self.queue.append(frame(message.arbitration_id, data))

    def recv(self, timeout):
        return self.queue.pop(0) if self.queue else None


class MotorInfoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("eye_motor_info_test", SCRIPT)
        cls.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.script)

    def setUp(self):
        self.bus = FakeBus()
        self.can = ModuleType("can")
        self.can.Message = frame
        self.can.CanError = type("FakeCanError", (Exception,), {})
        self.can.interface = SimpleNamespace(Bus=Mock(return_value=self.bus))
        config_module = ModuleType("motors.motor_config")
        self.configs = [SimpleNamespace(name=name, id=number, can_channel="can0", allow_comms=True)
                        for number, name in enumerate(("BASE", "EYE"), 1)]
        config_module.motor_config = lambda: self.configs
        modules = patch.dict(sys.modules, {"can": self.can, "motors.motor_config": config_module})
        modules.start()
        self.addCleanup(modules.stop)

    def run_report(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            status = self.script.main(list(args))
        return status, output.getvalue()

    def test_report_queries_both_axes_using_only_read_requests_and_closes_bus(self):
        status, output = self.run_report("--json")
        report = json.loads(output)
        self.assertEqual(status, 0)
        self.assertEqual([motor["name"] for motor in report["motors"]], ["BASE", "EYE"])
        self.assertEqual(len(self.bus.sent), 10)
        for message in self.bus.sent:
            self.assertIn(message.arbitration_id, (0x141, 0x142))
            self.assertIn(message.data[0], (0x30, 0x33, 0x92, 0x9A, 0x9C))
            self.assertEqual(message.data[1:], bytes(7))
            self.assertFalse(message.is_extended_id)
        self.can.interface.Bus.assert_called_once_with(
            interface="socketcan", channel="can0", receive_own_messages=False)
        self.assertTrue(self.bus.closed)
        gains = report["motors"][0]["reads"]["0x30"]
        self.assertEqual(gains["values"]["angle_kp"], 5)
        self.assertEqual(gains["raw_reply_hex"], "30 00 05 05 32 28 32 32")

    def test_signed_position_current_speed_and_fault_decoding(self):
        position = self.script.decode_reply(0x92, self.bus.payloads[0x92])
        self.assertEqual(position["position_raw_counts"], -1234500)
        self.assertEqual(position["position_manual_scale_deg"], -12345)
        self.assertEqual(position["position_eye_driver_scale_deg"], -1234.5)
        state = self.script.decode_reply(0x9C, self.bus.payloads[0x9C])
        self.assertEqual(state["iq_raw_counts"], -1024)
        self.assertEqual(state["iq_estimate_a"], -16.5)
        self.assertEqual(state["speed_protocol_deg_s"], -120)
        self.assertEqual(state["encoder_raw_counts"], 0x1234)
        status = self.script.decode_reply(0x9A, self.bus.payloads[0x9A])
        self.assertEqual(status["voltage_eye_driver_layout_v"], 24)
        self.assertTrue(status["faults_eye_driver_layout"]["lost_input"])
        self.assertFalse(status["faults_eye_driver_layout"]["over_voltage"])

    def test_acceleration_does_not_truncate_large_or_signed_values(self):
        for value in (3600, 842147890, -400):
            data = bytes([0x33, 0, 0, 0]) + value.to_bytes(4, "little", signed=True)
            self.assertEqual(self.script.decode_reply(0x33, data)["acceleration_protocol_deg_s2"], value)

    def test_wrong_stale_truncated_and_transmit_frames_are_not_used_as_replies(self):
        self.bus.queue.append(frame(data=bytes([0x30]) + bytes(7)))
        self.bus.noise = [frame(arbitration_id=0x142), frame(data=bytes([0x33]) + bytes(7)),
                          frame(is_extended_id=True), frame(is_error_frame=True),
                          frame(is_remote_frame=True), frame(is_rx=False),
                          frame(dlc=7), frame(data=bytes([0x30]))]
        data = self.script.read_reply(self.bus, 1, 0x30, 0.25, 2)
        self.assertEqual(data, self.bus.payloads[0x30])
        self.assertEqual(len(self.bus.sent), 1)

    def test_missing_setting_is_reported_without_fabricated_values_and_other_reads_continue(self):
        self.bus.missing = (0x33,)
        status, output = self.run_report("--json", "--motor", "EYE")
        self.assertEqual(status, 1)
        motor = json.loads(output)["motors"][0]
        self.assertEqual(motor["motor_id"], 2)
        self.assertIn("error", motor["reads"]["0x33"])
        self.assertNotIn("values", motor["reads"]["0x33"])
        self.assertIn("values", motor["reads"]["0x9C"])
        self.assertEqual(len(self.bus.sent), 6)
        self.assertTrue(self.bus.closed)

    def test_write_or_motion_commands_are_rejected_before_sending(self):
        for command in (0x31, 0x34, 0x40, 0x42, 0x44, 0x80, 0x88, 0xA1, 0xA4, 0x19):
            with self.assertRaises(ValueError):
                self.script.read_reply(self.bus, 1, command, 0.25, 2)
        self.assertEqual(self.bus.sent, [])

    def test_parameter_probe_reads_limits_even_when_legacy_settings_do_not_reply(self):
        self.bus.missing = (0x30, 0x33)
        status, output = self.run_report("--parameter-reads", "--motor", "BASE", "--json")
        readings = json.loads(output)["motors"][0]["reads"]
        self.assertEqual(status, 1)  # Legacy reads remain explicitly unavailable.
        self.assertIn("error", readings["0x30"])
        self.assertEqual(readings["0x40/0x96"]["values"],
                         {"kp_raw": 0x1234, "ki_raw": 0x5678, "kd_raw": 0x9ABC})
        self.assertEqual(readings["0x40/0x99"]["values"]["max_torque_current_raw"], 0x1234)
        self.assertEqual(readings["0x40/0x9A"]["values"]["max_speed_raw"], 0x56781234)
        self.assertEqual(readings["0x40/0x9E"]["values"]["speed_ramp_raw"], 0x56781234)
        probes = [message for message in self.bus.sent if message.data[0] == 0x40]
        self.assertEqual([message.data[1] for message in probes], [0x96, 0x97, 0x98, 0x99, 0x9A, 0x9E])
        self.assertTrue(all(message.data[2:] == bytes(6) for message in probes))

    def test_parameter_reply_must_echo_the_requested_parameter(self):
        self.bus.noise = [frame(data=bytes([0x40, 0x97]) + bytes(6))]
        data = self.script.read_reply(self.bus, 1, 0x40, 0.25, 2, parameter_id=0x96)
        self.assertEqual(data[1], 0x96)
        self.assertEqual(self.bus.sent[0].data, bytes([0x40, 0x96]) + bytes(6))
        for command, parameter_id in ((0x40, 0), (0x40, 0xFF), (0x30, 0x96), (0x42, 0x96)):
            with self.assertRaises(ValueError):
                self.script.read_reply(self.bus, 1, command, 0.25, 2, parameter_id=parameter_id)

    def test_bus_failure_produces_a_report_for_both_motors(self):
        self.can.interface.Bus.side_effect = self.can.CanError("interface unavailable")
        status, output = self.run_report("--json")
        report = json.loads(output)
        self.assertEqual(status, 1)
        self.assertEqual(len(report["motors"]), 2)
        self.assertTrue(all("error" in motor for motor in report["motors"]))
        self.can.interface.Bus.assert_called_once()

    def test_text_report_identifies_unavailable_data_and_channel_override(self):
        self.bus.missing = (0x30,)
        status, output = self.run_report("--motor", "BASE", "--channel", "can1", "--attempts", "1")
        self.assertEqual(status, 1)
        self.assertIn("BASE - ID 1 - can1 - 0x141", output)
        self.assertIn("UNAVAILABLE: No matching reply", output)
        self.assertIn("acceleration_protocol_deg_s2: 3600", output)


if __name__ == "__main__":
    unittest.main()
