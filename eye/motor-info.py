#!/usr/bin/env python3
"""Read motor settings and telemetry without enabling, homing, or writing settings.

Run from eye/ on a Pi with its CAN interface already configured:
    sudo systemctl stop main.service
    sudo ip link set can0 up type can bitrate 1000000
    .venv/bin/python motor-info.py
    .venv/bin/python motor-info.py --json > /tmp/motor-info.json

Leave other CAN control programs stopped while collecting the report. This script
does not stop them, disable an already enabled motor, or reconfigure the CAN bus.
Decoding follows the bundled LingKong CAN Protocol V2.35, with the voltage layout
used by the deployed eye driver. Raw replies preserve evidence of firmware differences.
"""

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import math
import socket
import sys
from time import monotonic


READ_COMMANDS = {
    0x30: "PI gains",
    0x33: "Acceleration limit",
    0x92: "Multi-turn position",
    0x9A: "Voltage and faults",
    0x9C: "Current, speed and encoder",
}

NOTES = [
    "Only read requests are sent. No motor enable/disable, motion, calibration, or setting writes.",
    "Stop main.service and other CAN control programs before reading for consistent replies/settings.",
    "Firmware/model, reduction ratio, stored max speed, and max torque-current limit have no read "
    "commands in the bundled CAN V2.35 manual; retrieve them with LK Motor Tool.",
    "Speed and acceleration use protocol units; gearbox-output scaling is unconfirmed.",
    "Position shows both the manual's /100 scale and the eye driver's /1000 scale, "
    "without homing offsets or inversion. Neither establishes the physical reduction ratio.",
    "Voltage uses the deployed driver's bytes 2-3 /100 layout. Iq amperes are an estimate "
    "using the manual's MG scale (33 A /2048 counts); raw values are retained.",
    "The eye startup PID write currently sends 0x34, which V2.35 defines as an acceleration "
    "write (PID RAM write is 0x31). Confirm firmware before interpreting/tuning settings.",
]


def decode_reply(command, data):
    """Decode an eight-byte reply, keeping ambiguous conversions explicitly labelled."""
    if len(data) != 8 or data[0] != command:
        raise ValueError("Expected an eight-byte reply with the requested command byte")
    if command == 0x30:
        names = ("angle_kp", "angle_ki", "speed_kp", "speed_ki", "iq_kp", "iq_ki")
        return dict(zip(names, data[2:8]))
    if command == 0x33:
        return {"acceleration_protocol_deg_s2": int.from_bytes(data[4:8], "little", signed=True)}
    if command == 0x92:
        counts = int.from_bytes(data[1:8], "little", signed=True)
        return {
            "position_raw_counts": counts,
            "position_manual_scale_deg": counts / 100.0,
            "position_eye_driver_scale_deg": counts / 1000.0,
        }
    temperature = int.from_bytes(data[1:2], "little", signed=True)
    if command == 0x9A:
        faults = data[7]
        return {
            "temperature_c": temperature,
            "voltage_eye_driver_layout_v": int.from_bytes(data[2:4], "little") / 100.0,
            "fault_bits_hex": f"0x{faults:02X}",
            "faults_eye_driver_layout": {
                "under_voltage": bool(faults & 0x01),
                "over_voltage": bool(faults & 0x02),
                "over_temperature": bool(faults & 0x08),
                "lost_input": bool(faults & 0x80),
                "other_bits_hex": f"0x{faults & ~0x8B:02X}",
            },
        }
    if command == 0x9C:
        iq = int.from_bytes(data[2:4], "little", signed=True)
        return {
            "temperature_c": temperature,
            "iq_raw_counts": iq,
            "iq_estimate_a": round(iq * 33.0 / 2048.0, 6),
            "speed_protocol_deg_s": int.from_bytes(data[4:6], "little", signed=True),
            "encoder_raw_counts": int.from_bytes(data[6:8], "little"),
        }
    raise ValueError(f"Unsupported read command 0x{command:02X}")


