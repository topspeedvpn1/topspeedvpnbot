from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    bot_token: str
    admin_chat_id: int
    app_secret: str
    database_path: str
    xui_verify_tls: bool
    request_timeout: int
    timezone: str


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> AppConfig:
    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    admin_chat_id_raw = os.getenv("ADMIN_CHAT_ID", "").strip()
    app_secret = os.getenv("APP_SECRET", "").strip()
    database_path = os.getenv("DATABASE_PATH", "/var/lib/topspeedvpnbot/topspeedvpnbot.db").strip()

    if not bot_token:
        raise ValueError("BOT_TOKEN is required")
    if not admin_chat_id_raw:
        raise ValueError("ADMIN_CHAT_ID is required")
    if not app_secret:
        raise ValueError("APP_SECRET is required")

    try:
        admin_chat_id = int(admin_chat_id_raw)
    except ValueError as exc:
        raise ValueError("ADMIN_CHAT_ID must be an integer") from exc

    return AppConfig(
        bot_token=bot_token,
        admin_chat_id=admin_chat_id,
        app_secret=app_secret,
        database_path=database_path,
        xui_verify_tls=_to_bool(os.getenv("XUI_VERIFY_TLS"), default=False),
        request_timeout=int(os.getenv("REQUEST_TIMEOUT", "30")),
        timezone=os.getenv("TIMEZONE", "UTC").strip() or "UTC",
    )
