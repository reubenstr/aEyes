# AGENTS.md

Instructions for coding agents working in the **aEyes** repository. Source code and configuration files are authoritative when documentation disagrees.

## Project Overview

**aEyes** is a distributed robotic eye system:

- A Raspberry Pi 5 controller uses an OAK-D W depth camera with **DepthAI v3 + YuNet** for face detection and tracking.
- The controller assigns tracked faces to six Raspberry Pi 4B eye units and sends commands over **Ethernet/ZMQ**.
- Each eye renders a procedural OpenGL ES eye and controls two gimbal motors over **CAN**.

## Repository Structure

| Path | Purpose |
| --- | --- |
| `controller/main.py` | Controller application and command publishing |
| `controller/camera/` | DepthAI camera and face detection |
| `controller/face_tracker.py` | Tracking and track lifecycle |
| `controller/eye_manager.py`, `controller/eye_assigner.py` | Eye behavior and face-to-eye assignment |
| `controller/config.py`, `controller/params.yaml` | Physical geometry and behavioral settings |
| `controller/monitoring/` | Monitoring API |
| `controller/ui/` | Web dashboard (React/Vite) |
| `controller/tests/` | Controller unit tests |
| `eye/main.py` | Eye subscriber and startup |
| `eye/eye_renderer.py`, `eye/shaders/` | Rendering |
| `eye/motors/` | CAN motor control and configuration |
| `scripts/` | Deployment and maintenance scripts |

Consult `controller/README.md` and `eye/README.md` for setup, operation, and detailed command usage.

## Development Rules

- Follow existing conventions and architecture. Keep changes limited to the requested scope.
- Do **not** add backward-compatibility layers, legacy fallbacks, or migration code unless explicitly requested.
- Do not duplicate hardcoded values already maintained in configuration or source files.
- Update or add tests when changing behavior; run the relevant tests after modifications.
- Treat `controller/data_types.py` and `eye/data_types.py` as a shared **`ControlMessage`** contract. Keep field names, types, and serialization synchronized.
- Preserve the project coordinate system: **X forward, Y left, Z up**, with positions in meters. Positive yaw is counterclockwise viewed from above; positive pitch is upward. `get_pitch_yaw()` returns **(yaw, pitch)** in degrees.
- Keep hardware-dependent functionality separate from hardware-independent tests wherever practical.
- Do not change dependency versions, physical geometry, motor limits, or deployment behavior as incidental cleanup.

## Testing

Run commands from the relevant component directory; scripts may rely on relative paths.

**Controller unit tests** (no camera, CAN motors, GPIO, or display required):

```bash
cd controller
.venv/bin/python -m unittest discover -s tests -v
```

**Web dashboard:**

```bash
cd controller/ui
yarn test
yarn build
```

**Offline controller replay** (when a capture file is available):

```bash
cd controller
.venv/bin/python replay.py /path/to/captures.jsonl
```

The replay command runs without a camera, network publication, or motor access. Some monitoring/API tests require local socket access. Refer to the component READMEs for environment setup.

## Hardware Safety

**Do not run commands that operate physical equipment or modify deployed systems without explicit user authorization.** In particular:

- `main.py --demo` and `sudo ./main.sh --demo` (from `controller/`) use synthetic detections but **publish commands to physical eye units**. Demo mode is not a hardware-safe test.
- Starting an eye with `eye/main.sh`, `eye/main.py`, or its `main.service` **enables and homes both motors automatically**.
- `scripts/push-eye-code.sh` uses `rsync --delete` and normally **restarts eye services**, triggering motor startup/homing. Use `--dry-run` only when inspection is needed; do not perform a live push without authorization.
- Do not run installation, calibration, homing, reset, service-restart, or shutdown commands against real devices without authorization.

Prefer controller unit tests, offline replay, and static inspection for routine validation. `eye/demo.py` exercises rendering without ZMQ or motors, but still requires an appropriate display environment.