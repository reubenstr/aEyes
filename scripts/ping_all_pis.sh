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

for h in "${HOSTS[@]}"; do
	(
		if ping -c1 -W1 "$h" >/dev/null 2>&1; then
			echo "Pinging $h... reachable"
		else
			echo "Pinging $h... not reachable"
		fi
	) &
done

wait
