#!/bin/sh
set -e

# Resolve absolute project root (current working directory)
ROOT_DIR="$(pwd -P)"

# Prompt for ID
printf "Enter EYE_ID (1 through 6): "
read EYE_ID

case "$EYE_ID" in
    ''|*[!0-9]*)
        echo "EYE_ID must be an integer"
        exit 1
        ;;
esac

if [ "$EYE_ID" -lt 1 ] || [ "$EYE_ID" -gt 6 ]; then
    echo "EYE_ID must be between 1 and 6"
    exit 1
fi

# Create virtual environment if it does not exist
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

. .venv/bin/activate

# Add environmental variables
ENV_FILE=".env"

if [ -f "$ENV_FILE" ]; then
    grep -v '^EYE_ID=' "$ENV_FILE" > "${ENV_FILE}.tmp"
    mv "${ENV_FILE}.tmp" "$ENV_FILE"
fi

echo "EYE_ID=$EYE_ID" >> "$ENV_FILE"
echo "EYE_ID=$EYE_ID stored in .env"


# Install requirements
if [ -f "requirements.txt" ]; then
    pip install --upgrade pip
    pip install -r requirements.txt
else
    echo "requirements.txt not found"
    exit 1
fi


# Install desktop wallpaper.
WALLPAPER_PATH="$ROOT_DIR/eye/media/desktop.jpg"

if [ ! -f "$WALLPAPER_PATH" ]; then
    echo "Wallpaper not found: $WALLPAPER_PATH"
    exit 1
fi

pcmanfm --set-wallpaper "$WALLPAPER_PATH"
echo "Desktop background set to $WALLPAPER_PATH"


# Set taskbar to autohide:
CONFIG_DIR="$HOME/.config/wf-panel-pi"
CONFIG_FILE="$CONFIG_DIR/wf-panel-pi.ini"

mkdir -p "$CONFIG_DIR"

cat > "$CONFIG_FILE" <<EOF
[panel]
autohide=true
autohide_duration=500
EOF
echo "Taskbar set to autohide. Only visible using physical mouse."


# Configure ethernet with static IP:
IP_LAST_OCTET=$((200 + EYE_ID))
ETH_IP="192.168.1.${IP_LAST_OCTET}/24"

# Find the active Ethernet connection name
ETH_CON="$(nmcli -t -f NAME,DEVICE con show --active | grep ':eth0$' | cut -d: -f1)"

# Fallback: first wired connection if not active yet
if [ -z "$ETH_CON" ]; then
    ETH_CON="$(nmcli -t -f NAME,TYPE con show | grep ':ethernet$' | cut -d: -f1 | head -n1)"
fi

if [ -z "$ETH_CON" ]; then
    echo "No Ethernet connection found for eth0"
    exit 1
fi

# Configure static IP without affecting Wi-Fi
nmcli con mod "$ETH_CON" \
    ipv4.method manual \
    ipv4.addresses "$ETH_IP" \
    ipv4.gateway "" \
    ipv4.dns "" \
    ipv4.never-default yes

nmcli con up "$ETH_CON"
echo "Ethernet IP set to $ETH_IP"




# Complete
echo "Setup complete."
