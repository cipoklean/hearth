#!/usr/bin/env bash
# Post-install / post-update health check for Hearth.
#   ./deploy/check.sh [hostname]
# 1. the app answers on 127.0.0.1:8088/api/health (required; retried for ~30 s)
# 2. Caddy answers on https://<hostname>/api/health (warns only: needs the OCI security list
#    rules for 80/443 and a certificate, which Caddy fetches on its own)
set -euo pipefail
LOCAL="${HEARTH_LOCAL_URL:-http://127.0.0.1:8088}"
DOMAIN="${1:-${HEARTH_DOMAIN:-}}"
if [[ -z "$DOMAIN" && -r /etc/hearth.env ]]; then
  DOMAIN="$(grep -E '^HEARTH_DOMAIN=' /etc/hearth.env | tail -n1 | cut -d= -f2- || true)"
fi

body=""
for _ in $(seq 1 30); do
  if body="$(curl -fsS --max-time 3 "$LOCAL/api/health" 2>/dev/null)"; then break; fi
  body=""
  sleep 1
done
if [[ -z "$body" ]]; then
  echo "    FAIL  app not answering on $LOCAL/api/health"
  echo "          see: sudo systemctl status hearth ; journalctl -u hearth -n 50"
  exit 1
fi
case "$body" in
  *'"ok":true'*) echo "    OK    app: $body" ;;
  *) echo "    FAIL  app unhealthy: $body"; exit 1 ;;
esac

if [[ -n "$DOMAIN" ]]; then
  if out="$(curl -fsS --max-time 10 "https://$DOMAIN/api/health" 2>&1)"; then
    echo "    OK    https://$DOMAIN/api/health"
  else
    echo "    WAIT  https://$DOMAIN not reachable yet: ${out:0:160}"
    echo "          Open TCP 80 and 443 in the OCI VCN security list, give Caddy a minute to get"
    echo "          the certificate (journalctl -u caddy -f), then run this check again."
  fi
fi
