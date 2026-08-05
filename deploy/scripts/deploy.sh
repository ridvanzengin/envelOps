#!/usr/bin/env bash
# deploy.sh -- pull latest code, rebuild images, run migrations, restart
# app services. Does NOT touch the shared infra project (db/redis/nginx
# stay up). Run from: /opt/envelops
set -euo pipefail

cd /opt/envelops

COMPOSE="docker compose -p envelops --env-file deploy/envelops/.env.prod -f deploy/envelops/docker-compose.prod.yml"

echo "[deploy] Pulling latest code..."
git pull

echo "[deploy] Building images..."
$COMPOSE build

echo "[deploy] Running migrations..."
$COMPOSE run --rm migrate

echo "[deploy] Restarting app services..."
$COMPOSE up -d --no-deps backend worker beat frontend

# The shared nginx serves iotops.online/agritwin.online live too -- only
# touch it, and only reload, when this repo's own vhost source actually
# changed. A bad config must never make it past `nginx -t` into a reload.
NGINX_SRC="deploy/nginx/envelops.conf"
NGINX_DST="/opt/agritwin/deploy/infra/nginx/conf.d/envelops.conf"
if ! cmp -s "$NGINX_SRC" "$NGINX_DST" 2>/dev/null; then
  echo "[deploy] nginx vhost changed, updating..."
  cp "$NGINX_DST" "${NGINX_DST}.bak" 2>/dev/null || true
  cp "$NGINX_SRC" "$NGINX_DST"
  if docker exec infra-nginx-1 nginx -t; then
    docker exec infra-nginx-1 nginx -s reload
    echo "[deploy] nginx reloaded."
  else
    echo "[deploy] nginx -t FAILED -- reverting, not reloading." >&2
    [ -f "${NGINX_DST}.bak" ] && mv "${NGINX_DST}.bak" "$NGINX_DST"
    exit 1
  fi
else
  echo "[deploy] nginx vhost unchanged, skipping."
fi

echo "[deploy] Done."
$COMPOSE ps
