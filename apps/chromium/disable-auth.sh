#!/usr/bin/env bash
# Strip the auth_basic / auth_basic_user_file lines from KasmVNC's
# nginx site config so the iframe in /browser doesn't prompt for a
# password. Job Search Pal's api adds its own cookie-auth gate on the
# /browser page, so this removes a redundant second layer.
#
# Idempotent — re-running on a config that's already been edited is
# a no-op.

set -euo pipefail

CONF=/etc/nginx/sites-enabled/default

if [ ! -f "$CONF" ]; then
  echo "[disable-auth] $CONF not found yet; skipping." >&2
  exit 0
fi

if grep -q "auth_basic" "$CONF"; then
  sed -i '/auth_basic[[:space:]]/d; /auth_basic_user_file[[:space:]]/d' "$CONF"
  echo "[disable-auth] auth_basic stripped from nginx config." >&2
else
  echo "[disable-auth] nothing to do; auth_basic already absent." >&2
fi
