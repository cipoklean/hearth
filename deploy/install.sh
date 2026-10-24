#!/usr/bin/env bash
# Hearth one-command install for an Ubuntu VM (Oracle Cloud Always Free Ampere A1 / ARM64, or x86_64).
#
#   git clone <repo> ~/hearth && cd ~/hearth && ./deploy/install.sh
#
# Run as your normal user (it uses sudo). Safe to run again: every step checks first.
# Optional environment:
#   HEARTH_DOMAIN=hearth.example.com   hostname for HTTPS (default: hearth.<public-ip-with-dashes>.sslip.io)
#   HEARTH_PYTHON=python3.11            interpreter to use (default: first of 3.11, 3.12, 3.13, python3 that is >= 3.11)
#   QLOO_API_KEY=...                   used when /etc/hearth.env has no key and there is no terminal
#   HEARTH_SKIP_FIREWALL=1             leave iptables/ufw alone
#
# What it does: Python >= 3.11 venv, Node >= 18 (NodeSource if missing), builds web/, writes
# /etc/hearth.env (asks for your Qloo key, never echoes it), installs hearth.service (uvicorn on
# 127.0.0.1:8088, 2 workers), installs Caddy from its official apt repo and adds a site block via
# /etc/caddy/Caddyfile.d (existing sites untouched), opens 80/443 in iptables, then health-checks.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="$REPO/deploy"
ENV_FILE=/etc/hearth.env
UNIT=/etc/systemd/system/hearth.service
NODE_MAJOR_MIN=18
NODE_MAJOR_INSTALL=22
export DEBIAN_FRONTEND=noninteractive

say()  { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m%s\033[0m\n' "$*"; }
warn() { printf '    \033[1;31m%s\033[0m\n' "$*" >&2; }
die()  { warn "$*"; exit 1; }

# ---- who runs the app ----------------------------------------------------------
if [[ $EUID -eq 0 ]]; then
  APP_USER="${SUDO_USER:-}"
  [[ -n "$APP_USER" && "$APP_USER" != root ]] || die "Run this as your normal user (e.g. ubuntu), not as root: ./deploy/install.sh"
  SUDO=""
else
  APP_USER="$(id -un)"
  SUDO="sudo"
  sudo -v || die "This script needs sudo."
fi
APP_GROUP="$(id -gn "$APP_USER")"
# sudo drops the environment, so pass the non-interactive apt frontend explicitly
apt_get() { $SUDO env DEBIAN_FRONTEND=noninteractive apt-get "$@"; }
as_user() { if [[ $EUID -eq 0 ]]; then sudo -u "$APP_USER" -H "$@"; else "$@"; fi; }

[[ -f "$REPO/pyproject.toml" && -d "$REPO/web" ]] || die "Run from a clone of the Hearth repo (pyproject.toml and web/ not found in $REPO)."
command -v apt-get >/dev/null || die "This installer supports Ubuntu/Debian (apt) only."
say "Installing Hearth from $REPO for user $APP_USER ($(uname -m))"

# ---- packages --------------------------------------------------------------------
say "System packages"
apt_get update -qq
apt_get install -y -qq git curl ca-certificates gnupg debian-keyring debian-archive-keyring \
  apt-transport-https python3 python3-venv >/dev/null
ok "base packages present"

py_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; }
PY=""
for cand in ${HEARTH_PYTHON:-} python3.11 python3.12 python3.13 python3; do
  if command -v "$cand" >/dev/null && py_ok "$cand"; then PY="$(command -v "$cand")"; break; fi
done
if [[ -z "$PY" ]]; then
  say "Python 3.11+ (Ubuntu 22.04 ships 3.10)"
  if ! apt_get install -y -qq python3.11 python3.11-venv >/dev/null 2>&1; then
    apt_get install -y -qq software-properties-common >/dev/null
    $SUDO add-apt-repository -y ppa:deadsnakes/ppa >/dev/null
    apt_get update -qq
    apt_get install -y -qq python3.11 python3.11-venv >/dev/null
  fi
  PY="$(command -v python3.11)"
fi
# the matching -venv package (Debian/Ubuntu split ensurepip out)
PYVER="$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
apt_get install -y -qq "python${PYVER}-venv" >/dev/null 2>&1 || true
ok "Python $PYVER at $PY"

node_major() { as_user bash -lc 'command -v node >/dev/null && node -p "process.versions.node.split(\".\")[0]"' 2>/dev/null || echo 0; }
if (( $(node_major) < NODE_MAJOR_MIN )); then
  say "Node.js $NODE_MAJOR_INSTALL (NodeSource; ARM64 supported)"
  curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR_INSTALL}.x" -o /tmp/nodesource_setup.sh
  $SUDO env DEBIAN_FRONTEND=noninteractive bash /tmp/nodesource_setup.sh >/dev/null
  apt_get install -y -qq nodejs >/dev/null
  rm -f /tmp/nodesource_setup.sh
