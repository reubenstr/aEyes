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



### MISC

sudo apt install -y python3-venv

python3 -m venv .venv

source .venv/bin/activate

pip install --upgrade pip

pip install pyzmq








