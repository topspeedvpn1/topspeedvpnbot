# topspeedvpnbot

Telegram bot for multi-panel 3x-ui config generation with admin-managed profiles.

## Features
- Multi-panel 3x-ui support.
- Allowlist-only users (`chat_id` must be approved by admin).
- Admin can manage:
  - customers (allowlist)
  - panels
  - profiles (prefix/suffix, traffic, days, ports, per-port capacity)
  - add new port to an existing profile
  - edit capacity for an existing profile port
  - delete panels and profiles from list views with confirmation
- User flow:
  - `/start`
  - choose model
  - choose quantity (`10`, `50`, `100`)
  - for each config: QR image + direct link + config number
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
- `/start` (for admin) also opens admin menu directly.

Then use categorized menu panels:
- `مشتری‌ها`
- `پروفایل‌ها`
- `پنل‌ها`
- `گزارش‌ها`
- In every admin input step, `بازگشت` is available to cancel.
- `منوی اصلی` is available in submenus to return to the top admin panel.

### Input formats
- Add customer:
  - `chat_id|name`
  - Example: `123456789|علی`

- Add panel:
  - `name|base_url|username|password`
  - Example: `main|https://1.2.3.4:20753/abc123|admin|tsvpn2000`

- Create profile:
  - `name|panel_name|prefix|suffix|gb|days|start|port:max,port:max`
  - `name|panel_name|prefix|gb|days|start|port:max,port:max` (when suffix is empty)
  - Example: `10h|main|10h||30|10|500|1044:1000,1025:1000`
  - `start` sets the first config number (example: first config becomes `10h500`).
  - Legacy formats without `start` are still accepted for backward compatibility.
  - Note: duplicate ports are rejected.

- Add profile port:
  - `profile_name|port:max`
  - Example: `10h|51045:100`

- Edit profile port capacity:
  - `profile_name|port|max`
  - Example: `10h|51045|250`

- Toggle profile:
  - `profile_name|on`
  - `profile_name|off`

- Assign profile access to customer:
  - `chat_id|profile1,profile2`
  - Example: `123456789|10h,20h`
  - Use `chat_id|all` to let a user see all active profiles.

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
- Ensure panel subscription endpoint is reachable (`subPort`/`subURI`), otherwise link delivery will fail.
