# AGENTS.md

This file guides coding agents working in this repository. Treat the Python source and configuration files as the source of truth when documentation disagrees.

## Project Overview

**aEyes** is a distributed robotic eye system. A **Raspberry Pi 5 controller with an OAK-D W depth camera** detects and tracks faces, then broadcasts commands to six Raspberry Pi 4B eye units over Ethernet/ZMQ. Each eye renders a procedural OpenGL ES eye and drives two CAN gimbal motors.

The active camera implementation is **DepthAI v3 + YuNet**, not the old Jetson/TensorRT/RealSense pipeline.

## Running and Testing

Run commands from the indicated component directory; the shell launchers use relative paths.

### Controller

```bash
cd ~/aEyes/controller
sudo ./main.sh
```

The launcher requires root and activates `.venv`. Direct Python camera use does not have that launcher check; OAK USB access requires the udev rule described in `controller/README.md`.

For local development, use the existing controller virtual environment or create one as documented in `controller/README.md`.

```bash
cd controller
.venv/bin/python -m unittest discover -v
.venv/bin/python plot.py
.venv/bin/python visual.py
```

- The unittest suite runs without a camera, GPIO, CAN motors, or a display; the renderer tests mock OpenGL/Pyglet.
- `plot.py` is the Matplotlib simulation; `visual.py` is the PySide6/pyqtgraph simulation. Both use synthetic detections and do not publish commands.
- `demo.py` uses a Qt visualizer and **publishes commands to physical eyes**.
- To exercise the camera alone, run `.venv/bin/python -m camera.detector` from `controller/`; add `--visualizer` for the DepthAI remote visualizer (HTTP port 8082).
- Tests cover capture timing/metadata, tracking and covariance gates, crossings/dropouts, rendering compatibility, motor ramp timing, and mocked homing/enable failures. Physical camera, CAN, and endstop behavior still require hardware validation.

### Eye Unit

```bash
cd ~/aEyes/eye
sudo ./main.sh
```

The launcher activates `.venv` and sources `.env` for `EYE_ID` (1–6). A display session is required. For an interactive SSH launch, see the `DISPLAY`/`XAUTHORITY` example in `eye/README.md`.

`eye/demo.py` exercises the renderer without ZMQ or motors. `eye/zero.sh` runs the interactive CAN zero-calibration TUI.

**Startup currently enables and homes both motors automatically.** Although `zero.py` writes `.motors-zeroed`, `eye/main.py` does not check that file. The eye README's claim that the file gates startup is outdated.

## Active Pipeline

1. `controller/camera/detector.py` creates the OAK-D pipeline: RGB camera → YuNet `ParsingNeuralNetwork`; stereo depth → `ImageAlign` aligned to the exact NN input → `SpatialLocationCalculator`.
2. Spatial calculation uses median depth, a 0.5 bounding-box scale, and a 200–5000 mm acceptance range. The default model is `camera/models/YuNet-640x360.rvc2.tar.xz` (640×360 input, six NN SHAVEs). Its archive config sets confidence 0.6 and IoU 0.3.
3. The detector's nonblocking output queue retains the latest message (`maxSize=1`). `poll_frame()` returns `None` for **no new frame**, or a `DetectedFrame` containing capture time, sequence number, and faces with confidence, normalized bounding boxes, and optional XYZ. Capture age is translated from `dai.Clock` into Python monotonic time. The compatibility `poll_faces()` wrapper returns only the face list.
4. `controller/main.py` preserves boxes and confidence even when depth is unavailable, remaps XYZ axes, and updates the tracker once per new camera frame. `Detection.depth_quality` represents relative depth trust; the current camera adapter supplies binary valid/invalid depth, not a measured valid-pixel fraction. Appearance embeddings remain optional and are not produced by the live detector.
5. `face_tracker.py` predicts 3D constant-velocity Kalman tracks, associates detections using Hungarian assignment, manages tentative/confirmed/reacquiring/lost states, and attempts spatial re-identification.
6. Tracker output is `dict[FaceId, TrackedFace]`; each `TrackedFace` contains `position` and `is_static`.
7. `EyeManager` owns an `EyeAssigner`. Non-static faces receive eyes by Y-Z layout proximity; uncovered faces bypass assignment throttling and may take an extra eye from another face. Remaining eyes are assigned gradually.
8. `EyeManager` computes palettes, blinks, distance-dependent eyelid opening, and per-eye yaw/pitch through `Conversions`.
9. `Publisher` serializes one dictionary of all eye commands as JSON on ZMQ PUB port 9000. JSON eye-ID keys are strings.
10. Each `eye/main.py` subscribes, selects its `EYE_ID`, applies appearance controls, ramps angle commands, and updates CAN motor targets. Rendering is scheduled at 60 Hz; CAN workers target a 10 ms loop.

