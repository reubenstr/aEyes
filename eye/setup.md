# EYE

sudo apt install -y python3-venv
pip install --upgrade pip
python3 -m venv .venv

sudo apt install python3-dev libgl1-mesa-dev libx11-dev
pip install pyglet moderngl PyOpenGL vispy pygame pillow
pip install pyzmq


source .venv/bin/activate


for VSCODE GLSL Lint extension:
sudo apt install -y glslang-tools


