#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: sudo ./install.sh [--all]

With no options, choose all components or answer each installation prompt.
  --all       Install/configure every component without prompting.
  -h, --help  Show this help.

Components: system packages, Python dependencies, Node/Yarn and UI dependencies,
dashboard build/deployment, OAK USB access, application services, GPIO shutdown
service, nginx, and Ethernet (192.168.5.100/24).

Python service startup remains manual. nginx is enabled and started/reloaded
when selected. Ethernet changes run last and may interrupt an SSH connection
over Ethernet.
EOF
}

confirm() {
    local answer
    while true; do
        printf '%s [y/N] ' "$1"
        if ! read -r answer; then
            echo ""
            echo "No answer received. Installation cancelled before making changes." >&2
            exit 1
        fi
        case "${answer,,}" in
            y|yes) return 0 ;;
            n|no|'') return 1 ;;
            *) echo "Please answer yes or no." ;;
        esac
    done
}

setup_context() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "Run this script with sudo from the deployment user's account." >&2
        exit 1
    fi
    USER_NAME="${SUDO_USER:-${USER:-root}}"
    if [ "$USER_NAME" = root ]; then
        echo "Run with sudo from the deployment user's account (not a root login)." >&2
        exit 1
    fi
    USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
    ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
    VENV_DIR="$ROOT_DIR/.venv"
    ETH_IP="192.168.5.100/24"
    FRONTEND_PREFIX="/usr/local"
    APT_UPDATED=false
    TASK_TMP=""
}

cleanup() {
    if [ -n "$TASK_TMP" ]; then
        rm -rf -- "$TASK_TMP"
    fi
}

prepare_tmp() {
    if [ -z "$TASK_TMP" ]; then
        TASK_TMP="$(mktemp -d)"
    fi
}

require_commands() {
    local command_name
    for command_name in "$@"; do
        if ! command -v "$command_name" >/dev/null; then
            echo "Missing command: $command_name. Install the relevant dependencies first." >&2
            exit 1
        fi
    done
}

install_packages() {
    if [ "$APT_UPDATED" = false ]; then
        apt update
        APT_UPDATED=true
    fi
    apt install -y "$@"
}

install_system_dependencies() {
    install_packages \
        python3 python3-venv python3-pip python3-lgpio python3-gpiozero \
        curl ca-certificates xz-utils iputils-ping sudo rsync
}

install_python_dependencies() {
    require_commands python3 sudo
    if [ ! -f "$ROOT_DIR/requirements.txt" ]; then
        echo "requirements.txt not found!" >&2
        exit 1
    fi
    if [ ! -x "$VENV_DIR/bin/python" ]; then
        sudo -u "$USER_NAME" python3 -m venv "$VENV_DIR" --system-site-packages
    else
        echo "Using existing virtual environment: $VENV_DIR"
    fi
    sudo -u "$USER_NAME" "$VENV_DIR/bin/python" -m pip install --upgrade pip
    sudo -u "$USER_NAME" "$VENV_DIR/bin/python" -m pip install -r "$ROOT_DIR/requirements.txt"
}

check_frontend_tools() {
    export PATH="$FRONTEND_PREFIX/bin:$PATH"
    require_commands node yarn sudo
    if [ "$(node -p 'process.versions.node.split(".")[0]')" != 24 ] || \
       [ "$(yarn --version)" != 1.22.22 ]; then
        echo "Node 24 and Yarn 1.22.22 are required. Select frontend dependencies first." >&2
        exit 1
    fi
    NODE_BIN="$(dirname -- "$(command -v node)")"
    YARN_BIN="$(command -v yarn)"
}

install_frontend_dependencies() {
    export PATH="$FRONTEND_PREFIX/bin:$PATH"
    require_commands curl python3 dpkg tar sha256sum sudo
    prepare_tmp
    local node_arch node_version node_archive node_tool
    if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" != 24 ]; then
        case "$(dpkg --print-architecture)" in
            arm64) node_arch=arm64 ;;
            amd64) node_arch=x64 ;;
            *) echo "Node 24 requires a supported 64-bit OS (arm64 or amd64)." >&2; exit 1 ;;
        esac
        curl --fail --silent --show-error https://nodejs.org/dist/index.json -o "$TASK_TMP/node-index.json"
        node_version="$(python3 - "$TASK_TMP/node-index.json" <<'PY'
