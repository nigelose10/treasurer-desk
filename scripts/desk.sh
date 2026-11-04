#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p "$ROOT/.state"
while IFS= read -r line; do
  [[ "$line" == *=* && "$line" != \#* ]] || continue
  unset "${line%%=*}"
done < "$ROOT/.env"
docker compose --env-file "$ROOT/.env" -p treasurer-desk \
  -f "$ROOT/.switch/standalone-docker-compose.yml" \
  -f "$ROOT/deploy/docker-compose.override.yml" \
  --profile collab --profile gateway --profile desk up -d --build desk
echo "desk container starting"
