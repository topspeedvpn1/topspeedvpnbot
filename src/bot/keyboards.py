from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


ADMIN_BUTTON_ADD_USER = "افزودن مشتری"
ADMIN_BUTTON_REMOVE_USER = "حذف مشتری"
ADMIN_BUTTON_ADD_PANEL = "افزودن پنل"
ADMIN_BUTTON_TEST_PANEL = "تست پنل"
ADMIN_BUTTON_CREATE_PROFILE = "ساخت پروفایل"
ADMIN_BUTTON_TOGGLE_PROFILE = "تغییر وضعیت پروفایل"
ADMIN_BUTTON_CAPACITY = "گزارش ظرفیت"
ADMIN_BUTTON_LIST_PANELS = "لیست پنل‌ها"
ADMIN_BUTTON_LIST_PROFILES = "لیست پروفایل‌ها"

ADMIN_BUTTONS = {
    ADMIN_BUTTON_ADD_USER,
    ADMIN_BUTTON_REMOVE_USER,
    ADMIN_BUTTON_ADD_PANEL,
    ADMIN_BUTTON_TEST_PANEL,
    ADMIN_BUTTON_CREATE_PROFILE,
    ADMIN_BUTTON_TOGGLE_PROFILE,
    ADMIN_BUTTON_CAPACITY,
    ADMIN_BUTTON_LIST_PANELS,
    ADMIN_BUTTON_LIST_PROFILES,
}


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.row(
        KeyboardButton(text=ADMIN_BUTTON_ADD_USER),
        KeyboardButton(text=ADMIN_BUTTON_REMOVE_USER),
    )
    kb.row(
        KeyboardButton(text=ADMIN_BUTTON_ADD_PANEL),
        KeyboardButton(text=ADMIN_BUTTON_TEST_PANEL),
    )
    kb.row(
        KeyboardButton(text=ADMIN_BUTTON_CREATE_PROFILE),
        KeyboardButton(text=ADMIN_BUTTON_TOGGLE_PROFILE),
    )
    kb.row(
        KeyboardButton(text=ADMIN_BUTTON_CAPACITY),
    )
    kb.row(
        KeyboardButton(text=ADMIN_BUTTON_LIST_PANELS),
        KeyboardButton(text=ADMIN_BUTTON_LIST_PROFILES),
    )
    return kb.as_markup(resize_keyboard=True)


def profile_menu_keyboard(profiles: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for profile_id, name in profiles:
        builder.row(InlineKeyboardButton(text=name, callback_data=f"profile:{profile_id}"))
    return builder.as_markup()


def quantity_keyboard(profile_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for qty in (10, 50, 100):
        builder.row(
            InlineKeyboardButton(text=str(qty), callback_data=f"qty:{profile_id}:{qty}")
        )
    return builder.as_markup()
