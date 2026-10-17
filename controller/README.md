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
./install.sh
```

## OAK-D W


Setup USB rules:

```bash
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' | sudo tee /etc/udev/rules.d/80-movidius.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

# Dev Machine Setup

If developing on a dedicated PC (not an RPi), instead if using the install.sh script, these are manual setup commands:

```bash
cd ./controller
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Test the pipeline displaying test data on a plot (no data is sent):
```
cd ./controller
python3 ./plot.py
```

Test the pipeline displaying test data on a plot and sending data to the eyes:
```
cd ./controller
python3 ./demo.py
```