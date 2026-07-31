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

# Согласие на обработку персональных данных (этап 49, 152-ФЗ).
PD_AGREE = "pd:agree"  # нажатие «Согласен» на экране согласия при первом входе

# Разделы тарифов/оплаты/промокодов (на этапе 1 — заглушки, наполнятся позже).
NAV_JOIN = "nav:join"        # Вступить в клуб → выбор тарифа
NAV_TARIFF = "nav:tariff"    # Выбрать тариф
NAV_MYSUB = "nav:mysub"      # Моя подписка
NAV_RENEW = "nav:renew"      # Продлить подписку
NAV_PROMO = "nav:promo"      # Ввести промокод
NAV_EVENTS = "nav:events"    # Мероприятия (все виды) — совместимость со старыми кнопками
NAV_BANYA = "nav:banya"      # Бани — события kind=banya (этап 39)
NAV_RETREAT = "nav:retreat"  # Ретриты — события kind=retreat (этап 39)
NAV_YOGA = "nav:yoga"        # Йога (этап 46; на этапе 39 кнопка скрыта)
NAV_CONSULT = "nav:consult"  # Консультации (этап 47; на этапе 39 кнопка скрыта)
NAV_REFERRAL = "nav:referral"  # Пригласить друга / моя реф-ссылка (этап 17)
NAV_MYTICKETS = "nav:mytickets"  # Мои билеты (этап 18)
NAV_BONUSES = "nav:bonuses"  # Мои бонусы: активные · скоро начислится · всего (этап 41)

# Услуги «по количеству»: йога (этап 46). Раздел открывается по NAV_YOGA.
YPROD = "yprod"          # yprod:{product_id} — выбрать формат → выбор количества
YQTY = "yqty"            # yqty:{product_id}:{qty} — выбрано количество → сводка
YPAY = "ypay"            # ypay:{product_id}:{qty} — создать платёж
YCHECK = "ycheck"        # ycheck:{yk_id} — проверить оплату услуги
YCANCEL = "ycancel"      # ycancel:{yk_id} — отменить незавершённый платёж
# Количества для выбора в разделе услуг (инлайн-кнопки).
QUANTITY_CHOICES: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8)

# Консультации: пакеты 1/4/8/12 (этап 47). Раздел открывается по NAV_CONSULT.
# Покупается один пакет (количество = 1), но цена пересчитывается со скидкой/промо/
# бонусами — поэтому callback'и оплаты/тоггла несут promo_id и флаг бонусов.
CPKG = "cpkg"        # cpkg:{product_id} — выбрать пакет → сводка
CPROMO = "cpromo"    # cpromo:{product_id} — ввести промокод для пакета
CBONUS = "cbonus"    # cbonus:{product_id}:{promo_or_0}:{1|0} — тоггл бонусов
CPAY = "cpay"        # cpay:{product_id}:{promo_or_0}:{1|0} — создать платёж
CCHECK = "ccheck"    # ccheck:{yk_id} — проверить оплату пакета
CCANCEL = "ccancel"  # ccancel:{yk_id} — отменить платёж + вернуть бонусы

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

# Клавиатура стартового экрана (welcome_kb) переехала в services.menu — она стала
# DB-управляемой (переименование/скрытие кнопок из веб-админки, этап 19). Отдельного
# «Главного меню» больше нет (этап 38): NAV_MENU оставлен алиасом NAV_START для
# старых сообщений, новые кнопки ведут на NAV_START. Здесь — вторичные экраны и NAV_*.