fi
ok "Node $(as_user bash -lc 'node --version')"

# ---- build -------------------------------------------------------------------------
say "Building the web app (web/dist)"
as_user bash -lc "cd '$REPO/web' && npm ci --no-audit --no-fund --loglevel=error && npm run build --silent" >/dev/null
[[ -f "$REPO/web/dist/index.html" ]] || die "web build did not produce web/dist/index.html"
ok "built"

say "Python virtualenv (.venv)"
if [[ ! -x "$REPO/.venv/bin/python" ]] || ! py_ok "$REPO/.venv/bin/python"; then
  as_user rm -rf "$REPO/.venv"
  as_user "$PY" -m venv "$REPO/.venv" || die "Could not create a venv with $PY (install python${PYVER}-venv)."
fi
as_user "$REPO/.venv/bin/pip" install -q --upgrade pip
as_user "$REPO/.venv/bin/pip" install -q -e "$REPO"
ok "hearth installed into .venv"

# ---- /etc/hearth.env ---------------------------------------------------------------
say "Configuration ($ENV_FILE)"
TMP_ENV="$(mktemp)"
chmod 600 "$TMP_ENV"
trap 'rm -f "$TMP_ENV" "$TMP_ENV.unit"' EXIT
if $SUDO test -f "$ENV_FILE"; then
  $SUDO cat "$ENV_FILE" > "$TMP_ENV"
  ok "keeping existing $ENV_FILE"
else
  sed "s|@REPO@|$REPO|g" "$DEPLOY/hearth.env.example" > "$TMP_ENV"
fi

env_get() { grep -E "^$1=" "$TMP_ENV" | tail -n1 | cut -d= -f2- || true; }
# Replace or add KEY=VALUE without putting VALUE on any command line (bash builtins only).
env_set() {
  local key="$1" val="$2" line found=0 out=""
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == "$key="* ]]; then line="$key=$val"; found=1; fi
    out+="$line"$'\n'
  done < "$TMP_ENV"
  (( found )) || out+="$key=$val"$'\n'
  printf '%s' "$out" > "$TMP_ENV"
}

if [[ -z "$(env_get QLOO_API_KEY)" ]]; then
  key="${QLOO_API_KEY:-}"
  if [[ -z "$key" ]]; then
    [[ -r /dev/tty ]] || die "No Qloo key: set QLOO_API_KEY in $ENV_FILE or export QLOO_API_KEY and re-run."
    read -r -s -p "    Paste your Qloo API key (input hidden): " key < /dev/tty
    echo
  fi
  [[ -n "$key" ]] || die "No Qloo key given."
  [[ "$key" =~ ^[A-Za-z0-9._~+/=-]+$ ]] || die "That key has unexpected characters (spaces or quotes?). Not saved."
  env_set QLOO_API_KEY "$key"
  unset key
  ok "Qloo key saved (not shown)"
else
  ok "Qloo key already set (not shown)"
fi
[[ -n "$(env_get HEARTH_WEB_DIST)" && "$(env_get HEARTH_WEB_DIST)" != *"@REPO@"* ]] || env_set HEARTH_WEB_DIST "$REPO/web/dist"

