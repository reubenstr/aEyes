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

LOCAL_HOST="$(hostname -s)"

for h in "${HOSTS[@]}"; do

	echo -n "Shutting down $h... "

	if [[ "$h" == "$LOCAL_HOST" ]]; then
		echo "skipping (self)"
		continue
	fi

	ERR=$(ssh -o ConnectTimeout=1 -o BatchMode=yes "eye@$h" "sudo shutdown now" 2>&1)
	if [[ $? -ne 0 ]]; then
		echo "failed — ${ERR}"
	else
		echo "success"
	fi

done
