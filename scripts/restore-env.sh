#!/usr/bin/env bash
set -u

for i in $(seq 1 6); do
	h="eye$i.local"
	echo -n "Restoring .env on $h... "

	ERR=$(ssh -o ConnectTimeout=3 -o BatchMode=yes "eye@$h" \
		"echo 'EYE_ID=$i' > /home/eye/aEyes/eye/.env" 2>&1)
	if [[ $? -ne 0 ]]; then
		echo "failed — ${ERR}"
	else
		echo "OK"
	fi
done
