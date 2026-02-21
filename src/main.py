from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from src.bot.handlers_admin import build_admin_router
from src.bot.handlers_user import build_user_router
from src.config import load_config
from src.db import Database
from src.repositories.allowlist import AllowlistRepository
from src.repositories.panels import PanelRepository
from src.repositories.profiles import ProfileRepository
from src.services.allocator import AllocatorService
from src.services.crypto import CryptoService


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


async def run() -> None:
    config = load_config()
    db = Database(config.database_path)
    await db.init()

    allowlist_repo = AllowlistRepository(db)
    panel_repo = PanelRepository(db)
    profile_repo = ProfileRepository(db)

    # Keep admin always allowed.
    await allowlist_repo.add(config.admin_chat_id, "admin")

    crypto = CryptoService(config.app_secret)
    allocator = AllocatorService(
        db=db,
        profiles_repo=profile_repo,
        panels_repo=panel_repo,
        crypto=crypto,
        verify_tls=config.xui_verify_tls,
        timeout_seconds=config.request_timeout,
    )

    bot = Bot(token=config.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(
        build_admin_router(
            admin_chat_id=config.admin_chat_id,
            allowlist_repo=allowlist_repo,
            panel_repo=panel_repo,
            profile_repo=profile_repo,
            allocator=allocator,
            crypto=crypto,
            xui_verify_tls=config.xui_verify_tls,
            request_timeout=config.request_timeout,
        )
    )
    dp.include_router(
        build_user_router(
            admin_chat_id=config.admin_chat_id,
            allowlist_repo=allowlist_repo,
            profile_repo=profile_repo,
            allocator=allocator,
        )
    )

    await dp.start_polling(bot)


def main() -> None:
    configure_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
