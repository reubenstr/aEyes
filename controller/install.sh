#!/usr/bin/env bash
set -euo pipefail

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

# Activate virtual environment
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
# Configure ethernet with static IP
ETH_IP="192.168.5.100/24"

echo "Setting Ethernet IP to $ETH_IP"

# Find Ethernet connection associated with eth0
ETH_CON="$(nmcli -t -f NAME,DEVICE con show | grep ':eth0$' | cut -d: -f1 || true)"

# Fallback: first ethernet-type connection
if [ -z "$ETH_CON" ]; then
    ETH_CON="$(nmcli -t -f NAME,TYPE con show | grep -E ':ethernet$|:802-3-ethernet$' | cut -d: -f1 | head -n1 || true)"
fi

if [ -z "$ETH_CON" ]; then
    echo "No Ethernet connection profile found"
    exit 1
fi

echo "Using connection profile: $ETH_CON"

echo "Applying static configuration..."
nmcli con mod "$ETH_CON" \
    ipv4.method manual \
    ipv4.addresses "$ETH_IP" \
    ipv4.gateway "" \
    ipv4.dns "" \
    ipv4.never-default yes \
    ipv4.route-metric 900

echo "Bringing connection up..."
nmcli con up "$ETH_CON"

echo "Ethernet setup complete"

echo ""
echo "DEV: PREMATURE EXIT. IN DEVELOPMENT, NOT READY FOR SERVICE."
exit

# -----------------------------------------------------------------------------
# Install main.service
echo "Installing service for main.sh"

tee /etc/systemd/system/main.service > /dev/null << EOF
[Unit]
Description=Main Service
After=multi-user.target

[Service]
Type=simple
WorkingDirectory=$USER_HOME/aEyes/controller
Environment=DISPLAY=:0
Environment=XAUTHORITY=$USER_HOME/.Xauthority
ExecStart=$USER_HOME/aEyes/controller/main.sh --service
Restart=on-failure
RestartSec=5s
TimeoutStopSec=10s

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable main.service
systemctl restart main.service

echo "Run this command to see the service status: sudo systemctl status main.service"
echo "Run this command to see live logs: sudo journalctl -u main.service -f"



# -----------------------------------------------------------------------------
# Complete
echo ""
echo "Install complete."