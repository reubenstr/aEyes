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




