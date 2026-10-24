#!/usr/bin/env bash
# Add (or refresh) Hearth's site block without touching other Caddy sites.
#   caddy-site.sh <domain> [caddy_etc_dir=/etc/caddy]     (run as root; install.sh does this)
# Writes <etc>/Caddyfile.d/hearth.caddy and makes sure <etc>/Caddyfile imports Caddyfile.d/*.caddy.
# The Caddyfile is backed up before any change. Only the package's untouched placeholder
# (":80 { root * /usr/share/caddy; file_server }") is replaced; any real config is appended to.
set -euo pipefail
DOMAIN="${1:?usage: caddy-site.sh <domain> [caddy_etc_dir]}"
ETC="${2:-/etc/caddy}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || { echo "invalid hostname: $DOMAIN" >&2; exit 1; }

SITE_DIR="$ETC/Caddyfile.d"
CF="$ETC/Caddyfile"
IMPORT_LINE="import $SITE_DIR/*.caddy"
mkdir -p "$SITE_DIR"
sed "s|@DOMAIN@|$DOMAIN|g" "$HERE/hearth.caddy.in" > "$SITE_DIR/hearth.caddy"

if [[ ! -f "$CF" ]]; then
  printf '%s\n' "$IMPORT_LINE" > "$CF"
  echo "created $CF"
elif grep -qF "$IMPORT_LINE" "$CF"; then
  echo "$CF already imports $SITE_DIR"
else
  cp -a "$CF" "$CF.bak.$(date +%Y%m%d%H%M%S)"
  real_lines="$(grep -cvE '^[[:space:]]*(#.*)?$' "$CF" || true)"
  if [[ "$real_lines" -le 4 ]] && grep -q 'root \* /usr/share/caddy' "$CF"; then
    printf '# Sites live in %s (package placeholder replaced by Hearth install; backup kept)\n%s\n' \
      "$SITE_DIR" "$IMPORT_LINE" > "$CF"
    echo "replaced Caddy's default placeholder in $CF (backup kept)"
  else
    printf '\n# Added by Hearth deploy/install.sh\n%s\n' "$IMPORT_LINE" >> "$CF"
    echo "appended an import line to your existing $CF (backup kept)"
  fi
fi