import json, sys
print(next(v['version'] for v in json.load(open(sys.argv[1])) if v['version'].startswith('v24.') and v['lts']))
PY
)"
        node_archive="node-$node_version-linux-$node_arch.tar.xz"
        curl --fail --silent --show-error "https://nodejs.org/dist/$node_version/$node_archive" -o "$TASK_TMP/$node_archive"
        curl --fail --silent --show-error "https://nodejs.org/dist/$node_version/SHASUMS256.txt" -o "$TASK_TMP/SHASUMS256.txt"
        (cd "$TASK_TMP" && awk -v archive="$node_archive" '$2 == archive' SHASUMS256.txt | sha256sum --check --status)
        tar -xJf "$TASK_TMP/$node_archive" -C /opt
        install -d -m 0755 "$FRONTEND_PREFIX/bin"
        for node_tool in node npm npx; do
            ln -sfn "/opt/node-$node_version-linux-$node_arch/bin/$node_tool" "$FRONTEND_PREFIX/bin/$node_tool"
        done
    fi
    NODE_BIN="$(dirname -- "$(command -v node)")"
    if ! command -v yarn >/dev/null || [ "$(yarn --version)" != 1.22.22 ]; then
        # npm otherwise follows Node's /opt prefix, whose bin directory may be
        # absent from both root's and the deployment user's PATH.
        PATH="$NODE_BIN:$PATH" npm install --global --prefix "$FRONTEND_PREFIX" yarn@1.22.22
    fi
    check_frontend_tools
    (cd "$ROOT_DIR/ui" && sudo -u "$USER_NAME" env PATH="$NODE_BIN:$PATH" "$YARN_BIN" install --frozen-lockfile)
}

deploy_dashboard() {
    check_frontend_tools
    require_commands rsync
    (cd "$ROOT_DIR/ui" && sudo -u "$USER_NAME" env PATH="$NODE_BIN:$PATH" "$YARN_BIN" build)
    install -d -m 0755 /var/www/aeyes
    rsync -r --delete --chmod=D755,F644 "$ROOT_DIR/ui/dist/" /var/www/aeyes/
}

configure_oak_usb() {
    require_commands udevadm
    install -d -m 0755 /etc/udev/rules.d
    printf '%s\n' 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' > /etc/udev/rules.d/80-movidius.rules
    udevadm control --reload-rules
    udevadm trigger --subsystem-match=usb
}

install_application_services() {
    require_commands python3 visudo systemctl
    prepare_tmp
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
    systemctl daemon-reload
    echo "Application services installed. Enable/start them when ready:"
    echo "  sudo systemctl enable --now main.service aeyes-monitor.service"
    echo "Install Python dependencies and configure OAK USB access before starting the controller."
}

install_shutdown_service() {
    require_commands systemctl
    prepare_tmp
    # Escape systemd specifiers and quoted paths in the generated unit.
    local service_root service_home
    service_root="${ROOT_DIR//\\/\\\\}"
    service_root="${service_root//\"/\\\"}"
    service_root="${service_root//%/%%}"
    service_home="${USER_HOME//\\/\\\\}"
    service_home="${service_home//\"/\\\"}"
    service_home="${service_home//%/%%}"
    cat > "$TASK_TMP/shutdown.service" <<EOF
[Unit]
Description=Shutdown Service
After=multi-user.target

[Service]
Type=simple
WorkingDirectory="$service_root"
Environment=DISPLAY=:0
Environment="XAUTHORITY=$service_home/.Xauthority"
ExecStart="$service_root/.venv/bin/python" "$service_root/shutdown.py" --service
Restart=on-failure
RestartSec=5s
TimeoutStopSec=10s

[Install]
WantedBy=multi-user.target
EOF
    install -m 0644 "$TASK_TMP/shutdown.service" /etc/systemd/system/shutdown.service
    systemctl daemon-reload
    echo "Shutdown service installed. Enable/start it after installing Python dependencies:"
    echo "  sudo systemctl enable --now shutdown.service"
}

