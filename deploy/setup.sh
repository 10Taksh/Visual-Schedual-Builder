#!/usr/bin/env bash
# One-shot server setup for Ubuntu 22.04/24.04 on Oracle Cloud (or any VM).
#
#   sudo REPO_URL=https://github.com/10Taksh/Visual-Schedual-Builder.git bash deploy/setup.sh
#
# Safe to re-run: it updates the checkout, reinstalls dependencies, and restarts the service.
# Optional: DOMAIN=schedule.example.com to have Caddy serve HTTPS for that hostname.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/10Taksh/Visual-Schedual-Builder.git}"
BRANCH="${BRANCH:-main}"
APP_DIR=/opt/schedule-builder
DATA_DIR=/var/lib/schedule-builder
ENV_FILE=/etc/schedule-builder.env
DOMAIN="${DOMAIN:-}"

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo." >&2
  exit 1
fi

echo "==> Installing packages"
apt-get update -q
apt-get install -y -q python3 python3-venv python3-pip git sqlite3 debian-keyring debian-archive-keyring apt-transport-https curl

if ! command -v caddy >/dev/null; then
  echo "==> Installing Caddy"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q
  apt-get install -y -q caddy
fi

echo "==> Opening ports 80/443 in the VM firewall (Oracle's Ubuntu image blocks them by default)"
for port in 80 443; do
  if ! iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null; then
    iptables -I INPUT 6 -p tcp --dport "$port" -m state --state NEW -j ACCEPT
  fi
done
if command -v netfilter-persistent >/dev/null; then netfilter-persistent save; fi

echo "==> Ensuring swap exists (small VMs have none; it prevents out-of-memory during installs)"
if [[ "$(swapon --show --noheadings | wc -l)" -eq 0 ]] && [[ ! -f /swapfile ]]; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap -q /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Creating service user and directories"
id -u schedule >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin schedule
mkdir -p "$APP_DIR" "$DATA_DIR"

echo "==> Fetching the app ($REPO_URL @ $BRANCH)"
if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" fetch --quiet origin
  git -C "$APP_DIR" checkout --quiet "$BRANCH"
  git -C "$APP_DIR" reset --quiet --hard "origin/$BRANCH"
else
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

echo "==> Installing Python dependencies"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "==> Writing $ENV_FILE with a fresh SECRET_KEY"
  MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
  WORKERS=$(( MEM_MB < 1500 ? 1 : 2 ))
  sed -e "s/^SECRET_KEY=.*/SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')/" \
      -e "s/^GUNICORN_WORKERS=.*/GUNICORN_WORKERS=$WORKERS/" \
    "$APP_DIR/deploy/schedule-builder.env.example" > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "    (${MEM_MB} MB RAM -> ${WORKERS} gunicorn worker(s))"
fi

chown -R schedule:schedule "$APP_DIR" "$DATA_DIR"

echo "==> Installing the systemd service"
cp "$APP_DIR/deploy/schedule-builder.service" /etc/systemd/system/schedule-builder.service
systemctl daemon-reload
systemctl enable --now schedule-builder
systemctl restart schedule-builder

echo "==> Configuring Caddy"
if [[ -n "$DOMAIN" ]]; then
  sed "s/^:80 {/$DOMAIN {/" "$APP_DIR/deploy/Caddyfile" > /etc/caddy/Caddyfile
else
  cp "$APP_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
fi
mkdir -p /var/log/caddy && chown caddy:caddy /var/log/caddy
systemctl enable --now caddy
systemctl reload caddy || systemctl restart caddy

echo "==> Installing nightly database backup (03:15, keeps 14 days)"
install -m 755 "$APP_DIR/deploy/backup.sh" /usr/local/bin/schedule-builder-backup
cat > /etc/cron.d/schedule-builder-backup <<'CRON'
15 3 * * * schedule /usr/local/bin/schedule-builder-backup
CRON

echo
echo "Done. Health check:"
sleep 1
curl -fsS http://127.0.0.1:8000/health && echo
PUBLIC_IP=$(curl -fsS --max-time 3 http://169.254.169.254/opc/v2/vnics/ -H 'Authorization: Bearer Oracle' 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)[0].get("publicIp",""))' 2>/dev/null || true)
echo "Open: http://${DOMAIN:-${PUBLIC_IP:-<your-public-ip>}}/"
echo "Logs: journalctl -u schedule-builder -f"
