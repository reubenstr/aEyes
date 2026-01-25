# EYE

sudo apt install -y python3-venv
pip install --upgrade pip
python3 -m venv .venv
source .venv/bin/activate
sudo apt install -y python3-dev libgl1-mesa-dev libx11-dev
pip install pyglet moderngl PyOpenGL vispy pygame pillow
pip install pyzmq



pip3 install PyTmcStepper
pip3 install RPi.GPIO pyserial



for VSCODE GLSL Lint extension:
sudo apt install -y glslang-tools

TEMP:

export DISPLAY=:0
export XAUTHORITY=/home/pi/.Xauthority
python3 ./main.py



WAYLAND_DISPLAY : None
DISPLAY         : :0
GL_VERSION      : OpenGL ES 3.1 Mesa 25.0.7-2+rpt3
GL_RENDERER     : V3D 4.2.14.0
GL_VENDOR       : Broadcom
GLSL            : OpenGL ES GLSL ES 3.10


add to config.txt after [all]:

```
# Enable Waveshare DSI LCD display
dtoverlay=vc4-kms-v3d
dtoverlay=vc4-kms-dsi-waveshare-panel,4_0_inchC

# Enable primary UART on GPIO14/15 (pins 8/10)
enable_uart=1

# Free PL011 UART0 from Bluetooth so it appears on GPIO14/15
dtoverlay=disable-bt

# Enable extra UART
dtoverlay=uart2
```


Check serial ports: 

```
ls -al /dev/ttyAMA*
```


TMC2208

https://github.com/bigtreetech/BIGTREETECH-TMC2208-V3.0


### Misc Resources

RPI4 UART Pins: https://pragmaticaddict.com/raspi-5-serial-ports.html