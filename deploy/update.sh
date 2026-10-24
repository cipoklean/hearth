#!/usr/bin/env bash
# Update a Hearth install in place: pull, rebuild, restart, check.
#   ./deploy/update.sh
# Re-run ./deploy/install.sh instead if deploy/*.in templates changed (it is idempotent).
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
[[ $EUID -ne 0 ]] || { echo "Run as your normal user (it uses sudo)."; exit 1; }

before="$(git rev-parse HEAD)"
git pull --ff-only
after="$(git rev-parse HEAD)"
echo "==> $before -> $after"

changed() { [[ "$before" != "$after" ]] && ! git diff --quiet "$before" "$after" -- "$@"; }

if changed deploy/hearth.service.in deploy/hearth.caddy.in deploy/install.sh; then
  echo "==> deploy templates changed; running install.sh"
  exec "$REPO/deploy/install.sh"
fi

echo "==> web app"
cd web
if changed web/package-lock.json || [[ ! -d node_modules ]]; then npm ci --no-audit --no-fund --loglevel=error; fi
npm run build --silent >/dev/null
cd "$REPO"

echo "==> python deps"
.venv/bin/pip install -q -e .

echo "==> restart"
sudo systemctl restart hearth
"$REPO/deploy/check.sh"
