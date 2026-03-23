#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Install dependencies
# echo "Installing system dependancies"
# apt install python3.8-venv

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