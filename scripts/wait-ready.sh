#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "waiting for .state/ready"
for _ in $(seq 1 90); do
  if [[ -f "$ROOT/.state/ready" ]]; then
    echo "desk ready: $(cat "$ROOT/.state/ready")"
    exit 0
  fi
  sleep 2
done
echo "desk did not become ready" >&2
docker logs treasurer-desk-desk-1 --tail 120 >&2 || true
exit 1
