#!/usr/bin/env bash
set -euo pipefail

cd /app

echo "[start] Running DB migrations..."
alembic upgrade head

echo "[start] Launching API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
