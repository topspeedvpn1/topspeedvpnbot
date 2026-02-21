#!/usr/bin/env bash
set -euo pipefail

APP_NAME="topspeedvpnbot"
APP_DIR="/opt/${APP_NAME}"
ENV_DIR="/etc/${APP_NAME}"
DATA_DIR="/var/lib/${APP_NAME}"
SERVICE_NAME="${APP_NAME}.service"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root."
  exit 1
fi

echo "Stopping and disabling ${SERVICE_NAME}..."
systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
systemctl disable "${SERVICE_NAME}" 2>/dev/null || true

rm -f "${SERVICE_FILE}"
systemctl daemon-reload

rm -rf "${APP_DIR}" "${ENV_DIR}" "${DATA_DIR}"

echo "Uninstall complete."
