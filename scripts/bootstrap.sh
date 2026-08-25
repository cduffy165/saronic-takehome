#!/usr/bin/env bash
# One-command bring-up: creates .env and the Streamlit secrets file from the
# checked-in examples if they don't exist yet, starts the whole stack, mints
# a Gitea access token and stores it, then runs migrations and the registry
# seed inside the api container. Docker is the only host requirement — no
# local Python/uv install is needed to run this. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."

wait_healthy() {
  local service="$1"
  local attempts=0
  until [ "$(docker compose ps --format '{{.Health}}' "$service" 2>/dev/null)" = "healthy" ]; do
    attempts=$((attempts + 1))
    if [ "$attempts" -gt 60 ]; then
      echo "$service did not become healthy in time — check 'docker compose logs $service'." >&2
      exit 1
    fi
    sleep 2
  done
}

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example."
fi

if [ ! -f .streamlit/secrets.toml ]; then
  cp .streamlit/secrets.toml.example .streamlit/secrets.toml
  echo "Created .streamlit/secrets.toml from its example (dev-only values)."
fi

if ! grep -q '^ANTHROPIC_API_KEY=sk-' .env; then
  echo "Set a real ANTHROPIC_API_KEY in .env, then re-run this script." >&2
  exit 1
fi

echo "Starting postgres, keycloak, gitea, api, and ui (this builds images on first run)..."
docker compose up -d --build

echo "Waiting for Gitea..."
wait_healthy gitea

echo "Creating the Gitea service account and minting an access token..."
docker compose exec -T --user git gitea gitea admin user create \
  --username factory --password "${GITEA_PASSWORD:-factory-dev-password}" \
  --email factory@localhost --admin --must-change-password=false >/dev/null 2>&1 || true

TOKEN=$(docker compose exec -T --user git gitea gitea admin user generate-access-token \
  --username factory --token-name "factory-api-$(date +%s)" \
  --scopes write:repository,write:user --raw)

if [ -z "$TOKEN" ]; then
  echo "Could not mint a Gitea access token — check 'docker compose logs gitea'." >&2
  exit 1
fi

if grep -q '^GITEA_TOKEN=' .env; then
  sed -i.bak "s|^GITEA_TOKEN=.*|GITEA_TOKEN=${TOKEN}|" .env && rm -f .env.bak
else
  echo "GITEA_TOKEN=${TOKEN}" >>.env
fi

echo "Restarting api with the new Gitea token..."
docker compose up -d api
wait_healthy api

echo "Running database migrations and loading the registry seed..."
docker compose exec -T api uv run alembic upgrade head
docker compose exec -T api uv run python -m factory.registry.seed

wait_healthy ui

cat <<'MSG'

Everything is up:
  UI        http://localhost:8501   (log in as alice/alice, bob/bob, carol/carol, or dave/dave)
  API       http://localhost:8000/health
  Keycloak  http://auth.localhost:8080  (admin/admin)
  Gitea     http://localhost:3000       (factory / factory-dev-password, unless GITEA_PASSWORD was set)

If your browser doesn't resolve auth.localhost on its own, add
"127.0.0.1 auth.localhost" to your hosts file.
MSG
