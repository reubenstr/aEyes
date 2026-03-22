#!/usr/bin/env bash
set -u

SRC="/home/$USER/Desktop/projects/aEyes/eye/"
DST="/home/eye/aEyes/eye/"

HOSTS=(
	eye1.local
	eye2.local
	eye3.local
	eye4.local
	eye5.local
	eye6.local
)

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
	DRY_RUN=true
	echo "Dry run mode — no changes will be made"
fi

for h in "${HOSTS[@]}"; do

	echo -n "Syncing to $h... "

	EXCLUDES=(
		--exclude='.git/'
		--exclude='.venv/'
		--exclude='.env'
		--exclude='.motors-zeroed'
	)
	RSYNC_OPTS=(-az --delete "${EXCLUDES[@]}")
	$DRY_RUN && RSYNC_OPTS+=(--dry-run)

	if $DRY_RUN; then
		rsync "${RSYNC_OPTS[@]}" "$SRC" "eye@$h:$DST"
	else
		rsync "${RSYNC_OPTS[@]}" "$SRC" "eye@$h:$DST" >/dev/null
	fi

	RC=$?
	if [[ $RC -ne 0 ]]; then
		echo "ERROR (exit $RC)"
	else
		echo "OK"
	fi
done
