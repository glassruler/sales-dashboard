#!/usr/bin/env bash
# Pull the latest code and rebuild. Data (./data), WhatsApp session and certificates are kept.
set -euo pipefail
git pull --ff-only
docker compose up -d --build
docker image prune -f >/dev/null
docker compose ps
