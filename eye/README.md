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


## Tracking motion

`main.py` advances separate yaw and pitch trajectories between controller messages.
`motors/motion.py` uses quintic curves that preserve position, velocity and
acceleration when goals change, and checks speed, acceleration, jerk and joint
limits over the entire planned curve. A goal inside the current stopping distance
may require continued motion in the old direction while braking. If a new curve
cannot meet the limits, the previous feasible curve finishes before replanning.

Tune each motor's `motion=MotionLimits(...)` in `motors/motor_config.py`, then restart:

| Setting | BASE / yaw | EYE / pitch |
|---|---:|---:|
| Maximum speed (degrees/s) | 45 | 30 |
| Maximum acceleration (degrees/s²) | 90 | 60 |
| Maximum jerk (degrees/s³) | 360 | 240 |
| Maximum commanded/measured position difference (degrees) | 5 | 5 |
| Maximum feedback age (s) | 0.25 | 0.25 |

These are starting values for hardware tuning using the existing current limits.
They use the eye application's angle coordinates; they do not change driver PI
gains, current limits, acceleration settings, homing speed or raw CAN speed caps.

Tracking initializes from fresh adjusted position feedback after homing. Missing,
stale or out-of-range feedback pauses an axis at its last accepted target. Excessive
following error also pauses it, and recovery requires feedback to get within half
the configured error limit of that held target. Pausing does not disable the motor;
its existing position target and hardware current limit remain active. Recovery
reseeds the trajectory at rest from fresh feedback, so no future motion accumulates
while paused. Fault holds/reseeding take precedence over normal smooth-motion limits.

A controller timeout holds the last accepted targets. Reconnection, or an eye worker
tick delayed more than 0.1 seconds, reseeds from fresh feedback before moving again.

## Mechanical

The main.py script will not initialize the motors if the .motors-zeroed file flag has not been found.

Use the zero.py script to zero the motors. When both motors have been zeroed the script will create the .motors-zered file flag allowing main.py to start

After the hardware is fully assembled and each RPi's software is configured, set the zero position of each motor.
Execute the zero.sh script per RPi.


## Development

Show the RPi's display on the dev machine's display over SSH:
```bash
ssh -Y eye@eye1.local
```

Since the main.sh is exected via a service, stop the service prior to manually executing main.sh:
```bash
systemctl stop main.service
```

Manually start the eye's main script:
```bash
cd aEyes/eye
sudo env DISPLAY="$DISPLAY" XAUTHORITY=/home/eye/.Xauthority ./main.sh
```

### Misc. Commands and Notes

Manually up the CAN interface:
```bash
sudo ip link set can0 up type can bitrate 1000000
sudo ifconfig can0 txqueuelen 65536
sudo ifconfig can0 up
```

Check the main service status and view logs:
```bash
sudo systemctl status main.service
sudo journalctl -u main.service -f
```
