#!/usr/bin/env bash
# One-time VPS setup (Ubuntu/Debian). The repo is private, so clone it with a deploy key first:
#   git clone git@github.com:<owner>/<repo>.git && cd <repo> && bash deploy/setup-vps.sh
set -euo pipefail

if ! command -v docker >/dev/null; then
  echo ">> Installing Docker"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  echo ">> Docker installed. Log out and back in once, then re-run this script."
  exit 0
fi

if [ ! -f .env ]; then
  cp .env.example .env
  TOKEN=$(openssl rand -hex 24)
  sed -i "s/^WA_GATEWAY_TOKEN=.*/WA_GATEWAY_TOKEN=$TOKEN/" .env
  echo ">> Created .env (random WA_GATEWAY_TOKEN set). Edit it now: nano .env"
  echo "   then re-run: bash deploy/setup-vps.sh"
  exit 0
fi

# Firewall: only SSH + web
if command -v ufw >/dev/null; then
  sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
  sudo ufw --force enable
fi

docker compose up -d --build
docker compose ps
echo
echo ">> Dashboard is up. Open it, go to 'Ringkasan & Kirim' and scan the WhatsApp QR once."
echo ">> Logs: docker compose logs -f wa scheduler"
