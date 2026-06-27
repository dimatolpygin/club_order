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
NAV_ABOUTMENU = "nav:aboutmenu"  # Подменю «О клубе» (этап 31): что внутри/правила/пригласить

# Разделы тарифов/оплаты/промокодов (на этапе 1 — заглушки, наполнятся позже).
NAV_JOIN = "nav:join"        # Вступить в клуб → выбор тарифа
NAV_TARIFF = "nav:tariff"    # Выбрать тариф
NAV_MYSUB = "nav:mysub"      # Моя подписка
NAV_RENEW = "nav:renew"      # Продлить подписку
NAV_PROMO = "nav:promo"      # Ввести промокод
NAV_EVENTS = "nav:events"    # Мероприятия (билеты «Фокус.Энергия», этап 13)
NAV_REFERRAL = "nav:referral"  # Пригласить друга / моя реф-ссылка (этап 17)
NAV_MYTICKETS = "nav:mytickets"  # Мои билеты (этап 18)

# Раздел «Мои билеты» (этап 18).
MYT_OPEN = "myt"             # myt:{ticket_id} — карточка билета
MYT_REFUND = "mytref"        # mytref:{ticket_id} — запрос на возврат (подтверждение)
MYT_REFUND_OK = "mytrefok"   # mytrefok:{ticket_id} — подтвердить запрос на возврат

# Префиксы callback'ов раздела мероприятий.
EVT_OPEN = "evt"             # evt:{event_id} — открыть карточку события
EVT_BUY = "evtbuy"           # evtbuy:{event_id}:{ticket_type} — выбрать билет
EVT_FULL = "evtfull"         # тап по типу без мест — попап «Мест нет»
# Оплата билета и выдача (этап 14).
# tpay:create:{event_id}:{ticket_type}[:{promo_id}] — создать платёж (promo_id опц., этап 16)
TPAY_CREATE = "tpay:create"
TPAY_CHECK = "tpay:check"    # tpay:check:{yk_id} — проверить оплату билета
TPAY_CANCEL = "tpay:cancel"  # tpay:cancel:{yk_id} — отменить платёж + вернуть бонусы (этап 17)
TAGREE = "tagree"            # tagree:{ticket_id} — согласие с правилами → адрес
# Промокод на билете (этап 16).
TPROMO = "tpromo"            # tpromo:{event_id}:{ticket_type} — ввести промокод для билета
# Оплата бонусами на билете (этап 17).
TBONUS = "tbonus"            # tbonus:{event_id}:{ticket_type}:{promo_or_0}:{1|0} — тоггл бонусов

# Клавиатуры приветствия (welcome_kb) и главного меню (main_menu_kb) переехали в
# services.menu — они стали DB-управляемыми (переименование/скрытие кнопок из
# веб-админки, этап 19). Здесь остаются вторичные экраны и константы NAV_*.


def about_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Выбрать тариф", callback_data=NAV_TARIFF))
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_ABOUTMENU))
    return b.as_markup()


def rules_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Вступить в клуб", callback_data=NAV_JOIN))
    b.row(InlineKeyboardButton(text="Моя подписка", callback_data=NAV_MYSUB))
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_ABOUTMENU))
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


def referral_link_kb(share_url: str) -> InlineKeyboardMarkup:
    """Экран реф-ссылки: поделиться (готовый текст приглашения) + в меню."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="Поделиться приглашением",
        switch_inline_query=f" {share_url}",
    ))
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_MENU))
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
def events_list_kb(groups: list) -> InlineKeyboardMarkup:
    """Список событий: кнопка на событие с подписью типа (Тип · Название · дата).

    `groups` — `(kind_short, [event_record])` в порядке показа. Тип в подписи,
    чтобы в списке было видно, где баня, а где ретрит. + «Назад» в меню.
    """
    b = InlineKeyboardBuilder()
    for kind_short, events in groups:
        for e in events:
            b.row(
                InlineKeyboardButton(
                    text=f"{kind_short} · {e['title']} · {e['starts_at']:%d.%m}",
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


def event_ticket_summary_kb(
    event_id: int, ticket_type: str, promo_id: int | None = None,
    *, use_bonus: bool = False, bonus_cap: int = 0,
) -> InlineKeyboardMarkup:
    """Сводка по билету: оплата + тоггл бонусов + промокод + «Назад».

    promo_id (этап 16) — применённый промокод зашивается в callback оплаты.
    bonus_cap>0 (этап 17) — показываем тоггл «Списать бонусы»; use_bonus — текущее
    состояние. Pay-callback несёт и промокод, и флаг бонусов (источник истины —
    пересчёт при создании платежа).
    """
    b = InlineKeyboardBuilder()
    promo_part = promo_id if promo_id is not None else 0
    pay_cb = f"{TPAY_CREATE}:{event_id}:{ticket_type}:{promo_part}:{1 if use_bonus else 0}"
    b.row(InlineKeyboardButton(text="Перейти к оплате", callback_data=pay_cb))
    if bonus_cap > 0:
        if use_bonus:
            b.row(InlineKeyboardButton(
                text="Не списывать бонусы",
                callback_data=f"{TBONUS}:{event_id}:{ticket_type}:{promo_part}:0",
            ))
        else:
            b.row(InlineKeyboardButton(
                text=f"Списать бонусы (−{bonus_cap} ₽)",
                callback_data=f"{TBONUS}:{event_id}:{ticket_type}:{promo_part}:1",
            ))
    promo_label = "Ввести другой промокод" if promo_id is not None else "Ввести промокод"
    b.row(InlineKeyboardButton(
        text=promo_label, callback_data=f"{TPROMO}:{event_id}:{ticket_type}"
    ))
    b.row(InlineKeyboardButton(text="Назад", callback_data=f"{EVT_OPEN}:{event_id}"))
    return b.as_markup()


def ticket_promo_enter_kb(event_id: int, ticket_type: str) -> InlineKeyboardMarkup:
    """Экран ввода промокода для билета: «Отмена» возвращает к сводке билета."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="Отмена", callback_data=f"{EVT_BUY}:{event_id}:{ticket_type}"
    ))
    return b.as_markup()


