#!/usr/bin/env bash
# Download the pinned Switch compose file. It is not vendored: Switch stays a
# server we talk to, under its own licence.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${SWITCH_VERSION:-0.31.0}"
DEST="$ROOT/.switch"
mkdir -p "$DEST"
URL="https://raw.githubusercontent.com/sandbox-quantum/switch/switch-v${VERSION}/deploy/local/standalone-docker-compose.yml"
TARGET="$DEST/standalone-docker-compose.yml"
if [[ -f "$TARGET" && "${FORCE_SWITCH_DOWNLOAD:-0}" != "1" ]]; then
  echo "using $TARGET"
  exit 0
fi
curl -fsSL "$URL" -o "$TARGET"
echo "downloaded Switch ${VERSION} compose to $TARGET"
