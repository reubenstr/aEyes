# Controller

Captures camera data and sends commands to the eyes.

## Installation


Create bare repo
```bash
mkdir -p ~/git-remotes
git clone --bare git@gitlab.com:reubenstr/aEyes.git ~/git-remotes/aEyes.git
```

Clone from the bare repo
```bash
git clone ~/git-remotes/aEyes.git ~/aEyes
```

Push controller updates
```bash
cd ~/aEyes
git push origin main
```

Push all updates to the remote repo (Gitlab)
```bash
cd ~/git-remotes/aEyes.git
git push origin main
```



## Jetson

Install OS with Jetpack 5.1.3 using the SDK Manager:
https://developer.nvidia.com/sdk-manager

Username/password: nvidia/nvidia

Boot up using physical keyboard, mouse, and monitor.

Connect to WiFi with internet.

Clone the repo
```bash
cd ~
git clone git@github.com:reubenstr/aEyes.git
```

Run the install script to setup virtual environment and more:

```bash
cd ~/aEyes/controller
sudo ./install.sh
```

## Setup Camera on Jetson

Install dependancies:

```bash
sudo apt update
sudo apt install -y git cmake build-essential libssl-dev libusb-1.0-0-dev \
libgtk-3-dev pkg-config libglfw3-dev libgl1-mesa-dev libglu1-mesa-dev at
```

Build and install RealSense libraries and GUI:
```bash
cd ~
git clone https://github.com/IntelRealSense/librealsense.git
cd librealsense
mkdir build && cd build
cmake .. -DBUILD_EXAMPLES=ON -DBUILD_PYTHON_BINDINGS=ON -DPYTHON_EXECUTABLE=$(which python3) -DFORCE_RSUSB_BACKEND=ON
make -j4
sudo make install
sudo ldconfig
```
Manually copy RealSense Python libs:

```bash
cd /home/nvidia/librealsense/build/
sudo cp /home/nvidia/librealsense/build/Release/pyrealsense2*.so /usr/lib/python3/dist-packages/
sudo cp ~/librealsense/build/Release/pyrealsense2*.so /home/nvidia/aEyes/controller/.venv/lib/python3.8/site-packages
```

Setup udev rules:

```bash
sudo cp ~/.99-realsense-libusb.rules /etc/udev/rules.d/99-realsense-libusb.rules && sudo udevadm control --reload-rules && udevadm trigger
```

List connected RealSense cameras:

```bash
rs-fw-update -l
```

Check for firmware updates:

https://dev.realsenseai.com/docs/firmware-releases-d400

Update firmware command example: 

```bash
sudo rs-fw-update -f ~/Downloads/Signed_Image_UVC_5_17_0_10.bin
```

Test camera using the Realsense Viewer GUI:

```bash
realsense-viewer
```

Install dependencies

```bash
sudo apt-get update
sudo apt-get install python3-pip libopenblas-base libopenmpi-dev
sudo apt-get install libomp-dev
```


----------------

sudo apt-get update

python3 -m pip install --upgrade pip setuptools wheel
pip3 install numpy==1.23.5
python3 -m pip install cuda-python

https://huggingface.co/crj/dl-ws/blob/8f8ec345154a161633d8294fd5e21908c97d7f8a/scrfd_2.5g.onnx

/usr/src/tensorrt/bin/trtexec \
  --onnx=scrfd_2.5g.onnx \
  --shapes=input.1:1x3x640x640 \
  --saveEngine=face_fp16.engine \
  --fp16 \
  --workspace=2048

/usr/src/tensorrt/bin/trtexec \
    --onnx=scrfd_2.5g.onnx \
  --shapes=input.1:1x3x480x480 \
  --saveEngine=face_480_fp16.engine \
  --fp16 \
  --memPoolSize=workspace:2048 

-------------




### MISC

sudo apt install -y python3-venv

python3 -m venv .venv

source .venv/bin/activate

pip install --upgrade pip

pip install pyzmq

sudo chown -R nvidia:nvidia /home/nvidia/aEyes/controller/.venv



(.venv) nvidia@ubuntu:~/aEyes/controller/tests$ nvcc --version
nvcc: NVIDIA (R) Cuda compiler driver
Copyright (c) 2005-2022 NVIDIA Corporation
Built on Sun_Oct_23_22:16:07_PDT_2022
Cuda compilation tools, release 11.4, V11.4.315
Build cuda_11.4.r11.4/compiler.31964100_0





