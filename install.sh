#!/usr/bin/env bash
set -euo pipefail

APP_NAME="topspeedvpnbot"
APP_DIR="/opt/${APP_NAME}"
ENV_DIR="/etc/${APP_NAME}"
DATA_DIR="/var/lib/${APP_NAME}"
SERVICE_NAME="${APP_NAME}.service"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"
REPO_URL="https://github.com/topspeedvpn1/topspeedvpnbot.git"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root."
  exit 1
fi

ensure_package() {
  local pkg="$1"
  if ! dpkg -s "$pkg" >/dev/null 2>&1; then
    apt-get install -y "$pkg"
  fi
}

echo "[1/8] Installing prerequisites..."
apt-get update -y
ensure_package git
ensure_package curl
ensure_package python3
ensure_package python3-venv
ensure_package python3-pip
ensure_package ca-certificates

if [[ -d "${APP_DIR}/.git" ]]; then
  echo "[2/8] Updating existing repository in ${APP_DIR}..."
  git -C "${APP_DIR}" fetch --all --prune
  git -C "${APP_DIR}" reset --hard origin/main
else
  echo "[2/8] Cloning repository to ${APP_DIR}..."
  rm -rf "${APP_DIR}"
  git clone "${REPO_URL}" "${APP_DIR}"
fi

echo "[3/8] Building virtual environment..."
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip wheel >/dev/null
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

mkdir -p "${ENV_DIR}" "${DATA_DIR}"

read -r -p "Enter Telegram BOT_TOKEN: " BOT_TOKEN
read -r -p "Enter ADMIN_CHAT_ID: " ADMIN_CHAT_ID

if [[ -z "${BOT_TOKEN}" || -z "${ADMIN_CHAT_ID}" ]]; then
  echo "BOT_TOKEN and ADMIN_CHAT_ID are required."
  exit 1
fi

if command -v openssl >/dev/null 2>&1; then
  APP_SECRET="$(openssl rand -hex 32)"
else
  APP_SECRET="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 64)"
fi

echo "[4/8] Writing env file..."
cat > "${ENV_DIR}/.env" <<ENV
BOT_TOKEN=${BOT_TOKEN}
ADMIN_CHAT_ID=${ADMIN_CHAT_ID}
APP_SECRET=${APP_SECRET}
DATABASE_PATH=${DATA_DIR}/topspeedvpnbot.db
XUI_VERIFY_TLS=false
REQUEST_TIMEOUT=30
TIMEZONE=UTC
ENV
chmod 600 "${ENV_DIR}/.env"

echo "[5/8] Installing systemd unit..."
cp -f "${APP_DIR}/systemd/topspeedvpnbot.service" "${SERVICE_FILE}"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

echo "[6/8] Starting service..."
systemctl restart "${SERVICE_NAME}"

sleep 1

echo "[7/8] Service status:"
systemctl --no-pager --full status "${SERVICE_NAME}" || true

echo "[8/8] Done."
echo "Useful commands:"
echo "  systemctl status ${SERVICE_NAME}"
echo "  journalctl -u ${SERVICE_NAME} -f"
echo "  bash <(curl -Ls https://raw.githubusercontent.com/topspeedvpn1/topspeedvpnbot/main/update.sh)"
