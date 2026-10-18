#!/usr/bin/env bash
set -euo pipefail

UI_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
DEPLOY_DIR="/var/www/aeyes"

if [ "$(id -u)" -eq 0 ]; then
    echo "Run ./deploy.sh without sudo; only the deployment copy requires sudo." >&2
    exit 1
fi

for command_name in node yarn rsync sudo; do
    if ! command -v "$command_name" >/dev/null; then
        echo "Missing command: $command_name. Install the frontend/system dependencies first." >&2
        exit 1
    fi
done

if [ "$(node -p 'process.versions.node.split(".")[0]')" != 24 ] || \
   [ "$(yarn --version)" != 1.22.22 ]; then
    echo "Node 24 and Yarn 1.22.22 are required, as in controller/install.sh." >&2
    exit 1
fi

cd -- "$UI_DIR"
yarn build
sudo install -d -m 0755 "$DEPLOY_DIR"
sudo rsync -r --delete --chmod=D755,F644 "$UI_DIR/dist/" "$DEPLOY_DIR/"
echo "Dashboard deployed to $DEPLOY_DIR. Refresh the browser to load the update."
