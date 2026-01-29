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

After SD card is flashed, edit the config.txt file on the new partition and add the following lines after the **[ALL]** heading to enable the display and UART.


```
# Enable Waveshare DSI LCD display
dtoverlay=vc4-kms-v3d
dtoverlay=vc4-kms-dsi-waveshare-panel,4_0_inchC

# Enable primary UART on GPIO14/15
enable_uart=1

# Free PL011 UART0 from Bluetooth so it appears on GPIO14/15
dtoverlay=disable-bt
```

Boot the RPi and update the system:

```bash
sudo apt update
sudo apt full-upgrade
```

Clone the repo in the home directory:

```bash
git@github.com:reubenstr/aEyes.git
```

### Script Installation

Run the setup.sh script to setup the virtual environment, install dependancies, and setup services.


- Selects EYE_ID (user selected)
- Creates virtual environment
- Adds EYE_ID to .env
- Adds dev vars to user's .bashrc
- Installs dependancies
- Enables low power mode
- Sets desktop background
- Hides the taskbar
- Installs services
- Configures ethernet static IP


sudo apt install -y python3-venv
pip install --upgrade pip
python3 -m venv .venv
source .venv/bin/activate
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
export EYE_ID="1"

sudo hostnamectl set-hostname <new-hostname>

pcmanfm --set-wallpaper /home/pi/aEyes/eye/media/desktop.jpg

wf-background --image /home/pi/aEyes/eye/media/temp.jpg


sudo -u pi DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus pcmanfm --set-wallpaper /home/pi/aEyes/eye/media/temp.jpg


Autohide taskbar (only shows on physical mouse):
/home/pi/.config/wf-panel-pi/wf-panel-pi.ini
```
[panel]
autohide=true
autohide_duration=500
```


sudo nmcli con mod "ethernet" ipv4.addresses 192.168.1.200/24
sudo nmcli con mod "ethernet" ipv4.gateway 192.168.1.200
sudo nmcli con mod "ethernet" ipv4.dns "8.8.8.8,8.8.4.4"
sudo nmcli con mod "ethernet" ipv4.method manual
sudo nmcli con mod "ethernet" connection.autoconnect yes
sudo nmcli con up "ethernet"



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
