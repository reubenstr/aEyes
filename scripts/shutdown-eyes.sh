#!/usr/bin/env bash

set -u

HOSTS=(
    eye1.local
    eye2.local
    eye3.local
    eye4.local
    eye5.local
    eye6.local
)

REBOOT=false

if [[ "${1:-}" == "--reboot" ]]; then
    REBOOT=true
    echo "Issuing reboot instead of shutdown"
fi

LOCAL_HOST="$(hostname -s)"

for h in "${HOSTS[@]}"; do
    ACTION="Shutting down"
    $REBOOT && ACTION="Rebooting"

    echo -n "$ACTION $h... "

    if [[ "$h" == "$LOCAL_HOST" ]]; then
        echo "skipping (self)"
        continue
    fi

    CMD="sudo shutdown now"
    $REBOOT && CMD="sudo shutdown -r now"

    ERR=$(ssh \
        -i /home/aeyes/.ssh/id_ed25519 \
        -o StrictHostKeyChecking=accept-new \
        -o ConnectTimeout=1 \
        -o BatchMode=yes \
        -o IdentitiesOnly=yes \
        "eye@$h" "$CMD" 2>&1)

    if [[ $? -ne 0 ]]; then
        echo "failed — ${ERR}"
    else
        echo "success"
    fi
done
