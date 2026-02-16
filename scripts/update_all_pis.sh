#!/usr/bin/env bash
set -euo pipefail

# Updates all remote RPi's project repo.
# Execute from central hub (main compute).

USER_NAME="pi"

HOSTS=(
  192.168.1.201
  192.168.1.202
  192.168.1.203
  192.168.1.204
  192.168.1.205
  192.168.1.206
)

REPO_DIR_REL="src/PROJECT"
BRANCH="main"

MAIN_HOST=192.168.1.10
MAIN_USER="pi"
MIRROR_REPO_PATH="~/git-remotes/PROJECT.git"
REMOTE_URL="${MAIN_USER}@${MAIN_HOST}:${MIRROR_REPO_PATH}"

PING_TIMEOUT_SECS=1
SSH_TIMEOUT_SECS=5

OK=()
OFFLINE=()
FAILED=()

for HOST in "${HOSTS[@]}"; do
  TARGET="${USER_NAME}@${HOST}"
  echo -n "Updating $HOST... "

  # Check if remote is online
  if ! ping -c 1 -W "$PING_TIMEOUT_SECS" "$HOST" >/dev/null 2>&1; then
    echo "OFFLINE"
    OFFLINE+=("$HOST")
    continue
  fi

  # Check if remote has ssh connectivity
  if ! ssh -o BatchMode=yes -o ConnectTimeout="$SSH_TIMEOUT_SECS" "$TARGET" "true" >/dev/null 2>&1; then
    echo "OFFLINE/UNREACHABLE"
    OFFLINE+=("$HOST")
    continue
  fi

  # Check if repo directory exists
  if ! ssh "$TARGET" "[ -d \"\$HOME/$REPO_DIR_REL\" ]"; then
    # Clone if missing
    if ssh "$TARGET" "mkdir -p \"\$HOME/src\" && git clone \"$REMOTE_URL\" \"\$HOME/$REPO_DIR_REL\""; then
      echo "CLONED"
      OK+=("$HOST")
    else
      echo "FAILED (clone)"
      FAILED+=("$HOST")
    fi
    continue
  fi

  # Check if directory is a git repo
  if ! ssh "$TARGET" "[ -d \"\$HOME/$REPO_DIR_REL/.git\" ]"; then
    echo "FAILED (not a git repo)"
    FAILED+=("$HOST")
    continue
  fi

  # Force update existing repo
  if ssh "$TARGET" "cd \"\$HOME/$REPO_DIR_REL\" && \
        git fetch origin && \
        git checkout $BRANCH && \
        git reset --hard origin/$BRANCH && \
        git clean -fd"; then
    echo "OK"
    OK+=("$HOST")
  else
    echo "FAILED (update)"
    FAILED+=("$HOST")
  fi

done

echo
echo "===== SUMMARY ====="
echo "OK (${#OK[@]}):      ${OK[*]:-none}"
echo "OFFLINE (${#OFFLINE[@]}): ${OFFLINE[*]:-none}"
echo "FAILED (${#FAILED[@]}):  ${FAILED[*]:-none}"