def pd_consent_kb() -> InlineKeyboardMarkup:
    """Экран согласия на обработку ПД (этап 49): единственная кнопка «Согласен».

    Тупика нет — без согласия пользователь не проходит дальше стартового экрана,
    поэтому «Назад»/меню тут не даём (обход гейта). Текст «Политики» — над кнопкой.
    """
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Согласен", callback_data=PD_AGREE))
    return b.as_markup()


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
    """Экран реф-ссылки: поделиться (готовый текст приглашения) + бонусы + в меню."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="Поделиться приглашением",
        switch_inline_query=f" {share_url}",
    ))
    b.row(InlineKeyboardButton(text="Мои бонусы", callback_data=NAV_BONUSES))
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_START))
    return b.as_markup()


def bonuses_kb() -> InlineKeyboardMarkup:
    """Экран «Мои бонусы» (этап 41): позвать друга (растит баланс) + в меню."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Пригласить друга", callback_data=NAV_REFERRAL))
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_START))
    return b.as_markup()


def bonus_accrued_kb() -> InlineKeyboardMarkup:
    """Автосообщение о бонусах (этап 41): не тупик — «Мои бонусы» · «Главное меню»."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Мои бонусы", callback_data=NAV_BONUSES))
    b.row(InlineKeyboardButton(text="Главное меню", callback_data=NAV_START))
    return b.as_markup()


def event_reminder_kb() -> InlineKeyboardMarkup:
    """Автонапоминание о событии (этап 41): «Мои билеты» — сразу к билету."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Мои билеты", callback_data=NAV_MYTICKETS))
    b.row(InlineKeyboardButton(text="Главное меню", callback_data=NAV_START))
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
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_START))
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
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_START))
    return b.as_markup()


# ── Мероприятия (этап 13) ────────────────────────────────────────────────────
def events_nav_for_kind(kind: str | None) -> str:
    """Callback списка мероприятий для вида события (этап 39).

    Кнопки «Назад»/«К мероприятиям» из карточки события возвращают в тот же
    раздел, откуда пришли: баня → «Бани», ретрит → «Ретриты», иначе — общий
    список (совместимость).
    """
    from .services import events as ev
    if kind == ev.KIND_BANYA:
        return NAV_BANYA
    if kind == ev.KIND_RETREAT:
        return NAV_RETREAT
    return NAV_EVENTS


def events_list_kb(groups: list, sold_out_ids: set | None = None) -> InlineKeyboardMarkup:
    """Список событий: кнопка на событие с подписью типа (Тип · Название · дата).

    `groups` — `(kind_short, [event_record])` в порядке показа. Тип в подписи,
    чтобы в списке было видно, где баня, а где ретрит. Распроданные события
    (`sold_out_ids`, этап 38) остаются в списке с пометкой «· мест нет».
    + «Назад» в меню.
    """
    sold_out = sold_out_ids or set()
    b = InlineKeyboardBuilder()
    for kind_short, events in groups:
        for e in events:
            suffix = " · мест нет" if e["id"] in sold_out else ""
            b.row(
                InlineKeyboardButton(
                    text=f"{kind_short} · {e['title']} · {e['starts_at']:%d.%m}{suffix}",
                    callback_data=f"{EVT_OPEN}:{e['id']}",
                )
            )
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_START))
    return b.as_markup()


def event_tickets_kb(
    event_id: int, items: list[tuple[str, int, bool]], back_cb: str = NAV_EVENTS
) -> InlineKeyboardMarkup:
    """Меню типов билетов события.

    `items` — `(ticket_type, price, available)` из services.events.seat_availability.
    Доступный тип → переход к покупке; без мест → попап «Мест нет» (EVT_FULL).
    `back_cb` (этап 39) — куда ведёт «Назад»: список бань/ретритов по виду события.
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
    b.row(InlineKeyboardButton(text="Назад", callback_data=back_cb))
    return b.as_markup()


def event_sold_out_kb(support_url: str | None, back_cb: str = NAV_EVENTS) -> InlineKeyboardMarkup:
    """Событие распродано: «Запрос в Поддержку» (если ссылка задана) + «Назад»."""
    b = InlineKeyboardBuilder()
    if support_url:
        b.row(InlineKeyboardButton(text="Запрос в Поддержку", url=support_url))
    else:
        b.row(InlineKeyboardButton(text="Запрос в Поддержку", callback_data=NAV_SUPPORT))
    b.row(InlineKeyboardButton(text="Назад", callback_data=back_cb))
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
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_START))
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
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_START))
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


def ticket_address_kb(back_cb: str = NAV_EVENTS) -> InlineKeyboardMarkup:
    """После показа адреса: к списку мероприятий (по виду события) + в главное меню."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="К мероприятиям", callback_data=back_cb))
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_START))
    return b.as_markup()


