from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards import (
    ADMIN_BUTTON_ADD_PANEL,
    ADMIN_BUTTON_ADD_PROFILE_PORT,
    ADMIN_BUTTON_ADD_USER,
    ADMIN_BUTTON_ASSIGN_USER_PROFILES,
    ADMIN_BUTTON_BACK,
    ADMIN_BUTTON_CAPACITY,
    ADMIN_BUTTON_CREATE_PROFILE,
    ADMIN_BUTTON_EDIT_PORT_CAPACITY,
    ADMIN_BUTTON_LIST_PANELS,
    ADMIN_BUTTON_LIST_PROFILES,
    ADMIN_BUTTON_LIST_USERS,
    ADMIN_BUTTON_MAIN_MENU,
    ADMIN_BUTTON_REMOVE_USER,
    ADMIN_SECTION_PANELS,
    ADMIN_SECTION_PROFILES,
    ADMIN_SECTION_REPORTS,
    ADMIN_SECTION_USERS,
    ADMIN_BUTTON_TEST_PANEL,
    ADMIN_BUTTON_TOGGLE_PROFILE,
    admin_back_keyboard,
    admin_menu_keyboard,
    admin_panels_keyboard,
    admin_profiles_keyboard,
    admin_reports_keyboard,
    admin_users_keyboard,
    panel_delete_confirm_keyboard,
    panel_list_keyboard,
)
from src.bot.states import AdminStates
from src.repositories.allowlist import AllowlistRepository
from src.repositories.panels import PanelRepository
from src.repositories.profiles import ProfileRepository
from src.services.allocator import AllocationError, AllocatorService
from src.services.crypto import CryptoService
from src.services.xui_client import XUIClient, XUIError


