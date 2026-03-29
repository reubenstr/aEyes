# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**aEyes** is a distributed robotic eye system. A Jetson controller detects and tracks faces, then broadcasts motor and render commands to up to 6 Raspberry Pi eye units over ZMQ. Each Pi renders a procedurally animated OpenGL eye and drives two CAN-bus gimbal motors.

> **Migration in progress:** `controller/detector.py` (TensorRT SCRFD via RealSense) is being replaced with an **OAK-D camera** pipeline. When working on the controller, treat detector.py as legacy. The rest of the pipeline (tracking, assignment, rendering, motors) remains intact.

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

### Motor Zeroing (Raspberry Pi — required before first run)
```bash
cd ~/aEyes/eye
sudo python3 zero.py   # interactive TUI: homes EYE motor against endstop, creates .motors-zeroed flag
```

### Deployment to Pis
```bash
./scripts/push-eye-code.sh     # rsync repo to all 6 Pis
./scripts/pull-eye-code.sh     # git pull on all Pis
./scripts/ping-all-pis.sh      # check network connectivity
```

## Architecture

### Communication Flow
1. Controller captures RGB + Depth frames from camera
2. `detector.py` (legacy/being replaced) detects faces → bounding boxes
3. `face_tracker.py` tracks faces via 3D Kalman filter + Hungarian algorithm → `dict[face_id, Position3D]`
4. `eye_assigner.py` maps tracked faces to eye IDs (1–6)
5. `eye_manager.py` maintains per-eye render state (colors, blink, radius) and computes gimbal angles
6. `conversions.py` converts camera-frame 3D positions → gimbal yaw/pitch angles
7. `publisher.py` broadcasts a JSON dict of 6 `ControlMessage`s over ZMQ PUB on port 9000 at 15 Hz
8. Each Pi subscribes, extracts its message by `EYE_ID`, renders via `eye_renderer.py`, and issues CAN motor commands

### ControlMessage (shared interface)
Defined identically in `eye/data_types.py` and `controller/data_types.py`:
```python
@dataclass
class ControlMessage:
    radius: float                             # iris scale 0–1
    rotation_deg: float                       # eye rotation in degrees
    eye_lid_position: float                   # 0=closed, 1=open
    iris_color: tuple[float, float, float]   # RGB 0–255
    cornea_color: tuple[float, float, float] # RGB 0–255 (striation tint)
    is_cat_eye: bool
    yaw: float                                # BASE motor angle (degrees)
    pitch: float                              # EYE motor angle (degrees)
```

### Coordinate System
- **+X** = Forward, **+Y** = Left, **+Z** = Up
- **+Yaw** = CCW when viewed from above; **+Pitch** = upward
- Transform chain: camera frame → base frame → gimbal yaw frame → pitch frame
- Pitch pivot is offset 80mm forward of the yaw axis (`PITCH_PIVOT_OFFSET`)

### Eye Physical Layout (config.py)
Six eyes in a hexagonal arrangement, positions relative to system origin (meters):
```
Eye 1: y=-0.405, z=0.000   (far left)
Eye 2: y=-0.205, z=+0.346  (upper left)
Eye 3: y=+0.205, z=+0.346  (upper right)
Eye 4: y=+0.405, z=0.000   (far right)
Eye 5: y=+0.205, z=-0.346  (lower right)
Eye 6: y=-0.205, z=-0.346  (lower left)
```
All at `x=0.0275m`; camera mounted at `y=0.030m` above origin.

### Network / Hardware
- Controller: Jetson at `192.168.5.1`
- Eyes: Raspberry Pi 4B at `192.168.5.101`–`192.168.5.106` (EYE_ID from `eye/.env`)
- Each Pi: Waveshare 4" DSI LCD (1920×480, rotated 90°), Waveshare RS485/CAN Hat (`can0` at 1 Mbps)
- Motors: 2× MG4010E-i10v3 per eye (dual-encoder CAN servo, 1:10 gearbox, 24V/3.5A)
  - CAN ID 1 = BASE (yaw, ±45°)
  - CAN ID 2 = EYE (pitch, ±45°, `inverse_rotation=True`, homed to 52° endstop)

## Key Files

| File | Role |
|---|---|
| `controller/main.py` | Main loop: camera → detection → tracking → assignment → ZMQ publish |
| `controller/detector.py` | **Legacy** TensorRT SCRFD detector — being replaced by OAK-D |
| `controller/config.py` | Physical layout: eye positions, camera mount, pitch pivot offset |
| `controller/data_types.py` | Shared data structures: `ControlMessage`, `Position3D`, `Detection`, `EyeConfig` |
| `controller/face_tracker.py` | Multi-face Kalman tracker + Hungarian matching + re-ID |
| `controller/kalman_filter_3d.py` | Constant-velocity 3D Kalman filter (state: x,y,z,vx,vy,vz) |
| `controller/eye_assigner.py` | Proximity-based face-to-eye assignment with rate limiting |
| `controller/eye_manager.py` | Per-eye render state: color lerp, blink, radius, gimbal angles |
| `controller/conversions.py` | Camera-frame 3D → gimbal yaw/pitch (calibration/geometry lives here) |
| `controller/publisher.py` | ZMQ PUB socket, serializes 6 ControlMessages as JSON on port 9000 |
| `controller/colors.py` | Color pool for assigning distinct colors to tracked faces |
| `controller/utilities.py` | `lerp()`, color helpers |
| `controller/demo.py` | Synthetic detection demo (no camera needed) |
| `eye/main.py` | Pi main loop: ZMQ recv → renderer dispatch → motor ramp → CAN commands |
| `eye/data_types.py` | `ControlMessage` dataclass (matches controller) |
| `eye/eye_renderer.py` | Pyglet/OpenGL ES 3.1 animated eye renderer (60 fps) |
| `eye/shaders/eye.frag` | Fragment shader: procedural iris (FBM), striation, eyelid, cat-eye, vignette |
| `eye/motors/motor_list.py` | Motor configuration (IDs, limits, inversion, homing) |
| `eye/motors/motors.py` | CAN worker thread (100 Hz), enable/disable sequences, position polling |
| `eye/motors/motor.py` | Low-level CAN commands for MG4010E (0x88/0x80/0xA4 etc.) |
| `eye/zero.py` | Interactive motor zero calibration TUI (prompt_toolkit) |
| `eye/demo.py` | Standalone renderer demo (no ZMQ or motors) |