# ── Йога: услуги «по количеству» (этап 46) ───────────────────────────────────
def yoga_products_kb(products: list) -> InlineKeyboardMarkup:
    """Раздел «Йога»: кнопка на каждый активный продукт (формат — цена) + «Назад».

    `products` — записи service_products (поля id/title/price). Цена в подписи —
    базовая за занятие; скидка участника применяется на экране количества/сводки.
    """
    from .utils import fmt_price

    b = InlineKeyboardBuilder()
    for p in products:
        b.row(InlineKeyboardButton(
            text=f"{p['title']} — {fmt_price(p['price'])} ₽",
            callback_data=f"{YPROD}:{p['id']}",
        ))
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_START))
    return b.as_markup()


def yoga_quantity_kb(product_id: int) -> InlineKeyboardMarkup:
    """Выбор количества занятий: инлайн-кнопки 1..8 + «Назад» к списку форматов."""
    b = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for n in QUANTITY_CHOICES:
        row.append(InlineKeyboardButton(text=str(n), callback_data=f"{YQTY}:{product_id}:{n}"))
        if len(row) == 4:
            b.row(*row)
            row = []
    if row:
        b.row(*row)
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_YOGA))
    return b.as_markup()


def service_summary_kb(product_id: int, quantity: int) -> InlineKeyboardMarkup:
    """Сводка услуги: оплата + изменить количество + «Назад» в раздел."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="Перейти к оплате", callback_data=f"{YPAY}:{product_id}:{quantity}"
    ))
    b.row(InlineKeyboardButton(
        text="Изменить количество", callback_data=f"{YPROD}:{product_id}"
    ))
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_YOGA))
    return b.as_markup()


def service_pay_kb(confirmation_url: str | None, yk_id: str) -> InlineKeyboardMarkup:
    """Экран оплаты услуги: «Оплатить» (ссылка) + «Проверить оплату» + «Отмена»."""
    b = InlineKeyboardBuilder()
    if confirmation_url:
        b.row(InlineKeyboardButton(text="Оплатить", url=confirmation_url))
    b.row(InlineKeyboardButton(text="Проверить оплату", callback_data=f"{YCHECK}:{yk_id}"))
    b.row(InlineKeyboardButton(text="Отмена", callback_data=f"{YCANCEL}:{yk_id}"))
    return b.as_markup()


def service_paid_kb(manager_url: str | None) -> InlineKeyboardMarkup:
    """Услуга оплачена: «Написать менеджеру» (ссылка) + «В главное меню»."""
    b = InlineKeyboardBuilder()
    if manager_url:
        b.row(InlineKeyboardButton(text="Написать менеджеру", url=manager_url))
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_START))
    return b.as_markup()


def service_canceled_kb() -> InlineKeyboardMarkup:
    """После отмены платежа услуги: вернуться в раздел «Йога» + в меню."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Вернуться в раздел", callback_data=NAV_YOGA))
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_START))
    return b.as_markup()


# ── Консультации: пакеты со скидками/промо/бонусами (этап 47) ─────────────────
def consult_packages_kb(products: list) -> InlineKeyboardMarkup:
    """Раздел «Консультации»: кнопка на каждый активный пакет (пакет — цена) + «Назад».

    `products` — записи service_products (поля id/title/price). Цена в подписи —
    базовая за пакет; скидка участника/промокод/бонусы применяются на экране сводки.
    """
    from .utils import fmt_price

    b = InlineKeyboardBuilder()
    for p in products:
        b.row(InlineKeyboardButton(
            text=f"{p['title']} — {fmt_price(p['price'])} ₽",
            callback_data=f"{CPKG}:{p['id']}",
        ))
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_START))
    return b.as_markup()