### Tracking Semantics

- Kalman state is position in meters and velocity in **meters/second**. Each capture advances active and lost filters once using actual elapsed capture time. Publication projects output without advancing the measurement-time filters, so delayed captures cannot be invalidated by an earlier publish tick.
- `update(None, timestamp=...)` and `get_output(timestamp=...)` project public output without consuming a detection frame or changing counters. `update([], timestamp=...)` means an observed frame with no faces. Duplicate/out-of-order capture timestamps are ignored.
- Confirmation thresholds count actual matched XYZ observations. Missing/lost retention settings retain their nominal-frame names for compatibility but are converted to **seconds** using the configured refresh rate. Omitted timestamps advance one nominal period for deterministic synthetic callers.
- Confirmed tracks coast briefly and resume normal updates on the first valid match after a short miss. Only a truly lost track enters `REACQUIRING`; it needs three matched XYZ observations by default before becoming public again. Tentative false positives are discarded without re-ID retention.
- Public extrapolation is capped by `coast_time_s` (0.25 s); output disappears when the elapsed missing grace expires, including a silent camera outage. Filtering and lost-track prediction continue on the capture timeline.
- A confirmed track can use overlapping image boxes through a brief depth failure (`depth_grace_s=0.5`, `min_bbox_iou=0.2`). Such matches retain identity without inventing XYZ measurements or confirming tentative/reacquiring tracks. Continuing image-only detections cannot keep stale depth alive indefinitely.
- Association gates each pair **before** Hungarian assignment, using a per-track depth-dependent Euclidean limit and a squared Mahalanobis innovation limit. Dummy unmatched options maximize valid match count before minimizing normalized uncertainty/appearance cost. Spatial and appearance costs have independent spatial gates; embeddings cannot bypass them.
- Re-ID also uses joint assignment and predicts lost tracks forward. The live pipeline currently uses spatial/image-box evidence; it has no face-recognition model.
- Output EMA uses elapsed time. Static classification compares velocity directly in m/s over a time window derived from `static_window`; observed misses, image-only observations, and lost reacquisition clear its history.
- Controller publication uses a deadline schedule that subtracts processing time from the sleep interval. Eye command ramping runs between received messages using measured monotonic time, with a 0.1 s maximum integration step after stalls.

### Recording and Replay

From `controller/`:

```bash
sudo ./main.sh --record /tmp/aeyes-captures.jsonl
.venv/bin/python replay.py /tmp/aeyes-captures.jsonl
```

`--record` writes one JSON object per camera frame with `timestamp`, `sequence`, and project-frame `detections`. `replay.py` runs without camera, network publication, or motor access and reports frame gaps, valid/depthless detection counts, and track IDs created.

Optional independent ground truth can be added to each frame as `truth: [{"id": "person-a", "position": {"x": 2, "y": 0, "z": 0}}]`. Labelled replay reports identity switches, fragmentation, reacquisition delay, position error, and target-angle error over reachable eye directions. Unlabelled recordings leave accuracy metrics null. Target-angle error evaluates controller geometry, not physical motor error. The CLI accepts `--match-distance` to set the evaluation association gate in meters.