## Tunable Parameters

### Detection / Camera (detector.py — legacy, replace with OAK-D)
| Parameter | Value | Effect |
|---|---|---|
| `CONF_THRESH` | 0.55 | Lower = more detections, more false positives |
| `NMS_IOU_THRESH` | 0.4 | Overlap threshold for merging detections |
| `RS_W/H` | 640×360 | Capture resolution (affects depth quality) |
| `RS_FPS` | 60 | Camera frame rate |
| `Z_MIN_M / Z_MAX_M` | 0.2m / 10.0m | Depth acceptance range |

### Tracking (face_tracker.py + kalman_filter_3d.py)
| Parameter | Value | Effect |
|---|---|---|
| `base_max_distance` | 0.4m | Match gate radius at 1m depth — increase for faster/farther subjects |
| `depth_scale_factor` | 0.15 | Gate grows by this per meter of depth |
| `embedding_weight` | 0.3 | 0=position-only matching, 1=appearance-only |
| `min_hits_to_confirm` | 3 | Frames before a tentative track becomes confirmed |
| `max_missing_confirmed` | 15 | Frames a confirmed track survives without detection |
| `max_missing_tentative` | 2 | Frames a tentative track survives without detection |
| `reid_window_frames` | 30 | Frames a lost track is retained for re-identification |
| `reid_max_distance` | 0.8m | Spatial radius for re-ID matching |
| `ema_alpha` | 0.4 | Output smoothing — lower = smoother but laggier (range 0–1) |
| `q` (Kalman process noise) | 0.1 | Higher = tracks react faster, noisier |
| `r_xy` (Kalman meas. noise) | 0.05m | X/Y position measurement trust |
| `r_z` (Kalman meas. noise) | 0.20m | Depth measurement trust (depth is noisier) |

### Assignment (eye_assigner.py)
| Parameter | Value | Effect |
|---|---|---|
| `assign_interval_s` | 1.0 | Rate limit for assigning extra eyes to faces — lower = more responsive crowd behavior |

### Rendering / Animation (eye_manager.py)
| Parameter | Value | Effect |
|---|---|---|
| `COLOR_IN_RATE` | 2.0 units/sec | Speed of iris color lerp toward face color |
| `COLOR_OUT_RATE` | 4.0 units/sec | Speed of iris color lerp back to neutral |
| `BLINK_RATE` | 1.0 blinks/sec | Blink animation speed on new face assignment |

### Gimbal Ramping (eye/main.py)
| Parameter | Value | Effect |
|---|---|---|
| `CLOSE_DEG` | 5.0° | Below this → full speed (`FAST_DEG_S`) |
| `FAR_DEG` | 30.0° | Above this → min speed (`SLOW_DEG_S`) |
| `FAST_DEG_S` | 900.0 °/s | Max slew rate (close to target) |
| `SLOW_DEG_S` | 22.5 °/s | Min slew rate (far from target) — controls smoothness of large moves |

### Motor (eye/motors/)
| Parameter | Value | Effect |
|---|---|---|
| Motor range (motor_list.py) | ±45.0° | Gimbal range per axis |
| EYE `home_position` (motor_list.py) | 52.0° | Physical endstop position used during homing |
| `min_loop_rate_seconds` (motors.py) | 0.010s | CAN worker loop period (100 Hz) |
| `motor_enable_sequence_delay` (motors.py) | 0.250s | Delay between enable steps |
| PID params (motor.py) | angle_kp/ki, speed_kp/ki, iq_kp/ki | Motor torque/speed tuning |

### System Timing (controller/main.py, eye/main.py)
| Parameter | Value | Effect |
|---|---|---|
| `REFRESH_RATE_HZ` (controller) | 15 | Main publish rate — higher uses more CPU, lower = laggier tracking |
| `SOCKET_PORT` | 9000 | ZMQ pub port (must match on all Pis) |
| `MESSAGE_TIMEOUT_SECONDS` (eye) | 3.0 | Time before eye shows error state |
| `CONTROLLER_FPS` (eye) | 15 | Expected message rate (used for timing estimates) |

## Dependencies

**Controller** (system-installed on Jetson): TensorRT, CUDA, RealSense SDK (`pyrealsense2`)
**Controller** (`requirements.txt`): `pyzmq`, `numpy`, `scipy`, `matplotlib`

**Eye** (`requirements.txt`): `pyglet`, `PyOpenGL`, `pyzmq`, `numpy`, `python-can`, `RPi.GPIO`, `rich`, `prompt_toolkit`

## Systemd Service (Pi)
```bash
sudo systemctl status main.service
sudo journalctl -u main.service -f
```
Installed by `eye/install.sh`. Requires `DISPLAY=:0` and `XAUTHORITY` env vars.
