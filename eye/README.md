# EYE

This code creates the eye graphics and controls the stepper driver board.

Executed on the Raspbery Pi 4.

## Hardware

  Raspberry Pi 4 B with 4MB RAM (but 2MB will likely work as well).
- https://www.raspberrypi.com/products/raspberry-pi-4-model-b/

Waveshare 4inch DSI LCD
- https://www.waveshare.com/wiki/4inch_DSI_LCD_(C)

Waveshare POE Hat (or your choice of POE hat)
- https://www.waveshare.com/poe-hat-e.htm
- https://www.waveshare.com/poe-hat-c.htm

Custom stepper driver board containing ESP32-S3 and two TMC2209 drivers
 - /aEyes/pcb/stepper-driver/
- /aEyes/firmware/stepper-driver




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

Copy over SSH keys

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
git clone git@github.com:reubenstr/aEyes.git
```

### Script Installation

Run the setup.sh script to complete the following:

- Selects EYE_ID (user selected)
- Configs the RPi firmware (overlays)
- Creates virtual environment
- Adds EYE_ID to .env
- Adds dev vars to user's .bashrc
- Installs Python dependancies
- Enables low power mode
- Sets the desktop background image
- Hides the taskbar
- Installs services
- Configures ethernet static IP





sudo apt install -y python3-dev libgl1-mesa-dev libx11-dev

pip install pyglet moderngl PyOpenGL vispy
pip install pyzmq
pip install pipreqs
pip3 install RPi.GPIO pyserial



for VSCODE GLSL Lint extension:
sudo apt install -y glslang-tools


Store one local to start GUI applications on remote (RPI):
export DISPLAY=:0
export XAUTHORITY=/home/pi/.Xauthority
python3 ./main.py


### Environment


sudo hostnamectl set-hostname <new-hostname>


## Manual execution

Eyes:

```
cd aEyes/eyes
sudo ./main.sh
```


## Debugging

Check serial ports: 

```
ls -al /dev/ttyAMA*
```


TMC2208

https://github.com/bigtreetech/BIGTREETECH-TMC2208-V3.0


### Misc Resources

RPI4 UART Pins: https://pragmaticaddict.com/raspi-5-serial-ports.html





### Misc Setup, under test


TEMP:
echo powersave | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
echo 600000 | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq
