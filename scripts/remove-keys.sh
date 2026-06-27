#!/usr/bin/env bash
set -euo pipefail

HOSTS=(
    eye1.local
    eye2.local
    eye3.local
    eye4.local
    eye5.local
    eye6.local
)

echo "Removing SSH known_hosts entries for eye*.local..."

for h in "${HOSTS[@]}"; do
    ssh-keygen -R "$h" >/dev/null 2>&1 || true
done

echo "Done removing host keys."

echo ""
echo "Optional: also removing IP-based entries (mDNS sometimes resolves to IPs)..."

for h in "${HOSTS[@]}"; do
    ip=$(getent hosts "$h" | awk '{print $1}' || true)
    if [[ -n "${ip:-}" ]]; then
        ssh-keygen -R "$ip" >/dev/null 2>&1 || true
    fi
done

echo ""
echo "SSH trust reset complete."