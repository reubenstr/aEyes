#!/usr/bin/env bash
set -u

SRC="/home/you/proj/"
HOSTS=(
	eye1.local
	eye2.local
	eye3.local
	eye4.local
	eye5.local
	eye6.local
	eye7.local
)

LOCAL_HOST="$(hostname -s)"

for h in "${HOSTS[@]}"; do

	echo -n "Syncing to $h... "

	if [[ "$h" == "$LOCAL_HOST" ]]; then
		echo "Skipping (self)"
	fi

	rsync -az --delete \
		--exclude='.git/' \
		"$SRC" "$h:$SRC" >/dev/null 2>&1

	RC=$?
	if [[ $RC -ne 0 ]]; then
		echo "ERROR (exit $RC)"
	else
		echo "OK"
	fi
done
