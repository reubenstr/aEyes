#!/bin/bash

# Check if the script is run with sudo.
if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root, use sudo." >&2
    exit 1
fi

# Activate the virtual environment.
if [ -f ".venv/bin/activate" ]; then
    echo "Activating virtual environment..."
else
    echo "Virtual environment activation script not found!" >&2
    exit 1
fi
source .venv/bin/activate

# Source .env variables as user (not sudo).
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
else
    echo ".env file not found!" >&2
    exit 1
fi

# Run the main app and pass through arguments.
if [ -f "./main.py" ]; then
    echo "Starting main..."
else
    echo "Main script not found!" >&2
    exit 1
fi

exec python3 main.py "$@"