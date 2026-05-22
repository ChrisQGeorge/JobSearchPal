#!/usr/bin/env bash
set -euo pipefail

cd /app

echo "[start] Running DB migrations..."
alembic upgrade head

# Expose project skills to the container's Claude Code config volume so
# `claude -p` can auto-discover them. The skills/ tree is bind-mounted read-
# only at /app/skills; we symlink each entry (e.g. /app/skills/resume-tailor)
# into /root/.claude/skills/<name>. Idempotent — symlink -f updates each turn.
if [[ -d /app/skills ]]; then
  mkdir -p /root/.claude/skills
  for d in /app/skills/*/; do
    [[ -d "$d" ]] || continue
    name=$(basename "$d")
    ln -sfn "$d" "/root/.claude/skills/$name"
  done
  echo "[start] Linked $(ls -1 /root/.claude/skills/ 2>/dev/null | wc -l) project skills into ~/.claude/skills"
fi

echo "[start] Launching API..."
# --timeout-keep-alive=60: the Next.js proxy holds keepalive sockets to api in
# Node's HTTP agent and reuses them. uvicorn's default 5 s close means the
# agent often grabs a socket the server already discarded → ECONNRESET on the
# next reuse. 60 s matches Node's typical default and stops the cascading
# socket-hang-up errors on the tracker page.
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --timeout-keep-alive 60
