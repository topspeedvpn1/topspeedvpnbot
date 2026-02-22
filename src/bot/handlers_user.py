from __future__ import annotations

import asyncio
import re
from urllib.parse import unquote

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards import profile_menu_keyboard, quantity_keyboard
from src.repositories.allowlist import AllowlistRepository
from src.repositories.profiles import ProfileRepository
from src.services.allocator import AllocationError, AllocatorService
from src.services.link_resolver import LinkResolverError, LinkResolverService
from src.services.xui_client import XUIError


def build_user_router(
    *,
    admin_chat_id: int,
    allowlist_repo: AllowlistRepository,
    profile_repo: ProfileRepository,
    allocator: AllocatorService,
) -> Router:
    router = Router(name="user")

    def extract_config_number(link: str, default_index: int) -> str:
        text = (link or "").strip()
        if not text:
            return str(default_index)

        decoded = unquote(text)

        # Prefer number in fragment, e.g. #10m293 => 293
        fragment = decoded.split("#", 1)[1] if "#" in decoded else ""
        if fragment:
            m = re.search(r"(\d+)$", fragment)
            if m:
                return m.group(1)

        # Fallback: trailing digits anywhere in full link
        m = re.search(r"(\d+)\D*$", decoded)
        if m:
            return m.group(1)

        return str(default_index)

    async def is_allowed(chat_id: int) -> bool:
        if chat_id == admin_chat_id:
            return True
        return await allowlist_repo.is_allowed(chat_id)

    async def get_visible_profiles(chat_id: int):
        profiles = await profile_repo.list_profiles(active_only=True)
        if chat_id == admin_chat_id:
            return profiles
        access_ids = await allowlist_repo.get_profile_access(chat_id)
        if not access_ids:
            return profiles
        return [p for p in profiles if p.id in access_ids]

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        chat_id = message.from_user.id
        if not await is_allowed(chat_id):
            await message.answer(
                "دسترسی شما فعال نیست. chat_id خود را به ادمین بده:\n"
                f"`{chat_id}`"
            )
            return

        profiles = await get_visible_profiles(chat_id)
        if not profiles:
            if chat_id == admin_chat_id:
                await message.answer(
                    "فعلا مدلی برای فروش فعال نیست.\n"
                    "شما ادمین هستی؛ با دستور `/admin` وارد پنل ادمین شو و:\n"
                    "1) اول روی 3x-ui یک inbound بساز\n"
                    "2) بعد در ربات `ساخت پروفایل` را انجام بده"
                )
            else:
                await message.answer("فعلا مدلی برای شما فعال نیست. به ادمین پیام بده.")
            return

        menu = [(p.id, p.name) for p in profiles]
        await message.answer(
            "چه مدل کانفیگی می‌خوای؟",
            reply_markup=profile_menu_keyboard(menu),
        )

    @router.callback_query(F.data.startswith("profile:"))
    async def choose_profile(callback: CallbackQuery) -> None:
        chat_id = callback.from_user.id
        if not await is_allowed(chat_id):
            await callback.answer("دسترسی ندارید", show_alert=True)
            return

        _, profile_id_raw = callback.data.split(":", 1)
        try:
            profile_id = int(profile_id_raw)
        except ValueError:
            await callback.answer("پروفایل نامعتبر", show_alert=True)
            return

        profile = await profile_repo.get_by_id(profile_id)
        if profile is None or not profile.active:
            await callback.answer("این مدل غیرفعال است", show_alert=True)
            return
        if chat_id != admin_chat_id:
            access_ids = await allowlist_repo.get_profile_access(chat_id)
            if access_ids and profile.id not in access_ids:
                await callback.answer("این مدل برای شما فعال نیست.", show_alert=True)
                return

        await callback.message.answer(
            f"مدل `{profile.name}` انتخاب شد. چه تعداد می‌خوای؟",
            reply_markup=quantity_keyboard(profile_id),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("qty:"))
    async def choose_quantity(callback: CallbackQuery) -> None:
        chat_id = callback.from_user.id
        if not await is_allowed(chat_id):
            await callback.answer("دسترسی ندارید", show_alert=True)
            return

        try:
            _, profile_id_raw, qty_raw = callback.data.split(":", 2)
            profile_id = int(profile_id_raw)
            quantity = int(qty_raw)
        except ValueError:
            await callback.answer("درخواست نامعتبر", show_alert=True)
            return

        profile = await profile_repo.get_by_id(profile_id)
        if profile is None or not profile.active:
            await callback.answer("این مدل غیرفعال است", show_alert=True)
            return
        if chat_id != admin_chat_id:
            access_ids = await allowlist_repo.get_profile_access(chat_id)
            if access_ids and profile.id not in access_ids:
                await callback.answer("این مدل برای شما فعال نیست.", show_alert=True)
                return

        await callback.answer("در حال ساخت...")
        await callback.message.answer("در حال ساخت کانفیگ‌ها، کمی صبر کن...")

        try:
            result = await allocator.allocate_and_create(
                profile_id=profile_id,
                quantity=quantity,
                chat_id=chat_id,
            )
        except (AllocationError, XUIError, LinkResolverError) as exc:
            await callback.message.answer(f"ساخت انجام نشد: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            await callback.message.answer(f"خطای غیرمنتظره: {exc}")
            return

        await callback.message.answer(
            f"{result.quantity} کانفیگ از مدل `{result.profile_name}` ساخته شد."
        )
        for idx, link in enumerate(result.links, start=1):
            await callback.message.answer(link)
            await callback.message.answer(extract_config_number(link, idx))
            # Small delay to reduce Telegram flood limits on large batches.
            await asyncio.sleep(0.08)

    return router
