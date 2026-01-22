# EYE

sudo apt install -y python3-venv
pip install --upgrade pip
python3 -m venv .venv
source .venv/bin/activate
sudo apt install -y python3-dev libgl1-mesa-dev libx11-dev
pip install pyglet moderngl PyOpenGL vispy pygame pillow
pip install pyzmq





for VSCODE GLSL Lint extension:
sudo apt install -y glslang-tools

TEMP:

export DISPLAY=:0
export XAUTHORITY=/home/pi/.Xauthority



WAYLAND_DISPLAY : None
DISPLAY         : :0
GL_VERSION      : OpenGL ES 3.1 Mesa 25.0.7-2+rpt3
GL_RENDERER     : V3D 4.2.14.0
GL_VENDOR       : Broadcom
GLSL            : OpenGL ES GLSL ES 3.10
