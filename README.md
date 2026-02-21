# topspeedvpnbot

Telegram bot for multi-panel 3x-ui config generation with admin-managed profiles.

## Features
- Multi-panel 3x-ui support.
- Allowlist-only users (`chat_id` must be approved by admin).
- Admin can manage:
  - customers (allowlist)
  - panels
  - profiles (prefix/suffix, traffic, days, ports, per-port capacity)
- User flow:
  - `/start`
  - choose model
  - choose quantity (`10`, `50`, `100`)
  - receive direct links in multiple messages
- Per-profile unique naming without leading zeros (`10h1`, `10h2`, ...).
- Automatic port rotation when a port reaches configured capacity.
- SQLite persistence with encrypted panel passwords (`APP_SECRET`).

## Requirements
- Python 3.10+
- Linux with `systemd` (for service mode)
- 3x-ui panels accessible via HTTPS/HTTP
- 2FA disabled for panel accounts used by bot

## Quick install on server
```bash
bash <(curl -Ls https://raw.githubusercontent.com/topspeedvpn1/topspeedvpnbot/main/install.sh)
```

During install it asks for:
- `BOT_TOKEN`
- `ADMIN_CHAT_ID`

## Update
```bash
bash <(curl -Ls https://raw.githubusercontent.com/topspeedvpn1/topspeedvpnbot/main/update.sh)
```

## Uninstall
```bash
bash <(curl -Ls https://raw.githubusercontent.com/topspeedvpn1/topspeedvpnbot/main/uninstall.sh)
```

## Admin usage
In Telegram (as admin):
- `/admin`

Then use menu buttons.

### Input formats
- Add panel:
  - `name|base_url|username|password`
  - Example: `main|https://1.2.3.4:20753/abc123|admin|tsvpn2000`

- Create profile:
  - `name|panel_name|prefix|suffix|gb|days|port:max,port:max`
  - Example: `10h|main|10h||30|10|1044:1000,1025:1000`
  - Note: duplicate ports are rejected.

- Toggle profile:
  - `profile_name|on`
  - `profile_name|off`

## Local run (development)
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m src.main
```

## Environment variables
See `.env.example`.

Important:
- `DATABASE_PATH` should be writable.
- `APP_SECRET` must stay private.

## Notes
- Bot does not create inbounds; it only adds clients to existing inbounds.
- Direct links are extracted from panel subscription output (`subId`).
