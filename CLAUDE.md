# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**aEyes** is a distributed robotic eye system: a Jetson controller detects and tracks faces via RealSense camera + TensorRT, then broadcasts motor and render commands to up to 6 Raspberry Pi eye units over ZMQ. Each eye unit renders an animated OpenGL eye and drives two CAN-bus motors (yaw/pitch gimbal).

## Running the System

### Controller (Jetson)
```bash
cd ~/aEyes/controller
./main.sh          # activates venv and runs main.py
```

### Eye Unit (Raspberry Pi)
```bash
cd ~/aEyes/eye
sudo ./main.sh     # requires sudo for CAN bus access
```

### Motor Zeroing Tool (Raspberry Pi)
```bash
cd ~/aEyes/eye
sudo python3 zero.py
```

### Controller Test Scripts
```bash
cd ~/aEyes/controller
python3 tests/camera.py        # validate RealSense camera
python3 tests/inference.py     # test face detector
python3 tests/cuda_available.py
```

### Deployment to Pis
```bash
./scripts/sync_all_pis.sh      # rsync repo to all 6 Pis
./scripts/update_all_pis.sh    # git pull on all Pis
```

## Architecture

### Communication Flow
1. Controller captures 640×360 RGB+Depth from RealSense at 60 fps
2. `detector.py` runs TensorRT SCRFD inference at 480×480 (letterboxed), outputs bounding boxes
3. `managers/face_tracker.py` tracks faces via Kalman filter + Hungarian algorithm
4. `managers/eye_assignment.py` maps tracked faces to eye IDs (1–6)
5. `managers/eye_manager.py` maintains per-eye render state and color animations
6. `conversions.py` converts RealSense 3D points → gimbal yaw/pitch angles
7. Controller publishes JSON array of 6 `ControlMessage`s over ZMQ PUB on port 9000 at 15 Hz
8. Each Pi subscribes to its index in the array, renders via `eye_renderer.py`, and drives motors via CAN bus

### ControlMessage (shared interface)
Defined identically in both `eye/interfaces.py` and `controller/interfaces.py`:
```python
@dataclass
class ControlMessage:
    radius: float                            # iris scale 0–1
    rotation_deg: float                      # eye rotation degrees
    eye_lid_position: float                  # 0=open, 1=closed
    iris_color: Tuple[float, float, float]  # RGB 0–255
    cornea_color: Tuple[float, float, float]
    is_cat_eye: bool
    yaw: float                               # BASE motor angle (degrees)
    pitch: float                             # EYE motor angle (degrees)
```

### Network / Hardware
- Controller: Jetson at `192.168.5.1`
- Eyes: Raspberry Pi 4B units at `192.168.5.101`–`192.168.5.106` (EYE_ID from `/eye/.env`)
- Each Pi: Waveshare 4" DSI LCD (1920×480, rotated 90°), Waveshare RS485/CAN Hat (`can0`)
- Motors: 2× MG4010E-i10v3 per eye — CAN ID 1 = BASE (yaw ±45°), CAN ID 2 = EYE (pitch ±45°)

### Key Parameters
| Location | Parameter | Value |
|---|---|---|
| `controller/main.py` | `REFRESH_RATE_HZ` | 15 |
| `controller/detector.py` | `INPUT_W/H` | 480×480 |
| `controller/detector.py` | `CONF_THRESH` | 0.55 |
| `controller/detector.py` | `RS_W/H` | 640×360 |
| `eye/main.py` | `SOCKET_ADDRESS` | 192.168.5.1 |
| `eye/motors/motor_list.py` | Motor range | ±45° per axis |

## Key Files

| File | Role |
|---|---|
| `controller/main.py` | Main loop: orchestrates detection → tracking → assignment → ZMQ broadcast |
| `controller/detector.py` | TensorRT SCRFD face detector (loads `.engine` file) |
| `controller/conversions.py` | Camera-frame → gimbal-angle coordinate transforms (calibration lives here) |
| `controller/managers/face_tracker.py` | Kalman filter + Hungarian matching for multi-face tracking |
| `controller/managers/eye_assignment.py` | Face-to-eye gimbal assignment logic |
| `controller/managers/eye_manager.py` | Per-eye render state: color lerp, radius, eyelid, cat-eye |
| `eye/main.py` | Pi main loop: receives ZMQ, dispatches to renderer and motors |
| `eye/eye_renderer.py` | Pyglet/OpenGL ES 3.1 animated eye renderer |
| `eye/motors/motors.py` | CAN bus motor controller (init sequences, enable/disable, position targets) |
| `eye/zero.py` | Interactive TUI for motor zero calibration |

## Dependencies

**Controller** (system-installed on Jetson): TensorRT, CUDA, RealSense SDK (`pyrealsense2`)
**Controller** (`requirements.txt`): `pyzmq==27.1.0`

**Eye** (`requirements.txt`): `pyglet`, `PyOpenGL`, `pyzmq`, `numpy`, `python-can`, `RPi.GPIO`, `rich`, `prompt_toolkit`

## Systemd Service (Pi)
```bash
sudo systemctl status main.service
sudo journalctl -u main.service -f
```
Service file installed by `eye/install.sh`. Requires `DISPLAY=:0` and `XAUTHORITY` env vars.