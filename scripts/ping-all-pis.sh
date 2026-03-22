#!/usr/bin/env bash
set -u

HOSTNAMES=(
	eye1.local
	eye2.local
	eye3.local
	eye4.local
	eye5.local
	eye6.local
)

IPS=(
	192.168.5.101
	192.168.5.102
	192.168.5.103
	192.168.5.104
	192.168.5.105
	192.168.5.106
)

USE_IP=false
if [[ "${1:-}" == "--ip" ]]; then
	USE_IP=true
fi

if $USE_IP; then
	HOSTS=("${IPS[@]}")
else
	HOSTS=("${HOSTNAMES[@]}")
fi

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