## Coordinates and Geometry

- DepthAI spatial output: X right, Y down, Z forward ([Luxonis reference](https://docs.luxonis.com/software-v3/depthai/depthai-components/nodes/spatial_location_calculator)).
- `Controller._camera_xyz_to_detection()` maps this to **X forward, Y left, Z up**: `(Z, -X, -Y)`.
- Tracker positions remain relative to the **camera origin**, expressed in project axes. `Conversions.camera_to_base()` adds the camera mount translation.
- Positive yaw is CCW viewed from above; positive pitch is upward. `get_pitch_yaw()` returns **(yaw, pitch)** in degrees.
- The pitch pivot is **103.5 mm** forward of the yaw pivot (`PITCH_PIVOT_OFFSET`), not 80 mm.
- Camera mount: `(0.04375, 0.0, 0.0)` meters. Camera rotation is currently hard-coded to zero.
- `CAMERA_CONFIG` FOV values (127° horizontal, 79.5° vertical) are used by the simulators; camera spatial inference uses the DepthAI pipeline.
- Yaw is calculated in the translated gimbal frame, accounting for both gimbal X and Y offsets; pitch then accounts for the rotated pitch-pivot offset.

All layout values live in `controller/config.py`:

| Eye | X (m) | Y (m) | Z (m) |
|---|---:|---:|---:|
| 1 | 0.0275 | -0.360 | 0.0 |
| 2 | 0.0275 | -0.180 | 0.31177 |
| 3 | 0.0275 | 0.180 | 0.31177 |
| 4 | 0.0275 | 0.360 | 0.0 |
| 5 | 0.0275 | 0.180 | -0.31177 |
| 6 | 0.0275 | -0.180 | -0.31177 |

## Shared Message Contract

`controller/data_types.py` and `eye/data_types.py` define matching `ControlMessage` dataclasses. Keep their field names, types, and serialization synchronized; `test_eye_render_pipeline.py` checks compatibility.

Current fields:

- Geometry/appearance: `radius`, `rotation_deg`, `eye_lid_position`, `iris_size`, `pupil_size`, `curvature`, `is_cat_eye`, `vein_count`, `vein_seed`.
- RGB integer triplets (0–255): `iris_color`, `striation_color`, `iris_accent_color`, `iris_center_color`, `pupil_color`, `sclera_color`, `vein_color`.
- Motor targets in degrees: `yaw`, `pitch`.

`radius` controls the outer rendered eye radius; it is independent of iris/pupil size. `eye_lid_position` is 0 closed, 1 open. The former `cornea_color` field no longer exists. Pi renderer setters normalize RGB to 0–1.

## Configuration and Important Defaults

Behavioral settings live in **`controller/params.yaml`**, loaded once at import by `parameters.py` using the pure types/validation in `parameter_schema.py`. The dashboard resets to versioned `params.defaults.yaml` and saves atomically with revision checks. Restart after edits. Physical geometry lives in `config.py`; detector-specific settings still live in `camera/detector.py` and the NN archive.

Key values as currently configured:

| Setting | Value | Meaning |
|---|---:|---|
| `system.refresh_rate_hz` | 15 | Camera FPS limit and controller publish schedule |
| `tracker.base_max_distance` | 0.4 | Base positional matching gate (m) |
| `tracker.depth_scale_factor` | 0.15 | Per-track gate growth with forward depth (project X) |
| `tracker.min_hits_to_confirm` | 30 | Consecutive detections for new-track confirmation |
| `tracker.min_hits_to_confirm_reacquiring_tracks` | 3 | Consecutive XYZ detections for lost-track reacquisition |
| `tracker.max_missing_confirmed` / `max_missing_tentative` | 30 / 5 | Nominal frames converted to 2 s / 0.333 s missing grace |
| `tracker.reid_window_frames` / `reid_max_distance` | 45 / 1.0 | 3 s lost-track retention and spatial gate (m) |
| `tracker.ema_alpha` | 0.4 | Output-position smoothing |
| `tracker.static_window` / `static_speed_thresh_mps` | 1000 / 0.15 | Nominal window duration (66.7 s) and static cutoff (m/s) |
| `tracker.mahalanobis_gate` | 11.345 | Squared innovation gate for 3D association |
| `tracker.min_detection_confidence` | 0.5 | Minimum confidence admitted by the tracker |
| `tracker.depth_grace_s` / `coast_time_s` | 0.5 / 0.25 | Depthless association grace and public extrapolation cap |
| `assigner.assign_interval_s` | 0.5 | Delay between extra-eye assignments |
| `eye_manager.color_in_rate` / `color_out_rate` | 2.0 / 4.0 | Time-based palette transitions |
| `eye_manager.blink_rate` | 1.0 | New-assignment blink speed |

New-track confirmation still requires 30 actual XYZ observations (about two seconds at 15 Hz). Short confirmed-track dropouts do not repeat that delay. Static classification requires about 67 seconds of uninterrupted matched depth observations at the current window setting.

Kalman defaults are `acceleration_noise=1.5` (continuous velocity diffusion in m²/s³), `measurement_std_lateral=0.05` m, and `measurement_std_depth=0.20` m. The measurement standard deviations are squared into covariance `R`, with depth noise on project X. Confidence/depth trust scales measurement covariance. The old `process_noise` and `measurement_noise_xy/z` YAML keys have been replaced; deploy `parameters.py`, `params.yaml`, and the filter together.

Eye-side network/timing constants are independent of YAML: controller address `192.168.5.100`, port 9000, timeout 3 s. The subscriber keeps the latest message using ZMQ conflation and clamps finite targets to configured motor limits. Motor ramping uses measured elapsed time between worker ticks, retaining thresholds/rates of 5°/30° and 900°/s/22.5°/s.

## Hardware and Motor Control

- Controller: Raspberry Pi 5 at `192.168.5.100`, USB OAK-D W.
- Eye units: Raspberry Pi 4B at `192.168.5.101`–`192.168.5.106`, Waveshare 4-inch DSI LCD, RS485/CAN Hat, `can0` at 1 Mbps.
- The root README identifies the yaw motor as **MG4010E-i10v3** and pitch as **MG4005-v2**. Some motor-driver comments still describe both as MG4010E.
- Motor configuration is **`eye/motors/motor_config.py`**, not `motor_list.py`.
- CAN ID 1 = BASE/yaw; CAN ID 2 = EYE/pitch. Both have nominal ±45° limits and default `inverse_rotation=True`.
- Configured endstop positions: BASE 67.5°, EYE 45°. Eye 2 homes BASE in the opposite direction. Eyes 4 and 6 toggle both motor inversions for their upside-down mounting.
- `home_motors()` temporarily disables position limits to seek endstops. Both axes must stop with fresh, advancing CAN position samples (maximum age 0.25 s; cumulative displacement within 0.25° for 0.5 s) before either calibration is written. Enable sequencing is followed by a bounded wait for fresh feedback. Timeout, stale/missing feedback, or cancellation disables motors, restores limits, displays an error, and prevents subscriber startup.
- Position samples are timestamped only for valid ID/0x92 position replies. Home offsets, adjusted feedback, position limits, and zero targets are updated atomically with CAN workers. Partial enable failure rolls back all motors; disable attempts every motor and releases locks even on transport errors. Worker position commands require the collection enable flag.
- `motor.py` implements CAN commands and position transforms. `motors.py` owns CAN initialization, worker threads, locks, and enable/disable sequencing.

## Deployment and Services

```bash
./scripts/ping-all-pis.sh
./scripts/push-eye-code.sh --dry-run
```

- `push-eye-code.sh` rsyncs the local **eye directory** to all six Pis with `--delete`, preserving excluded `.env`/`.venv` files. A normal push restarts each eye's `main.service`, which runs motor startup/homing. `--no-reset` suppresses the restart. Only one positional flag is currently handled.
- `pull-eye-code.sh` rsyncs **eye1 → the local eye directory** for collecting edits made on that Pi. It does not run git pull on all Pis.
- Both scripts currently use a development-PC path under `/home/$USER/Desktop/projects/aEyes/eye/`; alternative Pi paths are commented out.
- `eye/install.sh` configures host/eye identity, firmware/display/CAN, dependencies, networking, and `main.service`. It requires sudo and restarts the service.
- `controller/install.sh` requires sudo and installs dependencies/networking, OAK USB access, the dashboard build, nginx on port 80, and `main.service`/`aeyes-monitor.service` units. Controller and monitor activation is explicit; the existing `shutdown.service` is enabled/restarted during installation.
- The shutdown button uses GPIO 21 and invokes `scripts/shutdown-eyes.sh` before shutting down the controller.

On eye units:

```bash
sudo systemctl status main.service
sudo journalctl -u main.service -f
```

The installed eye service sets `DISPLAY=:0` and `XAUTHORITY`. Controller auto-start should not be assumed from the current install script.

## Key Files and Dependencies

| File | Role |
|---|---|
| `controller/main.py` | Live camera → tracking → eye state → publication loop |
| `controller/camera/detector.py` | Active DepthAI v3 YuNet + aligned stereo spatial pipeline |
| `controller/face_tracker.py`, `kalman_filter_3d.py` | Track lifecycle, association, re-ID, constant-velocity filtering |
| `controller/eye_assigner.py`, `eye_manager.py` | Face-to-eye allocation, palettes, blinks, eyelids, orientation |
| `controller/conversions.py`, `matrix_utils.py` | Coordinate transforms and gimbal geometry |
| `controller/parameters.py`, `params.yaml`, `config.py` | Behavioral settings and physical layout |
| `controller/publisher.py`, both `data_types.py` files | JSON/ZMQ wire contract |
| `controller/demo.py`, `visual.py`, `plot.py` | Synthetic pipeline demos and visualizers |
| `controller/replay.py` | Capture-log replay and optional ground-truth metrics |
| `controller/monitoring/`, `controller/ui/` | Isolated FastAPI monitoring/MJPEG API and Yarn/Vite/React/Three.js dashboard |
| `controller/deploy/` | Controller/monitor systemd units, port-80 nginx proxy, restricted restart rule |
| `controller/test_*.py` | Hardware-independent unittest suite |
| `eye/main.py` | Subscriber, startup/homing, command ramping, renderer dispatch |
| `eye/eye_renderer.py`, `eye/shaders/eye.frag` | Pyglet/GLES 3.1 rendering and procedural eye shader |
| `eye/motors/`, `eye/zero.py` | CAN control/configuration and manual zeroing |

Both components have their own `requirements.txt` and `.venv`. Controller dependencies include DepthAI 3.6.1, depthai-nodes 0.5.0, NumPy/SciPy, PyYAML, pyzmq, OpenCV, and the plotting/Qt libraries. Eye dependencies include Pyglet, PyOpenGL, pyzmq, NumPy, python-can, RPi.GPIO, rich, and prompt_toolkit. The controller requirements still include both OpenCV wheel variants and an older redundant DepthAI lower bound; inspect the file before changing dependency pins.

## Web Dashboard Development

From `controller/`, run `.venv/bin/python -m monitoring --demo --reload` for hardware-free telemetry/images. From `controller/ui/`, run `yarn dev` and open http://localhost:5173/. Live mode uses the monitor without `--demo` plus `main.py --monitor`, which publishes to physical eyes. Production nginx serves port 80 and proxies `/api` to localhost:8080; the monitoring feed uses loopback ZMQ port 9101. Eye status is network reachability only. See controller/README.md for full commands. Run `yarn test` and `yarn build` in `controller/ui/` and the controller unittest suite after changes. The standard unittest API/transport tests require local event-loop/socket access.
