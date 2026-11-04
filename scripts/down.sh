#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ ! -f .switch/standalone-docker-compose.yml ]]; then
  echo "no compose file downloaded; nothing to stop"
  exit 0
fi
if [[ -f "$ROOT/.env" ]]; then
  while IFS= read -r line; do
    [[ "$line" == *=* && "$line" != \#* ]] || continue
    unset "${line%%=*}"
  done < "$ROOT/.env"
fi
FLAGS=()
if [[ "${1:-}" == "--volumes" ]]; then
  FLAGS+=(--volumes)
fi
docker compose --env-file "$ROOT/.env" -p treasurer-desk \
  -f "$ROOT/.switch/standalone-docker-compose.yml" \
  -f "$ROOT/deploy/docker-compose.override.yml" \
  --profile collab --profile gateway --profile desk down "${FLAGS[@]}"