# hostname: $HEARTH_DOMAIN > value already in the env file > <public-ip>.sslip.io
DOMAIN="${HEARTH_DOMAIN:-$(env_get HEARTH_DOMAIN)}"
if [[ -z "$DOMAIN" ]]; then
  IP=""
  for url in https://api.ipify.org https://ifconfig.me https://icanhazip.com; do
    IP="$(curl -fsS -4 --max-time 5 "$url" 2>/dev/null | tr -d '[:space:]' || true)"
    [[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && break
    IP=""
  done
  [[ -n "$IP" ]] || die "Could not find this VM's public IPv4. Re-run with HEARTH_DOMAIN=<hostname>."
  DOMAIN="hearth.${IP//./-}.sslip.io"
fi
[[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || die "HEARTH_DOMAIN '$DOMAIN' is not a valid hostname."
env_set HEARTH_DOMAIN "$DOMAIN"
$SUDO install -m 640 -o root -g "$APP_GROUP" "$TMP_ENV" "$ENV_FILE"
ok "hostname: $DOMAIN"

# ---- systemd -------------------------------------------------------------------------
say "systemd service (hearth.service on 127.0.0.1:8088)"
sed -e "s|@REPO@|$REPO|g" -e "s|@USER@|$APP_USER|g" -e "s|@GROUP@|$APP_GROUP|g" \
  "$DEPLOY/hearth.service.in" > "$TMP_ENV.unit"
if ! $SUDO cmp -s "$TMP_ENV.unit" "$UNIT"; then
  $SUDO install -m 644 "$TMP_ENV.unit" "$UNIT"
  ok "wrote $UNIT"
fi
rm -f "$TMP_ENV.unit"
$SUDO systemctl daemon-reload
$SUDO systemctl enable hearth >/dev/null 2>&1
$SUDO systemctl restart hearth
ok "hearth.service enabled and (re)started"

# ---- Caddy -----------------------------------------------------------------------------
say "Caddy (HTTPS reverse proxy)"
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | $SUDO gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | $SUDO tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  $SUDO chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
  apt_get update -qq
  apt_get install -y -qq caddy >/dev/null
  ok "installed $(caddy version | cut -d' ' -f1)"
else
  ok "found $(caddy version | cut -d' ' -f1)"
fi
CF=/etc/caddy/Caddyfile
CF_SNAP="$(mktemp)"; HAD_CF=0
if [[ -f "$CF" ]]; then $SUDO cat "$CF" > "$CF_SNAP"; HAD_CF=1; fi
$SUDO "$DEPLOY/caddy-site.sh" "$DOMAIN" /etc/caddy | sed 's/^/    /'
if ! $SUDO caddy validate --config "$CF" --adapter caddyfile >/dev/null 2>&1; then
  $SUDO caddy validate --config "$CF" --adapter caddyfile || true
  # roll back so the live Caddy config (and any other sites) is exactly as before
  $SUDO rm -f /etc/caddy/Caddyfile.d/hearth.caddy
  if (( HAD_CF )); then $SUDO tee "$CF" < "$CF_SNAP" >/dev/null; else $SUDO rm -f "$CF"; fi
  rm -f "$CF_SNAP"
  die "Caddy config invalid; see above. Rolled back, Caddy was not reloaded and other sites are untouched."
fi
rm -f "$CF_SNAP"
$SUDO systemctl enable caddy >/dev/null 2>&1
if $SUDO systemctl is-active --quiet caddy; then $SUDO systemctl reload caddy; else $SUDO systemctl start caddy; fi
ok "Caddy serving https://$DOMAIN"

# ---- firewall (Oracle Ubuntu images REJECT everything but 22 in iptables) -------------------
if [[ "${HEARTH_SKIP_FIREWALL:-0}" != 1 ]]; then
  say "Firewall: open TCP 80 and 443"
  if command -v ufw >/dev/null && $SUDO ufw status 2>/dev/null | grep -q "Status: active"; then
    $SUDO ufw allow 80/tcp >/dev/null && $SUDO ufw allow 443/tcp >/dev/null
    ok "ufw rules added"
  else
    if ! command -v netfilter-persistent >/dev/null; then
      echo "iptables-persistent iptables-persistent/autosave_v4 boolean false" | $SUDO debconf-set-selections
      echo "iptables-persistent iptables-persistent/autosave_v6 boolean false" | $SUDO debconf-set-selections
      apt_get install -y -qq iptables-persistent >/dev/null
    fi
    for port in 80 443; do
      if ! $SUDO iptables -C INPUT -p tcp -m state --state NEW --dport "$port" -j ACCEPT 2>/dev/null; then
        # insert just above the first REJECT rule in INPUT (or at the top if there is none)
        pos="$($SUDO iptables -L INPUT --line-numbers -n | awk '$2=="REJECT"{print $1; exit}')"
        $SUDO iptables -I INPUT "${pos:-1}" -p tcp -m state --state NEW --dport "$port" -j ACCEPT
        ok "iptables: accept TCP $port"
      fi
    done
    $SUDO netfilter-persistent save >/dev/null 2>&1
    ok "rules saved (netfilter-persistent)"
  fi
fi

# ---- check ------------------------------------------------------------------------------
say "Health check"
"$DEPLOY/check.sh" "$DOMAIN" || true

cat <<EOF

  Hearth is installed.
    Service:  sudo systemctl status hearth      logs: journalctl -u hearth -f
    Config:   $ENV_FILE   (edit, then: sudo systemctl restart hearth)
    Update:   $DEPLOY/update.sh
    URL:      https://$DOMAIN

  ONE MORE STEP IN THE ORACLE CLOUD CONSOLE (the VM firewall is not enough):
    Networking > Virtual cloud networks > <your VCN> > Security Lists > Default Security List
    > Add Ingress Rules:  Source CIDR 0.0.0.0/0, IP protocol TCP, Destination port 80
                          Source CIDR 0.0.0.0/0, IP protocol TCP, Destination port 443
    (or the same two rules on the Network Security Group attached to the VM's VNIC).
    Caddy gets the HTTPS certificate automatically once port 80/443 are reachable;
    then re-run: $DEPLOY/check.sh
EOF
