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

echo "WiFi control for all RPis"
echo "  1) Enable WiFi"
echo "  2) Disable WiFi"
echo -n "Choose [1/2]: "
read -r choice

case "$choice" in
	1)
		ACTION="on"
		ACTION_LABEL="Enabling"
		;;
	2)
		ACTION="off"
		ACTION_LABEL="Disabling"
		;;
	*)
		echo "Invalid choice. Exiting."
		exit 1
		;;
esac

for h in "${HOSTS[@]}"; do

	echo -n "$ACTION_LABEL WiFi on $h... "

	ERR=$(ssh -o ConnectTimeout=3 -o BatchMode=yes "eye@$h" "sudo timeout 5 nmcli radio wifi $ACTION" 2>&1)
	RC=$?
	if [[ $RC -ne 0 ]]; then
		echo "failed — ${ERR}"
	else
		echo "success"
	fi

done
