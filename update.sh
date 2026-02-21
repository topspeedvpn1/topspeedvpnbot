#!/usr/bin/env bash
set -euo pipefail

APP_NAME="topspeedvpnbot"
APP_DIR="/opt/${APP_NAME}"
SERVICE_NAME="${APP_NAME}.service"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root."
  exit 1
fi

if [[ ! -d "${APP_DIR}/.git" ]]; then
  echo "${APP_DIR} not found. Run install.sh first."
  exit 1
fi

echo "Updating source..."
git -C "${APP_DIR}" fetch --all --prune
git -C "${APP_DIR}" reset --hard origin/main

echo "Installing dependencies..."
"${APP_DIR}/.venv/bin/pip" install --upgrade pip >/dev/null
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo "Restarting service..."
systemctl restart "${SERVICE_NAME}"
systemctl --no-pager --full status "${SERVICE_NAME}" || true
