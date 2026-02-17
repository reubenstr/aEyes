# EYE

This code creates the eye graphic and controls the motors.

Executed on the Raspbery Pi 4.

## Hardware

  Raspberry Pi 4 B with 4MB RAM (but 2MB will likely work).
- https://www.raspberrypi.com/products/raspberry-pi-4-model-b/

Waveshare 4inch DSI LCD
- https://www.waveshare.com/4inch-dsi-lcd-c.htm
- https://www.waveshare.com/wiki/4inch_DSI_LCD_(C)


Waveshare RS485 CAN Hat
- https://www.waveshare.com/rs485-can-hat.htm
- http://www.waveshare.com/wiki/RS485_CAN_HAT


## Installation

### Operating System

Raspberry Pi OS (64-bit) Desktop (Trixie)

SD creation tool:
- https://www.raspberrypi.com/software/

Use the Raspberry Pi creation tool and apply OS customization with the following:
- Username/password
- Wifi credentials
- Locale settings
- Enable SSH

Do not set hostname.

Boot the Pi.

Copy over SSH keys from development PC

```bash
ssh-copy-id pi@192.168.1.<200+<EYE_ID>>
```

Update the system:

```bash
sudo apt update
sudo apt full-upgrade
```

Setup dependencies:

```bash
sudo apt install -y python3-venv
pip install --upgrade pip
```

Clone the repo in the home directory:

```bash
cd ~
git clone jetson@192.168.1.200:~/git-remotes/aEyes.git
```

### Script Installation

Run the setup.sh script to complete the following:

- Selects EYE_ID (user selected)
- Configs the RPi firmware (overlays for LCD and CAN)
- Creates virtual environment
- Adds EYE_ID to .env
- Adds dev env vars to user's .bashrc
- Installs Python dependancies
- Enables low power mode
- Sets the desktop background image
- Hides the taskbar
- Installs services
- Configures ethernet static IP


## Manual execution

### Eyes:

ENV vars required to start GUI on RPI over SSH:

```bash
export DISPLAY=:0
export XAUTHORITY=/home/pi/.Xauthority
```

main.sh loads the virtual environment then starts the main script
```
cd aEyes/eyes
sudo ./main.sh
```


### Misc Resources

RPI4 UART Pins: https://pragmaticaddict.com/raspi-5-serial-ports.html


### Misc. Commands Under Test


TEMP:
echo powersave | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
echo 600000 | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq

MORE:

sudo ip link set can0 up type can bitrate 1000000
sudo ifconfig can0 txqueuelen 65536
sudo ifconfig can0 up

sudo ip link set can1 up type can bitrate 1000000
sudo ifconfig can1 txqueuelen 65536
sudo ifconfig can1 up