configure_nginx() {
    require_commands systemctl
    install_packages nginx
    install -m 0644 "$ROOT_DIR/deploy/aeyes-nginx.conf" /etc/nginx/sites-available/aeyes
    if [ -L /etc/nginx/sites-enabled/default ] && \
       [ "$(readlink -f /etc/nginx/sites-enabled/default)" = /etc/nginx/sites-available/default ]; then
        rm /etc/nginx/sites-enabled/default
    fi
    ln -sfn /etc/nginx/sites-available/aeyes /etc/nginx/sites-enabled/aeyes
    nginx -t
    # Start nginx if it was stopped; reload an existing server without a restart.
    systemctl enable nginx
    if systemctl is-active --quiet nginx; then
        systemctl reload nginx
    else
        systemctl start nginx
    fi
    echo "Dashboard: http://<controller-ip>/ (requires dashboard deployment and monitoring API)."
}

configure_ethernet() {
    require_commands nmcli
    local eth_con
    # Prefer the eth0 profile, falling back to the first Ethernet connection.
    eth_con="$(nmcli -t -f NAME,DEVICE con show | grep ':eth0$' | cut -d: -f1 || true)"
    if [ -z "$eth_con" ]; then
        eth_con="$(nmcli -t -f NAME,TYPE con show | grep -E ':ethernet$|:802-3-ethernet$' | cut -d: -f1 | head -n1 || true)"
    fi
    if [ -z "$eth_con" ]; then
        echo "No Ethernet connection profile found" >&2
        exit 1
    fi
    echo "Setting $eth_con to $ETH_IP"
    nmcli con mod "$eth_con" \
        ipv4.method manual \
        ipv4.addresses "$ETH_IP" \
        ipv4.gateway "" \
        ipv4.dns "" \
        ipv4.never-default yes \
        ipv4.route-metric 900
    nmcli con up "$eth_con"
}

main() {
    local install_all=false argument step
    for argument in "$@"; do
        case "$argument" in
            --all) install_all=true ;;
            -h|--help) usage; return 0 ;;
            *) echo "Unknown option: $argument" >&2; usage >&2; return 2 ;;
        esac
    done
    setup_context

    local -a steps=(
        install_system_dependencies
        install_python_dependencies
        install_frontend_dependencies
        deploy_dashboard
        configure_oak_usb
        install_application_services
        install_shutdown_service
        configure_nginx
        configure_ethernet
    )
    local -A descriptions=(
        [install_system_dependencies]="Install system packages (Python, GPIO and deployment tools)"
        [install_python_dependencies]="Create/reuse the Python virtual environment and install requirements.txt"
        [install_frontend_dependencies]="Install Node 24, Yarn 1.22.22 and dashboard dependencies"
        [deploy_dashboard]="Build the dashboard and deploy it to /var/www/aeyes"
        [configure_oak_usb]="Configure OAK camera USB access for non-root users"
        [install_application_services]="Install controller/monitor services and the dashboard restart sudo rule"
        [install_shutdown_service]="Install the GPIO shutdown-button service"
        [configure_nginx]="Install/configure and enable/start or reload nginx on port 80"
        [configure_ethernet]="Set Ethernet to 192.168.5.100/24 (may interrupt Ethernet SSH)"
    )
    local -a selected_steps=()
    if [ "$install_all" = false ]; then
        echo "Choose components; skipped steps are left unchanged. Service installation does not start Python services."
        echo "Ethernet changes may interrupt SSH and will run last."
        if confirm "Install/configure all components"; then
            install_all=true
        fi
    fi
    for step in "${steps[@]}"; do
        if [ "$install_all" = true ] || confirm "${descriptions[$step]}"; then
            selected_steps+=("$step")
        fi
    done
    if [ "${#selected_steps[@]}" -eq 0 ]; then
        echo "No steps selected. Nothing changed."
        return 0
    fi

    trap cleanup EXIT
    echo ""
    echo "Selected steps:"
    for step in "${selected_steps[@]}"; do
        printf '  - %s\n' "${descriptions[$step]}"
    done
    for step in "${selected_steps[@]}"; do
        printf '\n%s\n' "${descriptions[$step]}"
        "$step"
    done
    echo ""
    echo "Selected installation/configuration steps complete."
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
