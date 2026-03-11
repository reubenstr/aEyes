# EYE

This code creates the eye graphic and controls the motors.

Executed on the Raspberry Pi 4.

## Hardware

- Raspberry Pi 4 B with 4GB RAM (but 2GB will likely work).
- https://www.raspberrypi.com/products/raspberry-pi-4-model-b/

Waveshare 4inch DSI LCD
- https://www.waveshare.com/4inch-dsi-lcd-c.htm
- https://www.waveshare.com/wiki/4inch_DSI_LCD_(C)

Waveshare RS485 CAN Hat
- https://www.waveshare.com/rs485-can-hat.htm
- http://www.waveshare.com/wiki/RS485_CAN_HAT


## Installation

### Operating System

Create a master SD card that will be cloned for the remaining five RPis.

SD creation tool:
- https://www.raspberrypi.com/software/

Use the Raspberry Pi creation tool and apply OS customization with the following:
- Operating system: Raspberry Pi OS (64-bit) Desktop (Trixie)
- Hostname: eye<EYE_ID> (e.g: eye1, eye2, eye3...)
- Username/password: pi/pi
- Wifi credentials 
- Locale settings
- Enable SSH

Connect the Pi to a keyboard/monitor and boot the Pi. 

Copy the controller's SSH keys to the RPi:
```bash
ssh-copy-id pi@eye<EYE_ID>.local
```

Copy the Eye files:
```bash
scp -r ~/aEyes/eye pi@<ip>:~/aEyes/eye
```

SSH into the RPi:
```bash
ssh pi@eye<EYE_ID>.local
```

Run the install.sh script:
```bash
cd ~/aEyes/eye
sudo ./install.sh
```

The install script completes the following actions:
- Selects EYE_ID (user selected)
- sets the hostname
- resets the machine ID
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

Reboot the Pi:
```bash
sudo reboot
```

Verify the DSI LCD operates correctly and the PI is reachable over ethernet.

Shutdown the PI:
```bash
sudo shutdown now
```

## Cloning

Clone the SD card after setup is complete:
```bash
sudo dd if=/dev/mmcblk0 of=~/master_eye.img bs=4M status=progress
```

Image the other five SD cards:
```bash
sudo dd if=~/master_eye.img of=/dev/sdX bs=4M status=progress
```

Boot up each RPi and run the install.sh script to setup unique configuration. Use a keyboard/monitor.


## Manual execution

### Eyes:

ENV vars are required to start GUI on RPI over SSH:

```bash
export DISPLAY=:0
export XAUTHORITY=/home/pi/.Xauthority
```

main.sh loads the virtual environment then starts the main script
```bash
cd aEyes/eye
sudo ./main.sh
```

### Misc. Commands

```bash
sudo ip link set can0 up type can bitrate 1000000
sudo ifconfig can0 txqueuelen 65536
sudo ifconfig can0 up
```