def build_admin_router(
    *,
    admin_chat_id: int,
    allowlist_repo: AllowlistRepository,
    panel_repo: PanelRepository,
    profile_repo: ProfileRepository,
    allocator: AllocatorService,
    crypto: CryptoService,
    xui_verify_tls: bool,
    request_timeout: int,
) -> Router:
    router = Router(name="admin")

    def is_admin(chat_id: int) -> bool:
        return chat_id == admin_chat_id

    async def guard_admin(message: Message) -> bool:
        if not is_admin(message.from_user.id):
            await message.answer("این بخش فقط برای ادمین است.")
            return False
        return True

    async def guard_admin_callback(callback: CallbackQuery) -> bool:
        if not is_admin(callback.from_user.id):
            await callback.answer("این بخش فقط برای ادمین است.", show_alert=True)
            return False
        return True

    async def back_to_admin_menu(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("به منوی اصلی ادمین برگشتی.", reply_markup=admin_menu_keyboard())

    def wants_back(message: Message) -> bool:
        return (message.text or "").strip() == ADMIN_BUTTON_BACK

    def wants_main_menu(message: Message) -> bool:
        return (message.text or "").strip() == ADMIN_BUTTON_MAIN_MENU

    @router.message(Command("admin"))
    async def admin_menu(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.clear()
        await message.answer(
            "پنل ادمین باز شد. یک بخش را انتخاب کن.",
            reply_markup=admin_menu_keyboard(),
        )

    @router.message(Command("start"), F.from_user.id == admin_chat_id)
    async def admin_start_redirect(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer(
            "شما ادمین هستید. منوی ادمین باز شد.",
            reply_markup=admin_menu_keyboard(),
        )

    @router.message(Command("cancel"))
    async def cancel_any(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.clear()
        await message.answer("عملیات لغو شد.", reply_markup=admin_menu_keyboard())

    @router.message(F.text == ADMIN_BUTTON_MAIN_MENU)
    async def open_main_menu(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.clear()
        await message.answer("منوی اصلی ادمین:", reply_markup=admin_menu_keyboard())

    @router.message(F.text == ADMIN_SECTION_USERS)
    async def open_users_panel(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.clear()
        await message.answer("مدیریت مشتری‌ها:", reply_markup=admin_users_keyboard())

    @router.message(F.text == ADMIN_SECTION_PROFILES)
    async def open_profiles_panel(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.clear()
        await message.answer("مدیریت پروفایل‌ها:", reply_markup=admin_profiles_keyboard())

    @router.message(F.text == ADMIN_SECTION_PANELS)
    async def open_panels_panel(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.clear()
        await message.answer("مدیریت پنل‌ها:", reply_markup=admin_panels_keyboard())

    @router.message(F.text == ADMIN_SECTION_REPORTS)
    async def open_reports_panel(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.clear()
        await message.answer("بخش گزارش‌ها:", reply_markup=admin_reports_keyboard())

    @router.message(F.text == ADMIN_BUTTON_ADD_USER)
    async def ask_add_user(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.set_state(AdminStates.add_user)
        await message.answer(
            "فرمت: `chat_id|name`\n"
            "مثال: `123456789|علی`\n"
            "برای انصراف دکمه `بازگشت` را بزن.",
            reply_markup=admin_back_keyboard(),
        )

    @router.message(AdminStates.add_user)
    async def add_user(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        if wants_back(message) or wants_main_menu(message):
            await back_to_admin_menu(message, state)
            return
        raw = (message.text or "").strip()
        if not raw:
            await message.answer("فرمت اشتباه است.")
            return
        if "|" in raw:
            parts = [p.strip() for p in raw.split("|", 1)]
        else:
            parts = raw.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("فرمت صحیح: `chat_id|name`")
            return
        chat_raw, customer_name = parts[0], parts[1].strip()
        if not customer_name:
            await message.answer("نام مشتری خالی نباشد.")
            return
        try:
            chat_id = int(chat_raw)
        except ValueError:
            await message.answer("chat_id باید عدد باشد.")
            return
        await allowlist_repo.add(chat_id, customer_name)
        await state.clear()
        await message.answer(
            f"مشتری `{customer_name}` با chat_id `{chat_id}` اضافه شد.",
            reply_markup=admin_users_keyboard(),
        )

    @router.message(F.text == ADMIN_BUTTON_REMOVE_USER)
    async def ask_remove_user(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.set_state(AdminStates.remove_user)
        await message.answer(
            "chat_id کاربر برای حذف را بفرست.\n"
            "برای انصراف دکمه `بازگشت` را بزن.",
            reply_markup=admin_back_keyboard(),
        )

    @router.message(AdminStates.remove_user)
    async def remove_user(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        if wants_back(message) or wants_main_menu(message):
            await back_to_admin_menu(message, state)
            return
        try:
            chat_id = int((message.text or "").strip())
        except ValueError:
            await message.answer("chat_id باید عدد باشد.")
            return

        if chat_id == admin_chat_id:
            await message.answer("ادمین اصلی حذف نمی‌شود.")
            return

        await allowlist_repo.remove(chat_id)
        await state.clear()
        await message.answer(f"کاربر {chat_id} حذف شد.", reply_markup=admin_users_keyboard())

    @router.message(F.text == ADMIN_BUTTON_ASSIGN_USER_PROFILES)
    async def ask_assign_user_profiles(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.set_state(AdminStates.assign_user_profiles)
        await message.answer(
            "فرمت: `chat_id|profile1,profile2`\n"
            "مثال: `123456789|10h,20h`\n"
            "برای دسترسی به همه پروفایل‌ها: `123456789|all`\n"
            "برای انصراف دکمه `بازگشت` را بزن.",
            reply_markup=admin_back_keyboard(),
        )

    @router.message(AdminStates.assign_user_profiles)
    async def assign_user_profiles(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        if wants_back(message) or wants_main_menu(message):
            await back_to_admin_menu(message, state)
            return
        raw = (message.text or "").strip()
        parts = [p.strip() for p in raw.split("|", 1)]
        if len(parts) != 2:
            await message.answer("فرمت اشتباه است. از `chat_id|profile1,profile2` استفاده کن.")
            return

        chat_raw, profile_raw = parts
        try:
            chat_id = int(chat_raw)
        except ValueError:
            await message.answer("chat_id باید عدد باشد.")
            return

        user = await allowlist_repo.get_user(chat_id)
        if user is None:
            await message.answer("این مشتری در لیست مجاز نیست. اول مشتری را اضافه کن.")
            return

        profile_token = profile_raw.strip().lower()
        if profile_token == "all":
            await allowlist_repo.set_profile_access(chat_id, [])
            await state.clear()
            await message.answer(
                f"دسترسی مشتری `{user[1]}` به همه پروفایل‌های فعال تنظیم شد.",
                reply_markup=admin_users_keyboard(),
            )
            return

        requested_names = [x.strip() for x in profile_raw.split(",") if x.strip()]
        if not requested_names:
            await message.answer("حداقل یک نام پروفایل بده یا `all` بفرست.")
            return

        profiles = await profile_repo.list_profiles(active_only=False)
        by_name = {p.name: p for p in profiles}
        missing = [name for name in requested_names if name not in by_name]
        if missing:
            await message.answer(f"پروفایل پیدا نشد: {', '.join(missing)}")
            return

        profile_ids = [by_name[name].id for name in requested_names]
        await allowlist_repo.set_profile_access(chat_id, profile_ids)
        await state.clear()
        await message.answer(
            f"دسترسی مشتری `{user[1]}` روی این پروفایل‌ها تنظیم شد: {', '.join(requested_names)}",
            reply_markup=admin_users_keyboard(),
        )

    @router.message(F.text == ADMIN_BUTTON_LIST_USERS)
    async def list_users(message: Message) -> None:
        if not await guard_admin(message):
            return
        users = await allowlist_repo.list_users()
        if not users:
            await message.answer("هیچ مشتری ثبت نشده.")
            return

        profiles = await profile_repo.list_profiles(active_only=False)
        profile_by_id = {p.id: p.name for p in profiles}

        lines = ["مشتری‌ها:"]
        for chat_id, name in users:
            access_ids = await allowlist_repo.get_profile_access(chat_id)
            if access_ids:
                names = [profile_by_id.get(pid, f"#{pid}") for pid in sorted(access_ids)]
                access_text = ", ".join(names)
            else:
                access_text = "همه پروفایل‌ها"
            display_name = name if name else "-"
            lines.append(f"- {display_name} | {chat_id} | دسترسی: {access_text}")

        await message.answer("\n".join(lines), reply_markup=admin_users_keyboard())

    @router.message(F.text == ADMIN_BUTTON_ADD_PANEL)
    async def ask_add_panel(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.set_state(AdminStates.add_panel)
        await message.answer(
            "فرمت:\n"
            "`name|base_url|username|password`\n"
            "مثال:\n"
            "`main|https://1.2.3.4:20753/abc123|admin|tsvpn2000`\n"
            "برای انصراف دکمه `بازگشت` را بزن.",
            reply_markup=admin_back_keyboard(),
        )

    @router.message(AdminStates.add_panel)
    async def add_panel(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        if wants_back(message) or wants_main_menu(message):
            await back_to_admin_menu(message, state)
            return
        parts = [p.strip() for p in (message.text or "").split("|")]
        if len(parts) != 4 or not all(parts):
            await message.answer("فرمت اشتباه است. دقیقا 4 بخش با | بفرست.")
            return

        name, base_url, username, password = parts
        if not base_url.startswith("http://") and not base_url.startswith("https://"):
            base_url = "https://" + base_url

        enc = crypto.encrypt(password)
        await panel_repo.add(name=name, base_url=base_url.rstrip("/"), username=username, password_enc=enc)
        await state.clear()
        await message.answer(f"پنل `{name}` ذخیره شد.", reply_markup=admin_panels_keyboard())

    @router.message(F.text == ADMIN_BUTTON_TEST_PANEL)
    async def ask_test_panel(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.set_state(AdminStates.test_panel)
        panels = await panel_repo.list_panels(active_only=False)
        names = ", ".join(p.name for p in panels) if panels else "-"
        await message.answer(
            f"نام پنل را بفرست.\nپنل‌های ثبت‌شده: {names}\n"
            "برای انصراف دکمه `بازگشت` را بزن.",
            reply_markup=admin_back_keyboard(),
        )

    @router.message(AdminStates.test_panel)
    async def test_panel(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        if wants_back(message) or wants_main_menu(message):
            await back_to_admin_menu(message, state)
            return
        panel_name = (message.text or "").strip()
        panel = await panel_repo.get_by_name(panel_name)
        if panel is None:
            await message.answer("پنل پیدا نشد.")
            return

        try:
            password = crypto.decrypt(panel.password_enc)
            async with XUIClient(
                base_url=panel.base_url,
                username=panel.username,
                password=password,
                verify_tls=xui_verify_tls,
                timeout_seconds=request_timeout,
            ) as xui:
                count = await xui.test_connection()
        except XUIError as exc:
            await message.answer(f"تست ناموفق: {exc}")
            return

        await state.clear()
        await message.answer(
            f"اتصال پنل `{panel.name}` موفق بود. تعداد inbound: {count}",
            reply_markup=admin_panels_keyboard(),
        )

    @router.message(F.text == ADMIN_BUTTON_CREATE_PROFILE)
    async def ask_create_profile(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.set_state(AdminStates.create_profile)
        panels = await panel_repo.list_panels(active_only=False)
        names = ", ".join(p.name for p in panels) if panels else "-"
        await message.answer(
            "فرمت:\n"
            "`name|panel_name|prefix|suffix|gb|days|port:max,port:max`\n"
            "یا بدون suffix:\n"
            "`name|panel_name|prefix|gb|days|port:max,port:max`\n"
            "مثال:\n"
            "`10h|main|10h||30|10|1044:1000,1025:1000`\n"
            "اگر suffix نمی‌خوای خالی بگذار (دو || پشت هم).\n"
            f"پنل‌های ثبت‌شده: {names}\n"
            "برای انصراف دکمه `بازگشت` را بزن.",
            reply_markup=admin_back_keyboard(),
        )

    @router.message(AdminStates.create_profile)
    async def create_profile(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        if wants_back(message) or wants_main_menu(message):
            await back_to_admin_menu(message, state)
            return

        raw = (message.text or "").strip()
        parts = raw.split("|")
        if len(parts) not in {6, 7}:
            await message.answer("فرمت اشتباه است. باید 6 یا 7 بخش باشد.")
            return

        if len(parts) == 7:
            name, panel_name, prefix, suffix, gb_raw, days_raw, ports_raw = [p.strip() for p in parts]
        else:
            name, panel_name, prefix, gb_raw, days_raw, ports_raw = [p.strip() for p in parts]
            suffix = ""

        if not name or not panel_name or not prefix:
            await message.answer("name, panel_name, prefix اجباری هستند.")
            return

        if suffix == "_":
            suffix = ""

        try:
            gb = int(gb_raw)
            days = int(days_raw)
        except ValueError:
            await message.answer("gb و days باید عدد باشند.")
            return

        if gb < 0 or days < 0:
            await message.answer("gb و days نباید منفی باشند.")
            return

        panel = await panel_repo.get_by_name(panel_name)
        if panel is None:
            await message.answer("پنل پیدا نشد.")
            return

        entries = [e.strip() for e in ports_raw.split(",") if e.strip()]
        if not entries:
            await message.answer("حداقل یک پورت لازم است.")
            return

        requested_ports: list[tuple[int, int]] = []
        seen_ports: set[int] = set()
        for entry in entries:
            if ":" not in entry:
                await message.answer(f"فرمت پورت اشتباه: {entry}")
                return
            port_raw, max_raw = [x.strip() for x in entry.split(":", 1)]
            try:
                port = int(port_raw)
                max_count = int(max_raw)
            except ValueError:
                await message.answer(f"port/max باید عدد باشد: {entry}")
                return
            if port in seen_ports:
                await message.answer(f"پورت تکراری مجاز نیست: {port}")
                return
            if max_count <= 0:
                await message.answer(f"max برای پورت {port} باید بیشتر از صفر باشد.")
                return
            seen_ports.add(port)
            requested_ports.append((port, max_count))

        try:
            password = crypto.decrypt(panel.password_enc)
            async with XUIClient(
                base_url=panel.base_url,
                username=panel.username,
                password=password,
                verify_tls=xui_verify_tls,
                timeout_seconds=request_timeout,
            ) as xui:
                inbounds = await xui.list_inbounds()
        except XUIError as exc:
            await message.answer(f"خطا در اتصال پنل: {exc}")
            return

        inbound_by_port: dict[int, list[dict]] = {}
        for inbound in inbounds:
            try:
                port = int(inbound.get("port"))
            except (TypeError, ValueError):
                continue
            inbound_by_port.setdefault(port, []).append(inbound)

        db_ports: list[tuple[int, int, int]] = []
        for port, max_count in requested_ports:
            matches = inbound_by_port.get(port, [])
            if len(matches) == 0:
                await message.answer(f"پورت {port} روی پنل پیدا نشد.")
                return
            if len(matches) > 1:
                await message.answer(f"برای پورت {port} چند inbound وجود دارد؛ نامعتبر است.")
                return
            inbound_id = int(matches[0]["id"])
            db_ports.append((inbound_id, port, max_count))

        try:
            profile_id = await profile_repo.create(
                panel_id=panel.id,
                name=name,
                prefix=prefix,
                suffix=suffix,
                traffic_gb=gb,
                expiry_days=days,
                ports=db_ports,
            )
        except Exception as exc:
            await message.answer(f"ساخت پروفایل ناموفق: {exc}")
            return

        await state.clear()
        await message.answer(
            f"پروفایل `{name}` با شناسه {profile_id} ساخته شد.",
            reply_markup=admin_profiles_keyboard(),
        )

    @router.message(F.text == ADMIN_BUTTON_ADD_PROFILE_PORT)
    async def ask_add_profile_port(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.set_state(AdminStates.add_profile_port)
        profiles = await profile_repo.list_profiles(active_only=False)
        names = ", ".join(p.name for p in profiles) if profiles else "-"
        await message.answer(
            "فرمت: `profile_name|port:max`\n"
            "مثال: `10h|51045:100`\n"
            f"پروفایل‌های ثبت‌شده: {names}\n"
            "برای انصراف دکمه `بازگشت` را بزن.",
            reply_markup=admin_back_keyboard(),
        )

    @router.message(AdminStates.add_profile_port)
    async def add_profile_port(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        if wants_back(message) or wants_main_menu(message):
            await back_to_admin_menu(message, state)
            return

        parts = [p.strip() for p in (message.text or "").split("|")]
        if len(parts) != 2:
            await message.answer("فرمت اشتباه است. مثال: `10h|51045:100`")
            return

        profile_name, port_spec = parts
        if ":" not in port_spec:
            await message.answer("فرمت پورت اشتباه است. مثال: `51045:100`")
            return
        port_raw, max_raw = [x.strip() for x in port_spec.split(":", 1)]
        try:
            port = int(port_raw)
            max_count = int(max_raw)
        except ValueError:
            await message.answer("port و max باید عدد باشند.")
            return
        if max_count <= 0:
            await message.answer("max باید بیشتر از صفر باشد.")
            return

        profile = await profile_repo.get_by_name(profile_name)
        if profile is None:
            await message.answer("پروفایل پیدا نشد.")
            return

        existing_ports = await profile_repo.list_ports(profile.id)
        if any(p.port == port for p in existing_ports):
            await message.answer(f"پورت {port} از قبل برای این پروفایل ثبت شده.")
            return

        panel = await panel_repo.get_by_id(profile.panel_id)
        if panel is None:
            await message.answer("پنل متصل به پروفایل پیدا نشد.")
            return

        try:
            password = crypto.decrypt(panel.password_enc)
            async with XUIClient(
                base_url=panel.base_url,
                username=panel.username,
                password=password,
                verify_tls=xui_verify_tls,
                timeout_seconds=request_timeout,
            ) as xui:
                inbounds = await xui.list_inbounds()
        except XUIError as exc:
            await message.answer(f"خطا در اتصال پنل: {exc}")
            return

        matches = []
        for inbound in inbounds:
            try:
                inbound_port = int(inbound.get("port"))
            except (TypeError, ValueError):
                continue
            if inbound_port == port:
                matches.append(inbound)

        if not matches:
            await message.answer(f"پورت {port} روی پنل `{panel.name}` پیدا نشد.")
            return
        if len(matches) > 1:
            await message.answer(f"برای پورت {port} چند inbound وجود دارد؛ نامعتبر است.")
            return

        inbound_id = int(matches[0]["id"])
        try:
            await profile_repo.add_port(
                profile_id=profile.id,
                inbound_id=inbound_id,
                port=port,
                max_active_clients=max_count,
            )
        except Exception as exc:
            await message.answer(f"افزودن پورت ناموفق: {exc}")
            return

        await state.clear()
        await message.answer(
            f"پورت {port} با ظرفیت {max_count} به پروفایل `{profile.name}` اضافه شد.",
            reply_markup=admin_profiles_keyboard(),
        )

    @router.message(F.text == ADMIN_BUTTON_EDIT_PORT_CAPACITY)
    async def ask_edit_port_capacity(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.set_state(AdminStates.update_profile_port_capacity)
        profiles = await profile_repo.list_profiles(active_only=False)
        names = ", ".join(p.name for p in profiles) if profiles else "-"
        await message.answer(
            "فرمت: `profile_name|port|max`\n"
            "مثال: `10h|51045|250`\n"
            f"پروفایل‌های ثبت‌شده: {names}\n"
            "برای انصراف دکمه `بازگشت` را بزن.",
            reply_markup=admin_back_keyboard(),
        )

    @router.message(AdminStates.update_profile_port_capacity)
    async def edit_port_capacity(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        if wants_back(message) or wants_main_menu(message):
            await back_to_admin_menu(message, state)
            return

        parts = [p.strip() for p in (message.text or "").split("|")]
        if len(parts) != 3:
            await message.answer("فرمت اشتباه است. مثال: `10h|51045|250`")
            return

        profile_name, port_raw, max_raw = parts
        try:
            port = int(port_raw)
            max_count = int(max_raw)
        except ValueError:
            await message.answer("port و max باید عدد باشند.")
            return
        if max_count <= 0:
            await message.answer("max باید بیشتر از صفر باشد.")
            return

        profile = await profile_repo.get_by_name(profile_name)
        if profile is None:
            await message.answer("پروفایل پیدا نشد.")
            return

        updated = await profile_repo.update_port_capacity(
            profile_id=profile.id,
            port=port,
            max_active_clients=max_count,
        )
        if not updated:
            await message.answer(f"پورت {port} برای پروفایل `{profile.name}` ثبت نشده است.")
            return

        await state.clear()
        await message.answer(
            f"ظرفیت پورت {port} در پروفایل `{profile.name}` به {max_count} تغییر کرد.",
            reply_markup=admin_profiles_keyboard(),
        )

    @router.message(F.text == ADMIN_BUTTON_TOGGLE_PROFILE)
    async def ask_toggle_profile(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.set_state(AdminStates.toggle_profile)
        profiles = await profile_repo.list_profiles(active_only=False)
        names = ", ".join(p.name for p in profiles) if profiles else "-"
        await message.answer(
            "فرمت: `profile_name|on` یا `profile_name|off`\n"
            f"پروفایل‌های ثبت‌شده: {names}\n"
            "برای انصراف دکمه `بازگشت` را بزن.",
            reply_markup=admin_back_keyboard(),
        )

    @router.message(AdminStates.toggle_profile)
    async def toggle_profile(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        if wants_back(message) or wants_main_menu(message):
            await back_to_admin_menu(message, state)
            return
        parts = [p.strip() for p in (message.text or "").split("|")]
        if len(parts) != 2:
            await message.answer("فرمت اشتباه است.")
            return
        profile_name, status = parts

        profile = await profile_repo.get_by_name(profile_name)
        if profile is None:
            await message.answer("پروفایل پیدا نشد.")
            return

        status_l = status.lower()
        if status_l not in {"on", "off"}:
            await message.answer("مقدار وضعیت فقط on/off")
            return

        await profile_repo.set_active(profile.id, status_l == "on")
        await state.clear()
        await message.answer("وضعیت پروفایل تغییر کرد.", reply_markup=admin_profiles_keyboard())

    @router.message(F.text == ADMIN_BUTTON_CAPACITY)
    async def ask_capacity(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        await state.set_state(AdminStates.capacity_report)
        profiles = await profile_repo.list_profiles(active_only=False)
        names = ", ".join(p.name for p in profiles) if profiles else "-"
        await message.answer(
            "نام پروفایل را بفرست یا `all`\n"
            f"پروفایل‌های ثبت‌شده: {names}\n"
            "برای انصراف دکمه `بازگشت` را بزن.",
            reply_markup=admin_back_keyboard(),
        )

    @router.message(AdminStates.capacity_report)
    async def capacity_report(message: Message, state: FSMContext) -> None:
        if not await guard_admin(message):
            return
        if wants_back(message) or wants_main_menu(message):
            await back_to_admin_menu(message, state)
            return
        target = (message.text or "").strip()

        profiles = await profile_repo.list_profiles(active_only=False)
        selected = profiles if target.lower() == "all" else [p for p in profiles if p.name == target]
        if not selected:
            await message.answer("پروفایلی پیدا نشد.")
            return

        lines: list[str] = []
        for profile in selected:
            try:
                report = await allocator.get_capacity_report(profile.id)
            except (AllocationError, XUIError) as exc:
                lines.append(f"- {profile.name}: خطا -> {exc}")
                continue
            lines.append(
                f"- {report['profile_name']}: used={report['used']} free={report['free']} total={report['total_capacity']}"
            )
            for item in report["ports"]:
                lines.append(
                    f"  port {item['port']} | used={item['used']} free={item['free']} max={item['max']}"
                )

        await state.clear()
        await message.answer("\n".join(lines), reply_markup=admin_reports_keyboard())

    @router.message(F.text == ADMIN_BUTTON_LIST_PANELS)
    async def list_panels(message: Message) -> None:
        if not await guard_admin(message):
            return
        panels = await panel_repo.list_panels(active_only=False)
        if not panels:
            await message.answer("هیچ پنلی ثبت نشده.")
            return

        profiles = await profile_repo.list_profiles(active_only=False)
        profiles_by_panel: dict[int, list] = {}
        for profile in profiles:
            profiles_by_panel.setdefault(profile.panel_id, []).append(profile)

        lines = ["پنل‌ها:"]
        panel_buttons: list[tuple[int, str]] = []
        for panel in panels:
            status = "on" if panel.active else "off"
            lines.append(f"- {panel.name} ({status}) -> {panel.base_url}")
            panel_profiles = profiles_by_panel.get(panel.id, [])
            if not panel_profiles:
                lines.append("  پروفایل: -")
            for profile in panel_profiles:
                profile_status = "on" if profile.active else "off"
                ports = await profile_repo.list_ports(profile.id)
                ports_str = ", ".join(f"{p.port}:{p.max_active_clients}" for p in ports) if ports else "-"
                lines.append(f"  پروفایل {profile.name} ({profile_status}) | ports=[{ports_str}]")
            panel_buttons.append((panel.id, panel.name))

        lines.append("")
        lines.append("برای افزودن پورت: «افزودن پورت پروفایل»")
        lines.append("برای تغییر ظرفیت: «ویرایش ظرفیت پورت»")
        await message.answer("\n".join(lines), reply_markup=panel_list_keyboard(panel_buttons))

    @router.callback_query(F.data.startswith("admin_panel_delete:"))
    async def ask_delete_panel(callback: CallbackQuery) -> None:
        if not await guard_admin_callback(callback):
            return
        _, panel_id_raw = callback.data.split(":", 1)
        try:
            panel_id = int(panel_id_raw)
        except ValueError:
            await callback.answer("شناسه پنل نامعتبر است.", show_alert=True)
            return

        panel = await panel_repo.get_by_id(panel_id)
        if panel is None:
            await callback.answer("پنل پیدا نشد.", show_alert=True)
            return

        await callback.message.answer(
            f"حذف پنل `{panel.name}` تایید شود؟\n"
            "توجه: پروفایل‌های متصل به این پنل هم حذف می‌شوند.",
            reply_markup=panel_delete_confirm_keyboard(panel.id),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("admin_panel_confirm_delete:"))
    async def confirm_delete_panel(callback: CallbackQuery) -> None:
        if not await guard_admin_callback(callback):
            return
        _, panel_id_raw = callback.data.split(":", 1)
        try:
            panel_id = int(panel_id_raw)
        except ValueError:
            await callback.answer("شناسه پنل نامعتبر است.", show_alert=True)
            return

        panel = await panel_repo.get_by_id(panel_id)
        if panel is None:
            await callback.answer("پنل قبلا حذف شده یا وجود ندارد.", show_alert=True)
            return

        await panel_repo.delete(panel_id)
        await callback.message.edit_text(f"پنل `{panel.name}` حذف شد.")
        await callback.answer("حذف شد")

    @router.callback_query(F.data == "admin_panel_delete_cancel")
    async def cancel_delete_panel(callback: CallbackQuery) -> None:
        if not await guard_admin_callback(callback):
            return
        await callback.message.edit_text("حذف پنل لغو شد.")
        await callback.answer("لغو شد")

    @router.message(F.text == ADMIN_BUTTON_LIST_PROFILES)
    async def list_profiles(message: Message) -> None:
        if not await guard_admin(message):
            return
        profiles = await profile_repo.list_profiles(active_only=False)
        if not profiles:
            await message.answer("هیچ پروفایلی ثبت نشده.")
            return
        lines = ["پروفایل‌ها:"]
        for profile in profiles:
            status = "on" if profile.active else "off"
            ports = await profile_repo.list_ports(profile.id)
            ports_str = ", ".join(f"{p.port}:{p.max_active_clients}" for p in ports)
            lines.append(
                f"- {profile.name} ({status}) panel={profile.panel_id} prefix={profile.prefix} gb={profile.traffic_gb} days={profile.expiry_days} ports=[{ports_str}]"
            )
        await message.answer("\n".join(lines), reply_markup=admin_profiles_keyboard())

    return router
