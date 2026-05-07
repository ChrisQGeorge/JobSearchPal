#!/bin/sh
# Generate a self-signed TLS cert at container startup if one
# doesn't already exist in the persistent caddy_data volume. Caddy
# then serves it via the static `tls /path /path` directive in the
# Caddyfile — no on-demand issuance, no api dependency, no chance
# of a TLS handshake failure due to cert-pipeline hiccups.
#
# CADDY_HOSTNAME (set in .env) is added to the cert's subjectAltName
# so the user's chosen hostname / IP is covered. Defaults include
# localhost, *.local, the docker network's chromium/web service names,
# and a wildcard *.lan for general LAN use.
set -eu

CERT_DIR="/data/jsp-tls"
CERT_PEM="$CERT_DIR/cert.pem"
KEY_PEM="$CERT_DIR/key.pem"

mkdir -p "$CERT_DIR"

if [ ! -s "$CERT_PEM" ] || [ ! -s "$KEY_PEM" ]; then
  HOSTNAME="${CADDY_HOSTNAME:-jobsearchpal.local}"
  echo "[jsp-caddy] generating self-signed cert for CN=$HOSTNAME ..." >&2

  # Build a SAN list from common defaults plus whatever the user set.
  # Adding both DNS and IP entries because users on LAN deployments
  # typically reach the box by IP.
  SAN="DNS:localhost,DNS:*.local,DNS:*.lan,DNS:web,DNS:chromium,DNS:$HOSTNAME,IP:127.0.0.1"

  # Append any extra SANs from CADDY_EXTRA_SANS — comma-separated, in
  # the same `DNS:foo,IP:1.2.3.4` shape. Lets the user add their
  # server's public IP without rebuilding.
  if [ -n "${CADDY_EXTRA_SANS:-}" ]; then
    SAN="$SAN,$CADDY_EXTRA_SANS"
  fi

  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -keyout "$KEY_PEM" -out "$CERT_PEM" \
    -subj "/CN=$HOSTNAME" \
    -addext "subjectAltName=$SAN" \
    -addext "extendedKeyUsage=serverAuth" \
    >/dev/null 2>&1

  chmod 600 "$KEY_PEM"
  echo "[jsp-caddy] cert ready: $CERT_PEM" >&2
fi

exec "$@"