def ticket_promo_retry_kb(event_id: int, ticket_type: str) -> InlineKeyboardMarkup:
    """Промокод не подошёл: ввести ещё раз / продолжить без него / в меню."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="Ввести промокод ещё раз", callback_data=f"{TPROMO}:{event_id}:{ticket_type}"
    ))
    b.row(InlineKeyboardButton(
        text="Продолжить без промокода", callback_data=f"{EVT_BUY}:{event_id}:{ticket_type}"
    ))
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_MENU))
    return b.as_markup()


def ticket_pay_kb(confirmation_url: str | None, yk_id: str, event_id: int) -> InlineKeyboardMarkup:
    """Экран оплаты билета: «Оплатить» (ссылка) + «Проверить оплату» + «Отмена».

    «Отмена» отменяет незавершённый платёж и возвращает списанные бонусы (этап 17),
    а не просто уводит назад — иначе зарезервированные бонусы «зависали» бы до таймаута.
    """
    b = InlineKeyboardBuilder()
    if confirmation_url:
        b.row(InlineKeyboardButton(text="Оплатить", url=confirmation_url))
    b.row(InlineKeyboardButton(text="Проверить оплату", callback_data=f"{TPAY_CHECK}:{yk_id}"))
    b.row(InlineKeyboardButton(text="Отмена", callback_data=f"{TPAY_CANCEL}:{yk_id}"))
    return b.as_markup()


def ticket_canceled_kb(event_id: int) -> InlineKeyboardMarkup:
    """После отмены платежа: вернуться к билетам события + в меню."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Вернуться к билетам", callback_data=f"{EVT_OPEN}:{event_id}"))
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_MENU))
    return b.as_markup()


def ticket_rules_kb(ticket_id: int) -> InlineKeyboardMarkup:
    """Экран правил после оплаты: согласие (→ адрес) + «Есть вопросы» (поддержка)."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="С правилами согласен (показать адрес)",
        callback_data=f"{TAGREE}:{ticket_id}",
    ))
    b.row(InlineKeyboardButton(text="Есть вопросы", callback_data=NAV_SUPPORT))
    return b.as_markup()


def ticket_address_kb() -> InlineKeyboardMarkup:
    """После показа адреса: к списку мероприятий + в главное меню."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="К мероприятиям", callback_data=NAV_EVENTS))
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_MENU))
    return b.as_markup()


# ── Мои билеты (этап 18) ──────────────────────────────────────────────────────
def my_tickets_kb(tickets: list) -> InlineKeyboardMarkup:
    """Список активных билетов: кнопка на каждый билет (Название · дата) + меню.

    `tickets` — записи из repo.list_active_tickets (поля title/starts_at/id).
    """
    b = InlineKeyboardBuilder()
    for t in tickets:
        # У билета с запрошенным возвратом — метка прямо в подписи кнопки.
        suffix = " — возврат запрошен" if t["refund_requested"] else ""
        # Номер билета (этап 33) — чтобы покупатель мог назвать его менеджеру.
        b.row(
            InlineKeyboardButton(
                text=f"№{t['id']} · {t['title']} · {t['starts_at']:%d.%m}{suffix}",
                callback_data=f"{MYT_OPEN}:{t['id']}",
            )
        )
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_MENU))
    return b.as_markup()


def ticket_detail_kb(ticket_id: int, refund_requested: bool = False) -> InlineKeyboardMarkup:
    """Карточка билета: запрос возврата · назад. Адрес/правила уже на экране.

    Если возврат уже запрошен — кнопку запроса убираем (нельзя слать повторно).
    Кнопки «Перенос» нет (решение заказчика).
    """
    b = InlineKeyboardBuilder()
    if not refund_requested:
        b.row(InlineKeyboardButton(
            text="Запросить возврат", callback_data=f"{MYT_REFUND}:{ticket_id}"
        ))
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_MYTICKETS))
    return b.as_markup()


def ticket_refund_confirm_kb(ticket_id: int) -> InlineKeyboardMarkup:
    """Подтверждение запроса на возврат: отправить менеджеру / назад к билету."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="Да, запросить возврат", callback_data=f"{MYT_REFUND_OK}:{ticket_id}"
    ))
    b.row(InlineKeyboardButton(
        text="Назад", callback_data=f"{MYT_OPEN}:{ticket_id}"
    ))
    return b.as_markup()
