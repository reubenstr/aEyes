#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Must be run as root
if [ "$(id -u)" -ne 0 ]; then
    echo "This script must be run with sudo or as root"
    exit 1
fi

USER_NAME="${SUDO_USER:-$USER}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
USER_BASHRC="$USER_HOME/.bashrc"
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
VENV_DIR="$ROOT_DIR/.venv"
ETH_IP="192.168.5.100/24"

if [ "$USER_NAME" = root ]; then
    echo "Run with sudo from the deployment user's account (not a root login)." >&2
    exit 1
fi

# -----------------------------------------------------------------------------
# Create virtual environment as the non-root user
if [ -d "$VENV_DIR" ]; then
    echo "Virtual environment already exists. Skipping creation."
else
    echo "Creating virtual environment as $USER_NAME"
    sudo -u "$USER_NAME" python3 -m venv "$VENV_DIR" --system-site-packages
fi


# -----------------------------------------------------------------------------
# System Dependancies
echo "Installing system GPIO dependencies..."
apt update
apt install -y \
    python3-lgpio \
    python3-gpiozero \
    nginx curl ca-certificates xz-utils iputils-ping sudo rsync

# -----------------------------------------------------------------------------
# Install requirements as the non-root user
echo "Installing python dependencies from requirements.txt as $USER_NAME"
if [ -f "$ROOT_DIR/requirements.txt" ]; then
    sudo -u "$USER_NAME" "$VENV_DIR/bin/python" -m pip install --upgrade pip
    sudo -u "$USER_NAME" "$VENV_DIR/bin/python" -m pip install -r "$ROOT_DIR/requirements.txt"
else
    echo "requirements.txt not found!"
    exit 1
fi

# -----------------------------------------------------------------------------
# Configure ethernet with static IP
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


# -----------------------------------------------------------------------------
# Install shutdown.service
echo "Installing service for shutdown.py"

tee /etc/systemd/system/shutdown.service > /dev/null << EOF
[Unit]
Description=Shutdown Service
After=multi-user.target

[Service]
Type=simple
WorkingDirectory="$ROOT_DIR"
Environment=DISPLAY=:0
Environment=XAUTHORITY=$USER_HOME/.Xauthority
ExecStart="$VENV_DIR/bin/python" "$ROOT_DIR/shutdown.py" --service
Restart=on-failure
RestartSec=5s
TimeoutStopSec=10s

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable shutdown.service
systemctl restart shutdown.service

echo "Run this command to see the service status: sudo systemctl status shutdown.service"
echo "Run this command to see live logs: sudo journalctl -u shutdown.service -f"

# -----------------------------------------------------------------------------
# Node 24 LTS and pinned Yarn; build as the deployment user, never as root.
TASK_TMP="$(mktemp -d)"
trap 'rm -rf -- "$TASK_TMP"' EXIT

if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" != 24 ]; then
    case "$(dpkg --print-architecture)" in
        arm64) NODE_ARCH=arm64 ;;
        amd64) NODE_ARCH=x64 ;;
        *) echo "Node 24 requires a supported 64-bit OS (arm64 or amd64)." >&2; exit 1 ;;
    esac
    curl --fail --silent --show-error https://nodejs.org/dist/index.json -o "$TASK_TMP/node-index.json"
    NODE_VERSION="$(python3 - "$TASK_TMP/node-index.json" <<'PY'
import json, sys
print(next(v['version'] for v in json.load(open(sys.argv[1])) if v['version'].startswith('v24.') and v['lts']))
PY
)"
    NODE_ARCHIVE="node-$NODE_VERSION-linux-$NODE_ARCH.tar.xz"
    curl --fail --silent --show-error "https://nodejs.org/dist/$NODE_VERSION/$NODE_ARCHIVE" -o "$TASK_TMP/$NODE_ARCHIVE"
    curl --fail --silent --show-error "https://nodejs.org/dist/$NODE_VERSION/SHASUMS256.txt" -o "$TASK_TMP/SHASUMS256.txt"
    (cd "$TASK_TMP" && awk -v archive="$NODE_ARCHIVE" '$2 == archive' SHASUMS256.txt | sha256sum --check --status)
    tar -xJf "$TASK_TMP/$NODE_ARCHIVE" -C /opt
    for NODE_TOOL in node npm npx; do
        ln -sfn "/opt/node-$NODE_VERSION-linux-$NODE_ARCH/bin/$NODE_TOOL" "/usr/local/bin/$NODE_TOOL"
    done
fi

NODE_BIN="$(dirname -- "$(command -v node)")"
if ! command -v yarn >/dev/null || [ "$(yarn --version)" != 1.22.22 ]; then
    PATH="$NODE_BIN:$PATH" npm install --global yarn@1.22.22
fi
YARN_BIN="$(command -v yarn)"
(cd "$ROOT_DIR/ui" && sudo -u "$USER_NAME" env PATH="$NODE_BIN:$PATH" "$YARN_BIN" install --frozen-lockfile)
(cd "$ROOT_DIR/ui" && sudo -u "$USER_NAME" env PATH="$NODE_BIN:$PATH" "$YARN_BIN" build)
install -d -m 0755 /var/www/aeyes
rsync -r --delete --chmod=D755,F644 "$ROOT_DIR/ui/dist/" /var/www/aeyes/

# Direct Python launch as the deployment user uses the existing OAK USB rule.
printf '%s\n' 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' > /etc/udev/rules.d/80-movidius.rules
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb

# Render templates without assuming the checkout lives at ~/aEyes.
python3 - "$ROOT_DIR" "$USER_NAME" "$TASK_TMP" <<'PY'
from pathlib import Path
import sys
root, user, output = sys.argv[1:]
escaped_root = root.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
for filename in ('main.service', 'aeyes-monitor.service', 'aeyes-monitor.sudoers'):
    text = (Path(root) / 'deploy' / filename).read_text()
    (Path(output) / filename).write_text(text.replace('@ROOT@', escaped_root).replace('@USER@', user))
PY
visudo -cf "$TASK_TMP/aeyes-monitor.sudoers"
install -m 0440 "$TASK_TMP/aeyes-monitor.sudoers" /etc/sudoers.d/aeyes-monitor
install -m 0644 "$TASK_TMP/main.service" /etc/systemd/system/main.service
install -m 0644 "$TASK_TMP/aeyes-monitor.service" /etc/systemd/system/aeyes-monitor.service

# The standard nginx default site is replaced by the aEyes port-80 site.
install -m 0644 "$ROOT_DIR/deploy/aeyes-nginx.conf" /etc/nginx/sites-available/aeyes
if [ -L /etc/nginx/sites-enabled/default ] && [ "$(readlink -f /etc/nginx/sites-enabled/default)" = /etc/nginx/sites-available/default ]; then
    rm /etc/nginx/sites-enabled/default
fi
ln -sfn /etc/nginx/sites-available/aeyes /etc/nginx/sites-enabled/aeyes
nginx -t
systemctl daemon-reload
systemctl reload nginx

echo ""
echo "Install complete. Controller startup is explicit:"
echo "  sudo systemctl enable --now main.service aeyes-monitor.service nginx"
echo "Dashboard: http://192.168.5.100/ (port 80)"
echo "Logs: sudo journalctl -u main.service -u aeyes-monitor.service -f"