def read_reply(bus, motor_id, command, timeout, attempts):
    """Send only allowlisted read commands and accept matching received data frames."""
    if command not in READ_COMMANDS:
        raise ValueError(f"Command 0x{command:02X} is not an allowed read")
    import can

    arbitration_id = 0x140 + motor_id
    # Discard queued replies so a previous snapshot cannot masquerade as a fresh read.
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if bus.recv(0.0) is None:
            break
    for _ in range(attempts):
        bus.send(can.Message(arbitration_id=arbitration_id, is_extended_id=False,
                             data=[command, 0, 0, 0, 0, 0, 0, 0]), timeout=timeout)
        deadline = monotonic() + timeout
        while (remaining := deadline - monotonic()) > 0:
            reply = bus.recv(remaining)
            if reply is None:
                break
            if (reply.arbitration_id == arbitration_id
                    and reply.is_rx and not reply.is_extended_id
                    and not reply.is_error_frame and not reply.is_remote_frame
                    and reply.dlc == 8 and len(reply.data) == 8
                    and reply.data[0] == command):
                return bytes(reply.data)
    raise TimeoutError(f"No matching reply after {attempts} attempts ({timeout:g} s each)")


def collect_motor_info(bus, config, channel, timeout, attempts):
    import can

    result = {"name": str(config.name), "motor_id": config.id, "channel": channel,
              "can_id_hex": f"0x{0x140 + config.id:03X}", "reads": {}}
    for command, name in READ_COMMANDS.items():
        record = {"name": name}
        result["reads"][f"0x{command:02X}"] = record
        try:
            data = read_reply(bus, config.id, command, timeout, attempts)
            record.update(raw_reply_hex=data.hex(" "), values=decode_reply(command, data))
        except (can.CanError, OSError, TimeoutError) as error:
            record["error"] = str(error)
    return result


def print_report(report):
    print(f"aEyes motor information - {report['host']} - {report['timestamp_utc']}")
    for note in report["notes"]:
        print(f"Note: {note}")
    for motor in report["motors"]:
        print(f"\n{motor['name']} - ID {motor['motor_id']} - {motor['channel']} - {motor['can_id_hex']}")
        if "error" in motor:
            print(f"  UNAVAILABLE: {motor['error']}")
            continue
        for command, reading in motor["reads"].items():
            print(f"  {command} {reading['name']}")
            if "error" in reading:
                print(f"    UNAVAILABLE: {reading['error']}")
                continue
            for key, value in reading["values"].items():
                print(f"    {key}: {json.dumps(value)}")
            print(f"    raw_reply_hex: {reading['raw_reply_hex']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--channel", help="Override the CAN channel from motor_config.py")
    parser.add_argument("--motor", choices=("BASE", "EYE"), help="Read one axis (default: both configured axes)")
    parser.add_argument("--timeout", type=float, default=0.25, help="Reply timeout in seconds (default: 0.25)")
    parser.add_argument("--attempts", type=int, default=2, help="Read attempts per command (default: 2)")
    parser.add_argument("--json", action="store_true", help="Print a JSON report for saving/comparison")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0 or args.attempts < 1:
        parser.error("--timeout must be finite and positive; --attempts must be at least 1")
    try:
        import can
    except ImportError:
        print("python-can is required; run with the eye virtual environment (.venv/bin/python).", file=sys.stderr)
        return 1
    # Import configuration only: Motors.__init__ performs startup setting writes.
    from motors.motor_config import motor_config

    configs = [config for config in motor_config()
               if config.allow_comms and (args.motor is None or config.name == args.motor)]
    if not configs:
        parser.error("No matching motors have allow_comms enabled in motor_config.py")
    report = {"host": socket.gethostname(), "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "notes": NOTES, "motors": []}
    with ExitStack() as stack:
        buses = {}
        errors = {}
        for config in configs:
            channel = args.channel or config.can_channel
            if channel not in buses and channel not in errors:
                try:
                    bus = can.interface.Bus(interface="socketcan", channel=channel,
                                            receive_own_messages=False)
                    buses[channel] = stack.enter_context(bus)
                except (can.CanError, OSError) as error:
                    errors[channel] = f"Cannot open {channel}: {error}. Configure/up the CAN interface first."
            if channel in errors:
                report["motors"].append({"name": str(config.name), "motor_id": config.id,
                                         "channel": channel, "can_id_hex": f"0x{0x140 + config.id:03X}",
                                         "error": errors[channel]})
            else:
                report["motors"].append(collect_motor_info(
                    buses[channel], config, channel, args.timeout, args.attempts))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
    return int(any("error" in motor or any("error" in reading for reading in motor["reads"].values())
                   for motor in report["motors"]))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
