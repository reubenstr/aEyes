# Controller

- Captures camera data
- Sends commands to the eyes
- Serves GUI
- Provides data to the GUI

# Installation

## Operating System

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

## Repo

Add key to github (or your preferred git provider).

Clone repo

```bash
cd ~
git clone git@github.com:reubenstr/aEyes.git
```

## Setup Controller

On the Raspberry Pi, execute the installer. Select **YES** to all, unless you are intend to development and do want setup services or other aspects of the system. See the # Dev Machine Setup section below for development setup.

The installer provides independent steps to:

- Install system packages.
- Create the Python virtual environment and install dependencies.
- Install Node/Yarn and dashboard dependencies.
- Build and deploy the dashboard.
- Configure OAK USB access.
- Install or update, enable and start the controller and monitor services.
- Install, enable and start the shutdown-button service.
- Install and configure nginx.
- Configure static Ethernet networking.

The following services will be installed:
| Service | Purpose |
|---|---|
| `main.service` | Runs the camera, face tracking, and command publishing to eyes. |
| `aeyes-monitor.service` | Runs the monitoring API and WebSocket server on `127.0.0.1:8080`. |
| `shutdown.service` | Watches the GPIO 21 button and shuts down the eye units and controller when pressed. |
| `nginx.service` | Serves the dashboard on port 80 and proxies monitoring requests. |

```bash
cd ~/aEyes/controller
sudo ./install.sh
```

To install/configure everything without individual prompts:

```bash
sudo ./install.sh --all
```

The static Ethernet address will be: `192.168.5.100/24`

# Development Machine Setup

These instructions are for setting either a computer as a development machine to manually start various services. Do not run the Rasberry Pi installer as it installs services and setups static IP addresses.

## OAK-D W

Setup USB rules:

```bash
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' | sudo tee /etc/udev/rules.d/80-movidius.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## Install development dependencies

```bash
cd ./controller
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

```bash
sudo apt update
sudo apt install -y curl ca-certificates

# Install nvm and load it into this terminal.
export NVM_DIR="$HOME/.nvm"
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.8/install.sh | bash
source "$NVM_DIR/nvm.sh"

# Install Node 24 and make it the default.
nvm install 24
nvm use 24
nvm alias default 24

# Install the project's required Yarn version.
npm install --global yarn@1.22.22

# Verify: Node should report v24.x.x; Yarn should report 1.22.22.
node --version
yarn --version

cd ui
yarn install --frozen-lockfile
```

## Dashboard development with the simulation

Start UI, from `controller/ui/`:

```bash
yarn dev --host 127.0.0.1 --port 5173 --strictPort
```

Open **http://localhost:5173/**. You will see the UI without data.

Start the monitoring service, from `controller/`::

```bash
source .venv/bin/activate
./monitoring/monitor.py --reload --host 127.0.0.1 --port 8080
```

Start the main service, from `controller/`

```bash
source .venv/bin/activate
./main.py --demo
```

**Demo mode publishes commands to physical eyes.** It runs without a camera or
desktop/display. Remove the **--demo** flag to use the camera instead of simulated faces.

## Endpoints

During develop port **8080** is used, but if observing data from installed services, omit this port.

- http://192.168.5.100:8080/api/state — for the full monitoring state as JSON.
- http://192.168.5.100:8080/api/config — saved, default, and active settings.
- http://192.168.5.100:8080/api/health — backend/controller/camera status.
- ws://192.168.5.100:8080/api/ws — continuous state updates.

## Live Development

If developing on a Rasberry Pi that has been setup using the install script, you may stop or reset the services using the following commands.

View live logs from the services:

```bash
sudo journalctl -u <service name> -f
```

Stop the services (until reboot):

```bash
sudo systemctl stop <service name>
```

Restart the services allow recent code changes to take effect:

```bash
sudo systemctl restart <service name>
```

# Troubleshooting

## Websocket

```bash
websocat ws://192.168.5.100:9000
```
