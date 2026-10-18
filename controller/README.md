# Controller

Captures camera data and sends commands to the eyes.

## Installation

### Operating System

SD creation tool:
- https://www.raspberrypi.com/software/

Use the Raspberry Pi creation tool and apply OS customization with the following:
- Operating system: Raspberry Pi OS (64-bit) Desktop (Trixie)
- Hostname: aeyes
- Username/password: aeyes/aeyes
- Wifi credentials 
- Locale settings
- Enable SSH

If customization is not applied, setup the RPi using keyboard/monitor/mouse and use raspi-config to setup hostname, enable SSH, etc.


Update.
```bash
sudo apt update && sudo apt upgrade
```

Generate SSH keys. Use default options.
```bash
ssh-keygen
```

### Repo

Add key to gitlab.

Clone repo
```bash
cd ~
git clone git@github.com:reubenstr/aEyes.git
```

### Setup Controller
```bash
cd ~/aEyes/controller
```
Execute the installation script:
 
- Setups virtual environment
- Installs depenancies
- Apply static IP address to ethernet
- Installs services

```bash
sudo ./install.sh
```

## OAK-D W


Setup USB rules:

```bash
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' | sudo tee /etc/udev/rules.d/80-movidius.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

# Dev Machine Setup

Use Node.js **24 LTS**, Yarn **1.22.22**, and Python **3.12+**. Python dependencies
are in `requirements.txt`; frontend dependencies are in `ui/package.json` and
`ui/yarn.lock`. All backend commands below run from `controller/`, and frontend
commands run from `controller/ui/`. Do not run the Pi installer on your development
PC: it configures networking, GPIO, nginx and system services.

## Install development dependencies

```bash
cd /path/to/aEyes/controller
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cd ui
yarn install --frozen-lockfile
```

Install Node 24 using your normal Node version manager. To bootstrap the pinned
Yarn version if needed, run `npm install --global yarn@1.22.22`; use Yarn for all
project package installation and builds.

## Dashboard development with the simulation

Start the monitoring API in terminal 1, from `controller/`:

```bash
.venv/bin/python -m monitoring --reload --host 127.0.0.1 --port 8080
```

Start the controller with synthetic detections in terminal 2, from `controller/`:

```bash
.venv/bin/python main.py --demo
```

**Demo mode publishes commands to physical eyes.** It runs without a camera or
desktop/display. Synthetic detections use the same tracker, eye manager, publish
schedule, and monitoring feed as the live controller. The browser dashboard renders
the results. Tracks still need confirmation before they become visible or receive
eyes (30 matched observations by default). `demo.py` only supplies detections; start
demo mode through `main.py --demo` or `sudo ./main.sh --demo`.

Start Vite in terminal 3, from `controller/ui/`:

```bash
yarn dev --host 127.0.0.1 --port 5173 --strictPort
```

Open **http://localhost:5173/**. Vite proxies `/api`, including MJPEG and WebSockets,
to the backend on port 8080. Changes to frontend code update automatically, and
`--reload` reloads backend code. Settings are at **http://localhost:5173/settings**.

The dashboard identifies this source as **Simulation** and shows the application's
tracked faces, assignments, gaze lines, trajectories, colors, and commanded angles.
Camera preview and face crops show **No camera in this source**; images are not
generated for the dashboard. Settings can be saved, then applied by restarting
`main.py --demo` in its terminal. **Save and restart** is unavailable for this source
because service control only restarts the live controller's `main.service`.

The monitoring API always listens for application telemetry. It has no separate
`--demo` mode or synthetic data generator of its own. Run one controller at a
time, either `main.py` or `main.py --demo`: both bind the eye-command port (9000 by
default), and the local monitoring feed uses port 9101. Stop an installed
`main.service` before running the demo manually.

With neither application publishing, the dashboard waits for data. After roughly
one second without fresh telemetry, tracking, assignments, command values, rates,
and active settings are cleared. A lost browser/backend connection also clears
the displayed data and reconnects automatically. CPU/RAM readings describe the
host running the backend, and eye reachability probes continue while the backend
is running, independently of either application. Reachability does not establish
application or motor health.

## Live camera development

Configure the OAK USB udev rule above, reload it, and reconnect the camera if
necessary. Direct Python execution can then run as your normal user; `main.sh`
still requires sudo. Stop any installed controller/monitor services before opening
the same camera or port manually:

```bash
sudo systemctl stop main.service aeyes-monitor.service
```

Start the monitoring API in terminal 1, from `controller/`:

```bash
.venv/bin/python -m monitoring --reload --host 127.0.0.1 --port 8080
```

Start the live controller in terminal 2, from `controller/`:

```bash
.venv/bin/python main.py
```

**The live controller publishes commands to physical eyes.** Dashboard telemetry
and camera preview are enabled by default, including through `main.sh` and the
installed controller service. Use `main.py --no-monitor` to disable the extra
preview output and monitoring producer. The existing `--monitor` flag remains
accepted. Capture recording remains available: `main.py --record /tmp/captures.jsonl`.
The dashboard labels the live controller as **Live camera**.
Demo mode accepts the same options, including `--no-monitor` and
`--record /tmp/demo.jsonl`; synthetic recordings can be read by `replay.py`.
The monitoring API and browser can remain open while you stop one mode and start
the other.

Start Vite in terminal 3, from `controller/ui/`:

```bash
yarn dev --host 127.0.0.1 --port 5173 --strictPort
```

Open **http://localhost:5173/**. Use **Ctrl+C** in each terminal to stop manually
launched servers and the controller. For another device on your development LAN,
bind Vite to `0.0.0.0` and open that computer's address on port 5173.

## Settings and restarting

The Settings screen edits every section of `params.yaml`; physical geometry in
`config.py` is read-only. `params.defaults.yaml` is the versioned reset baseline.
Reset loads defaults into the form. Save validates and atomically writes settings,
retaining `params.yaml.bak`; changes take effect on the next application startup.
Saved and active configurations are shown separately; active values are available
only while fresh application telemetry is arriving. Stale browser revisions are
rejected rather than overwriting another save.

**Save and restart** is available through the installed monitor service and restarts
only the controller's `main.service`. It is disabled while the telemetry source is
`main.py --demo`, including after its feed goes stale. The web backend remains online.
In manual development, save and restart `main.py` or `main.py --demo` in its terminal
instead. Publisher address/port changes also need matching eye-side network
settings. The monitor's
HTTP/telemetry ports are reserved against publisher collisions.

## Build, test and inspect

From `controller/ui/`:

```bash
yarn typecheck
yarn test
yarn build
```

`yarn build` writes `ui/dist/`. To inspect that compiled build locally, keep the
backend running on 8080 and use `yarn preview --host 127.0.0.1 --port 4173`; the
preview server proxies `/api` to the same backend. Production uses nginx on port 80.

From `controller/`:

```bash
.venv/bin/python -m unittest discover -v
curl http://127.0.0.1:8080/api/health
curl http://127.0.0.1:8080/api/state
```

The tests require no camera, display, GPIO, CAN, or reachable Pi. Backend-only
checks report the application offline until a producer starts. The live OAK
preview/detection alignment, sustained 15 Hz publication under load, camera
interruption/reconnection and physical eye reachability still require Pi validation.

## Raspberry Pi production installation

From the controller checkout on the Pi:

```bash
sudo ./install.sh
sudo systemctl enable --now main.service aeyes-monitor.service nginx
```

The installer uses its actual checkout path, installs the unified Python
requirements, Node 24, Yarn and nginx, builds the UI as the deployment user, and
copies compiled assets to `/var/www/aeyes`. It preserves the controller Ethernet
and shutdown-service setup and installs the OAK USB rule. Controller/monitor
startup is explicit; installation does not automatically start either new service.
The existing shutdown service is enabled and restarted during installation.

Open **http://192.168.5.100/** on **port 80**. nginx serves the UI and proxies `/api`
to the independent FastAPI backend on `127.0.0.1:8080`. WebSocket upgrade headers
are forwarded and MJPEG buffering is disabled. The internal monitoring feed is
loopback ZMQ port 9101; the existing eye-command PUB socket remains port 9000.

The installer replaces nginx's standard default-site symlink with the aEyes site.
Remove any other conflicting port-80 default server before enabling this site.
The dashboard assumes a trusted LAN; origin checks prevent cross-origin browser
writes, and the installed sudo rule permits only restarting `main.service`.

```bash
sudo systemctl status main.service aeyes-monitor.service nginx
sudo journalctl -u main.service -u aeyes-monitor.service -f
sudo nginx -t
```

To deploy frontend edits, rerun the installer to rebuild/copy assets. Restart the
monitor service after backend code changes. An already-running controller is not
restarted by installation; restart it explicitly after updating controller code:

```bash
sudo systemctl restart aeyes-monitor.service
sudo systemctl restart main.service
```
