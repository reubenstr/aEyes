#!/usr/bin/env bash
set -u

SRC_HOST="eye1.local"
SRC="/home/eye/aEyes/eye/"
DST="/home/$USER/Desktop/projects/aEyes/eye/"

echo "Pulling eye code from $SRC_HOST..."

EXCLUDES=(
	--exclude='.git/'
	--exclude='.venv/'
	--exclude='.env'
	--exclude='.motors-zeroed'
)

rsync -az "${EXCLUDES[@]}" "eye@$SRC_HOST:$SRC" "$DST"

RC=$?
if [[ $RC -ne 0 ]]; then
	echo "ERROR (exit $RC)"
else
	echo "OK"
fi
