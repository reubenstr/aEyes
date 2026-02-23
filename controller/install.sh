#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Check if the device is a Jetson
#if ! grep -q "Jetson" /proc/device-tree/model 2>/dev/null; then
#    echo "This installation script is only for the Jetson!"
#    exit 1
#fi

# -----------------------------------------------------------------------------
# Must be run as root
if [ "$(id -u)" -ne 0 ]; then
    echo "This script must be run with sudo or as root"
    exit 1
fi

# -----------------------------------------------------------------------------
# Create virtual environment if it does not exist
if [ -d ".venv" ]; then
    echo "Virtual environment already exists. Skipping creation."
else
    echo "Creating virtual environment"
    python3 -m venv .venv
fi

. .venv/bin/activate


# -----------------------------------------------------------------------------
# Install depenancies
echo "Installing system dependancies"
# apt install -y 

# -----------------------------------------------------------------------------
# Install requirements
echo "Installing python dependancies from requirements.txt"
if [ -f "requirements.txt" ]; then
    pip install --upgrade pip
    pip install -r requirements.txt
else
    echo "requirements.txt not found!"
    exit 1
fi


# -----------------------------------------------------------------------------
# Complete
echo ""
echo "Install complete."