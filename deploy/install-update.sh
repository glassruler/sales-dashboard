#!/usr/bin/env bash
# Install a new archive uploaded to /tmp, keeping .env, data/ and the WhatsApp session.
# Usage (on the server):  sudo bash /opt/sales-dashboard/deploy/install-update.sh [/tmp/sales-dashboard.tar.gz]
set -euo pipefail

ARCHIVE="${1:-/tmp/sales-dashboard.tar.gz}"
APP_DIR="${APP_DIR:-/opt/sales-dashboard}"
[ -f "$ARCHIVE" ] || { echo "!! Archive not found: $ARCHIVE"; exit 1; }

echo ">> Unpacking $ARCHIVE into $(dirname "$APP_DIR")"
tar -xzf "$ARCHIVE" -C "$(dirname "$APP_DIR")" --exclude='sales-dashboard/data/*'

# The app runs as uid 1000 inside Docker; extracting as root makes data/ root-owned again.
mkdir -p "$APP_DIR/data"
chown -R 1000:1000 "$APP_DIR/data"

cd "$APP_DIR"
docker compose up -d --build
docker image prune -f >/dev/null
docker compose ps
echo ">> Updated. Health: $(curl -s "http://127.0.0.1:$(grep -E '^APP_PORT=' .env | cut -d= -f2 || echo 8501)/_stcore/health" || true)"
