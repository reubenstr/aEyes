#!/bin/bash
set -e

PIS=(
  192.168.1.201
  192.168.1.202
  192.168.1.203
  192.168.1.204
  192.168.1.205
  192.168.1.206
)

LOCAL_USER="$USER"
REMOTE_USER="pi"

SRC="/home/$LOCAL_USER/aEyes/"
DST="/home/$REMOTE_USER/aEyes/"

for PI in "${PIS[@]}"; do
    echo "Deploying to $PI..."
    rsync -av --delete --exclude='.git' \
      "$SRC" "$REMOTE_USER@$PI:$DST"
done