# EYE

This code creates the eye graphic and controls the motors.

Executed on each of the eye's Raspberry Pi 4.

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

Create a master SD card image that will be cloned for the remaining five RPis. The master will be configured as eye1 to start the process.

SD creation tool:
- https://www.raspberrypi.com/software/

Use the Raspberry Pi creation tool and apply OS customization with the following:
- Operating system: Raspberry Pi OS (64-bit) Desktop (Trixie)
- Hostname: eye1
- Username/password: eye/eye
- Wifi credentials 
- Locale settings
- Enable SSH

Connect the Pi to a keyboard/monitor and boot the Pi. 

Copy the controller's SSH keys to the RPi:
```bash
ssh-copy-id eye@eye1.local
```

Copy the Eye files:
```bash
rsync -av --progress ~/aEyes/eye eye@eye1.local:~/aEyes/
```

SSH into the RPi:
```bash
ssh eye@eye1.local
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

Turn off WiFi:
```bash
nmcli radio wifi off
```

Shutdown the PI:
```bash
sudo shutdown now
```

## Cloning

Clone the SD card after setup is complete:
```bash
sudo umount /dev/sda*
sudo dd if=/dev/sda of=~/master_eye.img bs=4M status=progress
sudo eject /dev/sda
```

Image the other five SD cards:
```bash
sudo umount /dev/sda*
sudo dd if=~/master_eye.img of=/dev/sda bs=4M status=progress conv=fsync
sudo eject /dev/sda
```

Boot up each RPi and run the install.sh script to setup unique EYE_ID per RPi. Use a keyboard/monitor or boot the RPis one at a time and ssh into eye@eye1.local.


## Mechanical

After the hardware is fully assembled and each RPi's software is configured, set the zero position of each motor.
Execute the zero.sh script per RPi.


## Development

ENV vars are required to start GUI on the RPi over SSH:

```bash
export DISPLAY=:0
export XAUTHORITY=/home/pi/.Xauthority
```

Since the main.sh is exected via a service, stop the service prior to manually executing main.sh

```bash
systemctl stop main.service
```

Manually start the eye's software.

```bash
cd aEyes/eye
sudo ./main.sh
```

### Misc. Commands and Notes

```bash
sudo ip link set can0 up type can bitrate 1000000
sudo ifconfig can0 txqueuelen 65536
sudo ifconfig can0 up
```
