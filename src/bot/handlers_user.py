from __future__ import annotations

import asyncio
import io
import re
from urllib.parse import quote, unquote

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
import qrcode

from src.bot.keyboards import (
    USER_BUTTON_BACK,
    quantity_keyboard,
    user_profile_keyboard,
    user_quantity_keyboard,
)
from src.bot.states import UserStates
from src.repositories.allowlist import AllowlistRepository
from src.repositories.profiles import ProfileRepository
from src.services.allocator import AllocationError, AllocatorService
from src.services.link_resolver import LinkResolverError
from src.services.xui_client import XUIError


def build_user_router(
    *,
    admin_chat_id: int,
    allowlist_repo: AllowlistRepository,
    profile_repo: ProfileRepository,
    allocator: AllocatorService,
) -> Router:
    router = Router(name="user")

    def build_qr_png(content: str) -> bytes:
        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(content)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def normalize_link_and_extract_number(link: str, default_index: int) -> tuple[str, str]:
        text = (link or "").strip()
        if not text:
            return "", str(default_index)

        head, sep, fragment = text.partition("#")
        if not sep:
            return text, str(default_index)

        decoded_fragment = unquote(fragment).strip()
        # 3x-ui may append traffic/expiry metadata after "-" in link fragment.
        clean_fragment = decoded_fragment.split("-", 1)[0].strip() if decoded_fragment else ""
        if not clean_fragment:
            clean_fragment = decoded_fragment

        normalized = text
        if clean_fragment:
            encoded = quote(clean_fragment, safe="-._~")
            normalized = f"{head}#{encoded}"

        m = re.search(r"(\d+)$", clean_fragment)
        if m:
            return normalized, m.group(1)

        return normalized, str(default_index)

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

    async def send_profiles_menu(message: Message, *, chat_id: int, state: FSMContext) -> bool:
        profiles = await get_visible_profiles(chat_id)
        if not profiles:
            await state.clear()
            if chat_id == admin_chat_id:
                await message.answer(
                    "فعلا مدلی برای فروش فعال نیست.\n"
                    "شما ادمین هستی؛ با دستور `/admin` وارد پنل ادمین شو و:\n"
                    "1) اول روی 3x-ui یک inbound بساز\n"
                    "2) بعد در ربات `ساخت پروفایل` را انجام بده"
                )
            else:
                await message.answer("فعلا مدلی برای شما فعال نیست. به ادمین پیام بده.")
            return False

        await state.set_state(UserStates.choose_profile)
        await state.update_data(selected_profile_id=None)
        profile_names = [p.name for p in profiles]
        await message.answer(
            "مدل موردنظر را از دکمه‌های پایین انتخاب کن.",
            reply_markup=user_profile_keyboard(profile_names),
        )
        return True

    async def validate_profile_access(chat_id: int, profile_id: int):
        profile = await profile_repo.get_by_id(profile_id)
        if profile is None or not profile.active:
            return None, "این مدل غیرفعال است."
        if chat_id != admin_chat_id:
            access_ids = await allowlist_repo.get_profile_access(chat_id)
            if access_ids and profile.id not in access_ids:
                return None, "این مدل برای شما فعال نیست."
        return profile, None

    async def process_quantity(
        *,
        message: Message,
        chat_id: int,
        profile_id: int,
        quantity: int,
    ) -> None:
        profile, access_error = await validate_profile_access(chat_id, profile_id)
        if access_error is not None:
            await message.answer(access_error)
            return

        await message.answer("در حال ساخت کانفیگ‌ها، کمی صبر کن...")

        try:
            result = await allocator.allocate_and_create(
                profile_id=profile_id,
                quantity=quantity,
                chat_id=chat_id,
            )
        except (AllocationError, XUIError, LinkResolverError) as exc:
            await message.answer(f"ساخت انجام نشد: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            await message.answer(f"خطای غیرمنتظره: {exc}")
            return

        await message.answer(
            f"{result.quantity} کانفیگ از مدل `{result.profile_name}` ساخته شد."
        )
        for idx, link in enumerate(result.links, start=1):
            normalized_link, number = normalize_link_and_extract_number(link, idx)
            try:
                qr_png = build_qr_png(normalized_link)
                qr_file = BufferedInputFile(qr_png, filename=f"config_{number}.png")
                await message.answer_photo(qr_file)
            except Exception:
                # QR generation failure should not block sending config itself.
                pass
            await message.answer(normalized_link)
            await message.answer(number)
            # Small delay to reduce Telegram flood limits on large batches.
            await asyncio.sleep(0.15)

    @router.message(Command("start"))
    async def start(message: Message, state: FSMContext) -> None:
        chat_id = message.from_user.id
        if not await is_allowed(chat_id):
            await state.clear()
            await message.answer(
                "دسترسی شما فعال نیست. chat_id خود را به ادمین بده:\n"
                f"`{chat_id}`"
            )
            return

        await send_profiles_menu(message, chat_id=chat_id, state=state)

    @router.message(UserStates.choose_profile)
    async def choose_profile_from_keyboard(message: Message, state: FSMContext) -> None:
        chat_id = message.from_user.id
        if not await is_allowed(chat_id):
            await state.clear()
            await message.answer("دسترسی ندارید.")
            return

        selected_name = (message.text or "").strip()
        if selected_name == USER_BUTTON_BACK:
            await send_profiles_menu(message, chat_id=chat_id, state=state)
            return

        profiles = await get_visible_profiles(chat_id)
        profile_by_name = {p.name.lower(): p for p in profiles}
        profile = profile_by_name.get(selected_name.lower())
        if profile is None:
            await message.answer("یکی از دکمه‌های پایین را انتخاب کن.")
            return

        await state.set_state(UserStates.choose_quantity)
        await state.update_data(selected_profile_id=profile.id)
        await message.answer(
            f"مدل `{profile.name}` انتخاب شد. چه تعداد می‌خوای؟",
            reply_markup=user_quantity_keyboard(),
        )

    @router.message(UserStates.choose_quantity)
    async def choose_quantity_from_keyboard(message: Message, state: FSMContext) -> None:
        chat_id = message.from_user.id
        if not await is_allowed(chat_id):
            await state.clear()
            await message.answer("دسترسی ندارید.")
            return

        text = (message.text or "").strip()
        if text == USER_BUTTON_BACK:
            await send_profiles_menu(message, chat_id=chat_id, state=state)
            return
        if text not in {"10", "50", "100"}:
            await message.answer("فقط یکی از دکمه‌های 10/50/100 را بزن.")
            return

        data = await state.get_data()
        profile_id = data.get("selected_profile_id")
        if not isinstance(profile_id, int):
            await send_profiles_menu(message, chat_id=chat_id, state=state)
            return

        await process_quantity(
            message=message,
            chat_id=chat_id,
            profile_id=profile_id,
            quantity=int(text),
        )

    @router.callback_query(F.data.startswith("profile:"))
    async def choose_profile(callback: CallbackQuery, state: FSMContext) -> None:
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

        profile, access_error = await validate_profile_access(chat_id, profile_id)
        if access_error is not None:
            await callback.answer(access_error, show_alert=True)
            return

        await state.set_state(UserStates.choose_quantity)
        await state.update_data(selected_profile_id=profile.id)
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

        await callback.answer("در حال ساخت...")
        await process_quantity(
            message=callback.message,
            chat_id=chat_id,
            profile_id=profile_id,
            quantity=quantity,
        )

    return router
