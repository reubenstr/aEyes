#!/usr/bin/env bash

#
# Pulls eye code from the target eye and overwrites the local project's eye code.
# Allows to develop code directly on a eye and pull changes for git commit.
#

set -u

SRC_HOST="eye1.local"
SRC="/home/eye/aEyes/eye/"

# DEV PC
DST="/home/$USER/Desktop/projects/aEyes/eye/"

# RPI
# DST="/home/$USER/aEyes/eye/"

echo "Pulling eye code from $SRC_HOST..."

EXCLUDES=(
	--exclude='.git/'
	--exclude='.venv/'
	--exclude='.env'
	--exclude='.motors-zeroed'
	--exclude='__pycache__/'
	--exclude='*.pyc'
)

rsync -az "${EXCLUDES[@]}" "eye@$SRC_HOST:$SRC" "$DST"

RC=$?
if [[ $RC -ne 0 ]]; then
	echo "ERROR (exit $RC)"
else
	echo "OK"
fi
