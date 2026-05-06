# Custom chromium image that disables the KasmVNC HTTP Basic auth gate
# so the /browser iframe loads cleanly without prompting the user for a
# password. The Job Search Pal api still gates /browser via its cookie
# auth, so this just removes the second layer (which was redundant for
# a single-user deployment and showed up as an annoying browser popup
# inside the iframe).
#
# linuxserver/chromium uses s6-overlay v3. The image scans
# /custom-cont-init.d/ at startup and runs every executable script
# there before launching its services. Our script sed-removes the
# `auth_basic` and `auth_basic_user_file` directives from the nginx
# site config so requests pass through.

FROM lscr.io/linuxserver/chromium:latest

# s6-overlay's init.d hook: scripts here run before nginx starts, so
# the config edit lands before the first request.
COPY disable-auth.sh /custom-cont-init.d/10-disable-auth.sh
RUN chmod +x /custom-cont-init.d/10-disable-auth.sh