def consult_summary_kb(
    product_id: int, promo_id: int | None = None,
    *, use_bonus: bool = False, bonus_cap: int = 0,
) -> InlineKeyboardMarkup:
    """Сводка по пакету консультаций: оплата + тоггл бонусов + промокод + «Назад».

    Промокод и флаг бонусов зашиты в callback оплаты/тоггла (источник истины —
    пересчёт при создании платежа). bonus_cap>0 → показываем тоггл «Списать бонусы».
    """
    b = InlineKeyboardBuilder()
    promo_part = promo_id if promo_id is not None else 0
    pay_cb = f"{CPAY}:{product_id}:{promo_part}:{1 if use_bonus else 0}"
    b.row(InlineKeyboardButton(text="Перейти к оплате", callback_data=pay_cb))
    if bonus_cap > 0:
        if use_bonus:
            b.row(InlineKeyboardButton(
                text="Не списывать бонусы",
                callback_data=f"{CBONUS}:{product_id}:{promo_part}:0",
            ))
        else:
            b.row(InlineKeyboardButton(
                text=f"Списать бонусы (−{bonus_cap} ₽)",
                callback_data=f"{CBONUS}:{product_id}:{promo_part}:1",
            ))
    promo_label = "Ввести другой промокод" if promo_id is not None else "Ввести промокод"
    b.row(InlineKeyboardButton(text=promo_label, callback_data=f"{CPROMO}:{product_id}"))
    b.row(InlineKeyboardButton(text="Назад", callback_data=NAV_CONSULT))
    return b.as_markup()


def consult_promo_enter_kb(product_id: int) -> InlineKeyboardMarkup:
    """Экран ввода промокода для пакета: «Отмена» возвращает к сводке пакета."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Отмена", callback_data=f"{CPKG}:{product_id}"))
    return b.as_markup()


def consult_promo_retry_kb(product_id: int) -> InlineKeyboardMarkup:
    """Промокод не подошёл: ввести ещё раз / продолжить без него / в меню."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="Ввести промокод ещё раз", callback_data=f"{CPROMO}:{product_id}"
    ))
    b.row(InlineKeyboardButton(
        text="Продолжить без промокода", callback_data=f"{CPKG}:{product_id}"
    ))
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_START))
    return b.as_markup()


def consult_pay_kb(confirmation_url: str | None, yk_id: str) -> InlineKeyboardMarkup:
    """Экран оплаты пакета: «Оплатить» (ссылка) + «Проверить оплату» + «Отмена».

    «Отмена» отменяет незавершённый платёж и возвращает списанные бонусы (этап 47).
    """
    b = InlineKeyboardBuilder()
    if confirmation_url:
        b.row(InlineKeyboardButton(text="Оплатить", url=confirmation_url))
    b.row(InlineKeyboardButton(text="Проверить оплату", callback_data=f"{CCHECK}:{yk_id}"))
    b.row(InlineKeyboardButton(text="Отмена", callback_data=f"{CCANCEL}:{yk_id}"))
    return b.as_markup()


def consult_canceled_kb() -> InlineKeyboardMarkup:
    """После отмены платежа пакета: вернуться в раздел «Консультации» + в меню."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Вернуться в раздел", callback_data=NAV_CONSULT))
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_START))
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
    b.row(InlineKeyboardButton(text="В главное меню", callback_data=NAV_START))
    return b.as_markup()


def ticket_detail_kb(ticket_id: int, refund_requested: bool = False) -> InlineKeyboardMarkup:
    """Карточка билета: поддержка · назад. Адрес/правила уже на экране.

    Кнопки «Запросить возврат» больше нет (этап 38) — возвраты только через
    менеджера, поэтому вместо неё «Поддержка». Кнопки «Перенос» тоже нет.
    `refund_requested` больше не влияет на раскладку (оставлен для совместимости
    вызова).
    """
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Поддержка", callback_data=NAV_SUPPORT))
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
