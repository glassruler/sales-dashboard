#!/usr/bin/env bash
# One-time setup on a Debian/Ubuntu server that already runs Nginx.
# Run from the project folder as root:  bash deploy/setup-vps.sh
set -euo pipefail
cd "$(dirname "$0")/.."

DOMAIN="${DOMAIN:-duakelinci.webbros.my.id}"
# Port precedence: command line (APP_PORT=8506 bash ...) > .env > 8501
if [ -z "${APP_PORT:-}" ] && [ -f .env ]; then
  APP_PORT="$(grep -E '^APP_PORT=' .env | tail -1 | cut -d= -f2 | tr -d '[:space:]')"
fi
APP_PORT="${APP_PORT:-8501}"
echo ">> Using APP_PORT=$APP_PORT"

# 1. Docker
if ! command -v docker >/dev/null; then
  echo ">> Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi

# 2. .env with random secrets (only the first time)
if [ ! -f .env ]; then
  cp .env.example .env
  sed -i "s/^WA_GATEWAY_TOKEN=.*/WA_GATEWAY_TOKEN=$(openssl rand -hex 24)/" .env
  sed -i "s/^APP_PASSWORD=.*/APP_PASSWORD=$(openssl rand -base64 12 | tr -d '/+=')/" .env
  sed -i "s/^APP_PORT=.*/APP_PORT=$APP_PORT/" .env
  echo ">> Created .env. Dashboard password: $(grep ^APP_PASSWORD= .env | cut -d= -f2)"
  echo "   Add your AI / Telegram / WhatsApp settings any time with: nano .env"
fi

# 3. The port must be free
if ss -ltn | grep -q ":$APP_PORT "; then
  if ! docker compose ps --status running 2>/dev/null | grep -q app; then
    echo "!! Port $APP_PORT is already used by something else. Set APP_PORT=xxxx in .env and"
    echo "   in deploy/nginx-duakelinci.conf, then re-run."
    exit 1
  fi
fi

# 4. Start app + scheduler + WhatsApp gateway
docker compose up -d --build
docker compose ps

# 5. Nginx site (skipped if a panel manages Nginx and sites-available does not exist)
if [ -d /etc/nginx/sites-available ]; then
  sed "s/8501/$APP_PORT/; s/duakelinci.webbros.my.id/$DOMAIN/" deploy/nginx-duakelinci.conf \
    > /etc/nginx/sites-available/duakelinci.conf
  ln -sf /etc/nginx/sites-available/duakelinci.conf /etc/nginx/sites-enabled/duakelinci.conf
  nginx -t && systemctl reload nginx
  echo ">> Nginx site enabled for $DOMAIN"
  if ! command -v certbot >/dev/null; then
    apt-get update -qq && apt-get install -y -qq certbot python3-certbot-nginx
  fi
  echo ">> For HTTPS run:  certbot --nginx -d $DOMAIN"
else
  echo ">> /etc/nginx/sites-available not found (panel-managed Nginx?)."
  echo "   Add a reverse proxy for $DOMAIN -> http://127.0.0.1:$APP_PORT with WebSocket enabled."
fi

echo
echo ">> Local check: curl -s http://127.0.0.1:$APP_PORT/_stcore/health  (should print: ok)"
echo ">> Logs:        docker compose logs -f"
