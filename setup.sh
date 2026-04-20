#!/usr/bin/env bash
# Job Search Pal setup script.
# Generates a .env file with strong random secrets, then brings the stack up.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

ENV_FILE="$REPO_ROOT/.env"
ENV_EXAMPLE="$REPO_ROOT/.env.example"

command_exists() { command -v "$1" >/dev/null 2>&1; }

require() {
  if ! command_exists "$1"; then
    echo "ERROR: '$1' is required but not installed." >&2
    echo "Please install $1 and re-run setup." >&2
    exit 1
  fi
}

gen_secret() {
  # 48 bytes -> 64 base64 chars, url-safe
  if command_exists openssl; then
    openssl rand -base64 48 | tr -d '\n=+/' | cut -c1-48
  else
    LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 48
  fi
}

uninstall() {
  echo "Stopping and removing containers..."
  docker compose down || true
  read -rp "Delete persistent data volumes (DB, uploads)? [y/N]: " yn
  if [[ "${yn,,}" == "y" ]]; then
    docker compose down -v
    echo "Volumes removed."
  fi
  read -rp "Remove .env file? [y/N]: " yn
  if [[ "${yn,,}" == "y" ]]; then
    rm -f "$ENV_FILE"
    echo ".env removed."
  fi
  echo "Uninstall complete."
  exit 0
}

if [[ "${1:-}" == "--uninstall" ]]; then
  uninstall
fi

echo "==> Job Search Pal setup"
require docker

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: 'docker compose' (v2) is required." >&2
  exit 1
fi

if [[ -f "$ENV_FILE" ]]; then
  echo ".env already exists — keeping it. Delete it first if you want fresh secrets."
else
  echo "Generating .env with random secrets..."
  cp "$ENV_EXAMPLE" "$ENV_FILE"

  MYSQL_PASSWORD="$(gen_secret)"
  MYSQL_ROOT_PASSWORD="$(gen_secret)"
  SESSION_SECRET="$(gen_secret)"
  MASTER_SECRET="$(gen_secret)"

  # Portable in-place edit for Linux / macOS.
  sed_i() {
    if [[ "$(uname)" == "Darwin" ]]; then
      sed -i '' "$@"
    else
      sed -i "$@"
    fi
  }

  sed_i "s|^MYSQL_PASSWORD=.*|MYSQL_PASSWORD=${MYSQL_PASSWORD}|" "$ENV_FILE"
  sed_i "s|^MYSQL_ROOT_PASSWORD=.*|MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}|" "$ENV_FILE"
  sed_i "s|^SESSION_SECRET=.*|SESSION_SECRET=${SESSION_SECRET}|" "$ENV_FILE"
  sed_i "s|^MASTER_SECRET=.*|MASTER_SECRET=${MASTER_SECRET}|" "$ENV_FILE"

  chmod 600 "$ENV_FILE"
  echo "Wrote $ENV_FILE (mode 0600)."

  if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    sed_i "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}|" "$ENV_FILE"
    echo "Wrote ANTHROPIC_API_KEY from environment."
  else
    echo ""
    echo "NOTE: after the stack is up, complete the Claude Code OAuth login with:"
    echo "        docker compose exec -it api claude login"
    echo "      (or set ANTHROPIC_API_KEY in $ENV_FILE for pay-per-token API access)"
  fi
fi

echo "==> Building containers..."
docker compose build

echo "==> Starting stack..."
docker compose up -d

echo "==> Waiting for API to become healthy..."
for i in {1..30}; do
  if docker compose exec -T api python -c "import urllib.request as r; r.urlopen('http://127.0.0.1:8000/health')" 2>/dev/null; then
    break
  fi
  sleep 2
done

echo ""
echo "Job Search Pal is up."
echo "  Web:     http://localhost:$(grep -E '^WEB_PORT=' "$ENV_FILE" | cut -d= -f2)"
echo "  API:     http://localhost:$(grep -E '^API_PORT=' "$ENV_FILE" | cut -d= -f2)"
echo ""
echo "To stop:         docker compose down"
echo "To uninstall:    ./setup.sh --uninstall"
