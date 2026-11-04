#!/usr/bin/env bash
# Start the pinned Switch stack (postgres, switch-core, Mattermost, gateway).
# The desk container is a separate step so seed.py can create demo users first.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
bash "$ROOT/scripts/get-switch.sh"

if ! docker info >/dev/null 2>&1; then
  echo "docker daemon is not up; starting dockerd"
  sudo mkdir -p /etc/docker
  if [[ ! -f /etc/docker/daemon.json ]]; then
    printf '%s\n' '{' '  "storage-driver": "fuse-overlayfs"' '}' | sudo tee /etc/docker/daemon.json >/dev/null
  fi
  sudo dockerd >/tmp/dockerd.log 2>&1 &
  for _ in $(seq 1 30); do
    docker info >/dev/null 2>&1 && break
    sleep 1
  done
  docker info >/dev/null
fi

if [[ ! -f "$ROOT/.env" ]]; then
  python3 - <<'PY'
import secrets, string
from pathlib import Path
alphabet = string.ascii_letters + string.digits
def pw() -> str:
    return "A1a" + "".join(secrets.choice(alphabet) for _ in range(20))
values = {
    "SWITCH_REGISTRY": "ghcr.io",
    "SWITCH_IMAGE_NAMESPACE": "sandbox-quantum",
    "SWITCH_VERSION": "0.31.0",
    "GATEWAY_HOST_PORT": "3000",
    "API_HOST_PORT": "8000",
    "MATTERMOST_HOST_PORT": "8065",
    "POSTGRES_HOST_PORT": "5432",
    "SWITCH_BIND_ADDR": "127.0.0.1",
    "DB_USER": "switch_app",
    "DB_PASSWORD": secrets.token_hex(24),
    "DB_OWNER_USER": "postgres",
    "DB_OWNER_PASSWORD": secrets.token_hex(24),
    "DB_NAME": "switch",
    "AGENT_REGISTRATION_TOKEN": secrets.token_hex(24),
    "SECRET_KEYS": "k1:" + secrets.token_urlsafe(48),
    "GATEWAY_ADMIN_EMAIL": "admin@switch.local",
    "GATEWAY_ADMIN_PASSWORD": pw(),
    "FRONTEND_BASE_URL": "http://localhost:3000",
    "GATEWAY_PUBLIC_URL": "http://127.0.0.1:8000",
    "MATTERMOST_ADMIN_USER": "admin",
    "MATTERMOST_ADMIN_PASSWORD": pw(),
    "MATTERMOST_TEAM_NAME": "switch",
    "MATTERMOST_USER": "user",
    "MATTERMOST_USER_PASSWORD": pw(),
    "MAYA_PASSWORD": pw(),
    "SAM_PASSWORD": pw(),
    "TELEMETRY_ENABLED": "false",
    "TELEMETRY_ENVIRONMENT": "local",
    "OUTBOUND_ALLOWED_PRIVATE_HOSTS": "localhost",
    "ID_SERVER_NAME": "localhost",
    "LLM_MODE": "rules",
    "ROOM_NAME": "club-finance",
    "ROOM_USERS": "user,maya,sam",
    "TREASURER_USERNAMES": "user",
    "DESK_SYNC_POLICY": "seed",
}
lines = [f"{key}={value}" for key, value in values.items()]
Path(".env").write_text("\n".join(lines) + "\n")
print("wrote .env with generated secrets (not printed)")
PY
fi

mkdir -p "$ROOT/.state"
# A developer shell may already have exported an older .env. Compose lets
# those beat --env-file, which silently boots the stack with the wrong secrets.
while IFS= read -r line; do
  [[ "$line" == *=* && "$line" != \#* ]] || continue
  unset "${line%%=*}"
done < "$ROOT/.env"
COMPOSE=(docker compose --env-file "$ROOT/.env" -p treasurer-desk
  -f "$ROOT/.switch/standalone-docker-compose.yml"
  -f "$ROOT/deploy/docker-compose.override.yml"
  --profile collab --profile gateway)
"${COMPOSE[@]}" up -d
echo "waiting for Switch /health and Mattermost"
for _ in $(seq 1 90); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null && curl -sf http://127.0.0.1:8065/api/v4/system/ping >/dev/null; then
    status="$(docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' treasurer-desk-setup-1 2>/dev/null || true)"
    if [[ "$status" == "exited 0" ]]; then
      echo "switch stack is up"
      exit 0
    fi
  fi
  sleep 2
done
echo "timed out waiting for the Switch stack" >&2
docker compose -p treasurer-desk logs --tail 80 setup switch mattermost || true
exit 1
