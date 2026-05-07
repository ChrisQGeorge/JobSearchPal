# Custom Caddy image that bakes openssl + an init script for
# generating a self-signed TLS cert at container startup. We do this
# instead of relying on Caddy's `tls internal { on_demand }` because
# on-demand issuance depends on the api container being reachable
# from caddy via /health, and any hiccup in that chain (slow boot
# order, network policy, hostname resolution) breaks the TLS
# handshake itself with ERR_SSL_PROTOCOL_ERROR rather than a clean
# 5xx. A pre-generated static cert removes that whole failure mode.
#
# Cert SANs are baked from the CADDY_HOSTNAME env var (set in .env);
# defaults cover localhost / *.local / the running container's IP.
# The browser will still warn the first time — accept the warning, or
# import the generated cert into your client's trust store.

FROM caddy:2-alpine
RUN apk add --no-cache openssl
COPY entrypoint.sh /usr/local/bin/jsp-caddy-entrypoint.sh
RUN chmod +x /usr/local/bin/jsp-caddy-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/jsp-caddy-entrypoint.sh"]
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
