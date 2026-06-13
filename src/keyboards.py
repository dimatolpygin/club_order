"""Inline-клавиатуры и callback-константы навигации."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ── Навигация по экранам ─────────────────────────────────────────────────────
NAV_START = "nav:start"
NAV_ABOUT = "nav:about"
NAV_RULES = "nav:rules"
NAV_SUPPORT = "nav:support"
NAV_MENU = "nav:menu"

# Разделы тарифов/оплаты/промокодов (на этапе 1 — заглушки, наполнятся позже).
NAV_JOIN = "nav:join"        # Вступить в клуб → выбор тарифа
NAV_TARIFF = "nav:tariff"    # Выбрать тариф
NAV_MYSUB = "nav:mysub"      # Моя подписка
NAV_RENEW = "nav:renew"      # Продлить подписку
NAV_PROMO = "nav:promo"      # Ввести промокод

# ── Поддержка ────────────────────────────────────────────────────────────────
SUP_PAYMENT = "sup:payment"
SUP_NOACCESS = "sup:noaccess"
SUP_QUESTION = "sup:question"
SUP_ADMIN = "sup:admin"


def welcome_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Вступить в клуб", callback_data=NAV_JOIN))
    b.row(InlineKeyboardButton(text="Что внутри клуба", callback_data=NAV_ABOUT))
    b.row(InlineKeyboardButton(text="Правила участия", callback_data=NAV_RULES))
    b.row(InlineKeyboardButton(text="Поддержка", callback_data=NAV_SUPPORT))
    return b.as_markup()


def about_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Выбрать тариф", callback_data=NAV_TARIFF))
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_START))
    return b.as_markup()


def rules_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Вступить в клуб", callback_data=NAV_JOIN))
    b.row(InlineKeyboardButton(text="Моя подписка", callback_data=NAV_MYSUB))
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_START))
    return b.as_markup()


def support_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Проблема с оплатой", callback_data=SUP_PAYMENT))
    b.row(InlineKeyboardButton(text="Нет доступа к чату", callback_data=SUP_NOACCESS))
    b.row(InlineKeyboardButton(text="Вопрос по подписке", callback_data=SUP_QUESTION))
    b.row(InlineKeyboardButton(text="Написать администратору", callback_data=SUP_ADMIN))
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_START))
    return b.as_markup()


def main_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Вступить в клуб", callback_data=NAV_JOIN))
    b.row(
        InlineKeyboardButton(text="Моя подписка", callback_data=NAV_MYSUB),
        InlineKeyboardButton(text="Продлить", callback_data=NAV_RENEW),
    )
    b.row(InlineKeyboardButton(text="Ввести промокод", callback_data=NAV_PROMO))
    b.row(
        InlineKeyboardButton(text="Что внутри клуба", callback_data=NAV_ABOUT),
        InlineKeyboardButton(text="Правила клуба", callback_data=NAV_RULES),
    )
    b.row(InlineKeyboardButton(text="Поддержка", callback_data=NAV_SUPPORT))
    return b.as_markup()


def back_to_support_kb() -> InlineKeyboardMarkup:
    """Кнопка возврата из экрана ввода обращения в меню поддержки."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_SUPPORT))
    return b.as_markup()


def sub_ended_kb() -> InlineKeyboardMarkup:
    """Клавиатура уведомления «подписка закончилась» (экран 17)."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Вернуться в клуб", callback_data=NAV_TARIFF))
    b.row(InlineKeyboardButton(text="Ввести промокод", callback_data=NAV_PROMO))
    return b.as_markup()


def reminder_early_kb() -> InlineKeyboardMarkup:
    """Напоминание «осталось N» (экран 14): продлить · моя подписка."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Продлить подписку", callback_data=NAV_RENEW))
    b.row(InlineKeyboardButton(text="Моя подписка", callback_data=NAV_MYSUB))
    return b.as_markup()


def reminder_soon_kb() -> InlineKeyboardMarkup:
    """Напоминание «завтра заканчивается» (экран 15): продлить сейчас · поддержка."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Продлить сейчас", callback_data=NAV_RENEW))
    b.row(InlineKeyboardButton(text="Поддержка", callback_data=NAV_SUPPORT))
    return b.as_markup()


def reminder_last_kb() -> InlineKeyboardMarkup:
    """Напоминание «последний день» (экран 16): продлить · моя подписка · поддержка."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Продлить подписку", callback_data=NAV_RENEW))
    b.row(InlineKeyboardButton(text="Моя подписка", callback_data=NAV_MYSUB))
    b.row(InlineKeyboardButton(text="Поддержка", callback_data=NAV_SUPPORT))
    return b.as_markup()


def promo_enter_kb() -> InlineKeyboardMarkup:
    """Экран ввода промокода (18): только «Назад» в меню."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_MENU))
    return b.as_markup()


def promo_not_found_kb() -> InlineKeyboardMarkup:
    """Промокод не найден: ввести заново · выбрать тариф · поддержка."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Ввести заново", callback_data=NAV_PROMO))
    b.row(InlineKeyboardButton(text="Выбрать тариф", callback_data=NAV_TARIFF))
    b.row(InlineKeyboardButton(text="Поддержка", callback_data=NAV_SUPPORT))
    return b.as_markup()


def promo_failed_kb() -> InlineKeyboardMarkup:
    """Промокод истёк/исчерпан/уже использован: выбрать тариф · поддержка."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Выбрать тариф", callback_data=NAV_TARIFF))
    b.row(InlineKeyboardButton(text="Поддержка", callback_data=NAV_SUPPORT))
    return b.as_markup()


def to_menu_kb() -> InlineKeyboardMarkup:
    """Кнопка в главное меню (для заглушек и подтверждений)."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_MENU))
    return b.as_markup()
