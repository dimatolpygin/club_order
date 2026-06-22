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
NAV_EVENTS = "nav:events"    # Мероприятия (билеты «Фокус.Энергия», этап 13)

# Префиксы callback'ов раздела мероприятий.
EVT_OPEN = "evt"             # evt:{event_id} — открыть карточку события
EVT_BUY = "evtbuy"           # evtbuy:{event_id}:{ticket_type} — выбрать билет
EVT_FULL = "evtfull"         # тап по типу без мест — попап «Мест нет»

def welcome_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Вступить в клуб", callback_data=NAV_JOIN))
    b.row(InlineKeyboardButton(text="Мероприятия", callback_data=NAV_EVENTS))
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


def support_kb(url: str | None) -> InlineKeyboardMarkup:
    """Экран поддержки: кнопка-ссылка «Перейти» (если ссылка задана) + «Назад».

    URL задаётся админом (раздел «Ссылка поддержки»). Если ссылки нет — показываем
    только «Назад» (текст экрана при этом объясняет, что контакт уточняется).
    """
    b = InlineKeyboardBuilder()
    if url:
        b.row(InlineKeyboardButton(text="Перейти в поддержку", url=url))
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
    b.row(InlineKeyboardButton(text="Мероприятия", callback_data=NAV_EVENTS))
    b.row(
        InlineKeyboardButton(text="Что внутри клуба", callback_data=NAV_ABOUT),
        InlineKeyboardButton(text="Правила клуба", callback_data=NAV_RULES),
    )
    b.row(InlineKeyboardButton(text="Поддержка", callback_data=NAV_SUPPORT))
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


# ── Мероприятия (этап 13) ────────────────────────────────────────────────────
def events_list_kb(events: list) -> InlineKeyboardMarkup:
    """Список событий: по кнопке на событие (название · дата) + «Назад» в меню."""
    b = InlineKeyboardBuilder()
    for e in events:
        b.row(
            InlineKeyboardButton(
                text=f"{e['title']} · {e['starts_at']:%d.%m}",
                callback_data=f"{EVT_OPEN}:{e['id']}",
            )
        )
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_MENU))
    return b.as_markup()


def event_tickets_kb(
    event_id: int, items: list[tuple[str, int, bool]]
) -> InlineKeyboardMarkup:
    """Меню типов билетов события.

    `items` — `(ticket_type, price, available)` из services.events.seat_availability.
    Доступный тип → переход к покупке; без мест → попап «Мест нет» (EVT_FULL).
    """
    from .services import events as ev
    from .utils import fmt_price

    b = InlineKeyboardBuilder()
    for ttype, price, available in items:
        label = ev.ticket_label(ttype)
        if available:
            b.row(
                InlineKeyboardButton(
                    text=f"{label} — {fmt_price(price)} ₽",
                    callback_data=f"{EVT_BUY}:{event_id}:{ttype}",
                )
            )
        else:
            b.row(
                InlineKeyboardButton(
                    text=f"{label} — мест нет",
                    callback_data=EVT_FULL,
                )
            )
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_EVENTS))
    return b.as_markup()


def event_sold_out_kb(support_url: str | None) -> InlineKeyboardMarkup:
    """Событие распродано: «Запрос в Поддержку» (если ссылка задана) + «Назад»."""
    b = InlineKeyboardBuilder()
    if support_url:
        b.row(InlineKeyboardButton(text="Запрос в Поддержку", url=support_url))
    else:
        b.row(InlineKeyboardButton(text="Запрос в Поддержку", callback_data=NAV_SUPPORT))
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_EVENTS))
    return b.as_markup()


def event_ticket_summary_kb(event_id: int) -> InlineKeyboardMarkup:
    """Сводка по выбранному билету (оплата — этап 14): «Назад» к билетам события."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Назад", callback_data=f"{EVT_OPEN}:{event_id}"))
    return b.as_markup()
