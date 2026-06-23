"""Раздел «Мероприятия» в боте (этап 13): показ событий + выбор билета.

Поверх данных этапа 12 (`events` + `event_ticket_prices`). Правила показа и
доступность мест — в services.events (чистая логика, покрыта smoke-тестом).
Оплата билета и учёт проданных мест — этап 14.
"""
from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
import asyncpg

from .. import keyboards as kb
from .. import repo, texts
from ..logger import logger
from ..services import app_settings
from ..services import events as ev
from ..services import promo as promo_service
from ..services import tickets
from ..services.yookassa import YooKassaError
from ..states import TicketPromoStates
from ..utils import fmt_price
from .payment import _return_url

router = Router()


async def _edit(cb: CallbackQuery, text: str, markup) -> None:
    with suppress(TelegramBadRequest):  # «message is not modified» — не критично
        await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


async def _subscriber_discount(pool: asyncpg.Pool, tg_id: int, event) -> int:
    """Скидка участника клуба на событие, % (0 — если нет активной подписки)."""
    is_subscriber = await repo.get_active_subscription(pool, tg_id) is not None
    return event["subscriber_discount_percent"] if is_subscriber else 0


def _price_block(pr: dict) -> str:
    """Разбивка цены билета: скидка (зачёркнутая база) + бонусы + итог (этапы 15–17)."""
    base = fmt_price(pr["base_price"])
    disc = fmt_price(pr["price_after_discount"])
    lines: list[str] = []
    if pr["price_after_discount"] < pr["base_price"]:
        applied = pr["applied"]
        if applied == "promo":
            label = f"По промокоду {pr['promo']['code']} −{pr['discount_pct']}%"
        elif applied == "subscriber":
            label = f"Скидка участника −{pr['discount_pct']}%"
        elif applied == "referral":
            label = f"Скидка новичка −{pr['referral_amount']} ₽"
        else:
            label = "Скидка"
        lines.append(f"Цена: <s>{base} ₽</s>")
        lines.append(f"<b>{label}: {disc} ₽</b>")
    else:
        lines.append(f"<b>Стоимость: {disc} ₽</b>")
    if pr["bonus_used"]:
        lines.append(f"Бонусами: <b>−{pr['bonus_used']} ₽</b>")
        lines.append(f"<b>Итого к оплате: {fmt_price(pr['final'])} ₽</b>")
    elif pr["bonus_cap"] > 0:
        lines.append(
            f"<i>Доступно бонусов: {pr['balance']} ₽ — можно списать до "
            f"{pr['bonus_cap']} ₽ (до 50% цены)</i>"
        )
    return "\n".join(lines) + "\n"


async def _ticket_summary_view(
    pool: asyncpg.Pool, tg_id: int, event, ttype: str, prices,
    *, promo_id: int | None = None, use_bonus: bool = False,
):
    """Готовит (text, markup, pr) сводки билета (этапы 15–17).

    Скидки (подписчик/промокод/новичок) НЕ суммируются — берётся максимальная;
    бонусы добивают цену (≤50%). Расчёт — единый `tickets.compute_ticket_pricing`
    (тот же, что при создании платежа), поэтому показ и оплата всегда совпадают.
    """
    pr = await tickets.compute_ticket_pricing(
        pool, tg_id=tg_id, event=event, ticket_type=ttype,
        base_price=prices[ttype], promo_id=promo_id, use_bonus=use_bonus,
    )
    # Промокод введён, но выгоднее другая скидка — поясняем (его не применяем).
    note = ""
    if promo_id is not None and pr["applied"] != "promo" and pr["promo"] is not None:
        note = (
            "<i>Промокод применён, но другая скидка выгоднее — оставили её "
            "(скидки не суммируются).</i>\n\n"
        )
    text = texts.event_ticket_summary(
        event["title"], ev.ticket_label(ttype), _price_block(pr), note
    )
    applied_promo_id = pr["applied_promo_id"]
    markup = kb.event_ticket_summary_kb(
        event["id"], ttype, applied_promo_id,
        use_bonus=use_bonus and pr["bonus_used"] > 0, bonus_cap=pr["bonus_cap"],
    )
    return text, markup, pr


# ── Список мероприятий ───────────────────────────────────────────────────────
@router.callback_query(F.data == kb.NAV_EVENTS)
async def show_events(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    await repo.set_fsm_state(pool, cb.from_user.id, "screen:events")

    rows = await repo.list_events(pool)
    # Полностью распроданные события скрываем (иначе распроданная баня заняла бы
    # слот «ближайшей» и спрятала следующую доступную). Цены и продажи — пакетно.
    prices_all = await repo.prices_by_event(pool)
    counts_all = await repo.ticket_counts_by_event(pool)
    sold_out_ids = {
        e["id"] for e in rows
        if not ev.event_available(
            e, prices_all.get(e["id"], {}), ev.seats_occupied(counts_all.get(e["id"], {}))
        )
    }
    visible = ev.visible_events(rows, datetime.now(timezone.utc), sold_out_ids)
    if not visible:
        await _edit(cb, texts.EVENTS_NONE, kb.to_menu_kb())
        logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: мероприятия (пусто)")
        return

    grouped = ev.group_by_kind(visible)
    text = texts.events_list([(ev.kind_label(k), evs) for k, evs in grouped])
    markup = kb.events_list_kb([(ev.kind_short(k), evs) for k, evs in grouped])
    await _edit(cb, text, markup)
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: мероприятия — {len(visible)} событ. "
        f"({len(grouped)} групп)"
    )


# ── Карточка события: меню типов билетов ─────────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.EVT_OPEN}:"))
async def show_event(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    event_id = int(cb.data.split(":", 1)[1])
    event = await repo.get_event(pool, event_id)
    if event is None or not event["is_active"]:
        await _edit(cb, texts.EVENTS_NONE, kb.to_menu_kb())
        return

    await repo.set_fsm_state(pool, cb.from_user.id, f"screen:event:{event_id}")
    prices = await repo.get_event_prices(pool, event_id)
    counts = await repo.get_event_ticket_counts(pool, event_id)
    items = ev.seat_availability(event, prices, ev.seats_occupied(counts))

    # Ни одного типа со свободными местами (или вовсе без цен) → «Мест нет».
    if not any(available for _, _, available in items):
        url = await app_settings.support_url(pool)
        await _edit(cb, texts.EVENT_SOLD_OUT, kb.event_sold_out_kb(url or None))
        logger.info(
            f"🤖 Бот → @{cb.from_user.username or '—'}: событие «{event['title']}» — мест нет"
        )
        return

    # Скидка участника клуба (этап 15): активная подписка → цена со скидкой события.
    discount_pct = await _subscriber_discount(pool, cb.from_user.id, event)
    display_items = [
        (ttype, ev.apply_discount(price, discount_pct), available)
        for ttype, price, available in items
    ]
    # Для подписчика — разбивка со зачёркнутой старой ценой (в кнопках зачёркивание
    # невозможно, поэтому показываем «старая → новая» в тексте карточки).
    price_lines = None
    if discount_pct > 0:
        price_lines = [
            f"{ev.ticket_label(ttype)}: <s>{fmt_price(old)} ₽</s> → "
            f"<b>{fmt_price(new)} ₽</b>"
            for (ttype, old, avail), (_, new, _) in zip(items, display_items)
            if avail
        ]
    text = texts.event_card(
        ev.kind_label(event["kind"]), event["title"], event["starts_at"],
        discount_pct, price_lines,
    )
    await _edit(cb, text, kb.event_tickets_kb(event_id, display_items))
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: событие «{event['title']}», "
        f"{len(items)} тип(ов) билетов, скидка участника {discount_pct}%"
    )


# ── Тап по типу без мест ─────────────────────────────────────────────────────
@router.callback_query(F.data == kb.EVT_FULL)
async def ticket_sold_out(cb: CallbackQuery) -> None:
    await cb.answer("Мест нет. Напиши в поддержку — подскажем по свободным местам.", show_alert=True)


# ── Выбор билета: сводка (оплата — этап 14) ──────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.EVT_BUY}:"))
async def choose_ticket(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()  # сбрасываем возможный незавершённый ввод промокода
    _, event_id_raw, ttype = cb.data.split(":", 2)
    event_id = int(event_id_raw)
    event = await repo.get_event(pool, event_id)
    if event is None or not event["is_active"]:
        await _edit(cb, texts.EVENTS_NONE, kb.to_menu_kb())
        return

    prices = await repo.get_event_prices(pool, event_id)
    # Повторно проверяем доступность типа (мог распродаться между экранами).
    if ttype not in prices or not ev.has_seats(event, ttype):
        await cb.answer("Мест нет на этот тип билета.", show_alert=True)
        return

    await repo.set_fsm_state(pool, cb.from_user.id, f"screen:ticket:{event_id}:{ttype}")
    text, markup, pr = await _ticket_summary_view(
        pool, cb.from_user.id, event, ttype, prices
    )
    await _edit(cb, text, markup)
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: выбран билет {ttype} на "
        f"«{event['title']}» — {fmt_price(pr['final'])} ₽ (скидка: {pr['applied']})"
    )


# ── Ввод промокода для билета (этап 16) ──────────────────────────────────────
# Сообщение на каждый невалидный статус промокода в флоу билета.
_TPROMO_FAIL = {
    promo_service.NOT_FOUND: texts.TICKET_PROMO_NOT_FOUND,
    promo_service.EXPIRED: texts.TICKET_PROMO_EXPIRED,
    promo_service.EXHAUSTED: texts.TICKET_PROMO_EXHAUSTED,
    promo_service.ALREADY_USED: texts.TICKET_PROMO_ALREADY_USED,
}


@router.callback_query(F.data.startswith(f"{kb.TPROMO}:"))
async def ticket_promo_enter(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    _, event_id_raw, ttype = cb.data.split(":", 2)
    event_id = int(event_id_raw)
    await state.set_state(TicketPromoStates.waiting_code)
    await state.update_data(event_id=event_id, ticket_type=ttype)
    await repo.set_fsm_state(pool, cb.from_user.id, f"screen:ticket:promo:{event_id}:{ttype}")
    await _edit(cb, texts.TICKET_PROMO_ENTER, kb.ticket_promo_enter_kb(event_id, ttype))
    logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: ввод промокода на билет")


@router.message(TicketPromoStates.waiting_code)
async def ticket_promo_entered(
    message: Message, state: FSMContext, pool: asyncpg.Pool
) -> None:
    data = await state.get_data()
    event_id = data.get("event_id")
    ttype = data.get("ticket_type")
    await state.clear()
    if event_id is None or ttype is None:
        await message.answer(texts.EVENTS_NONE, reply_markup=kb.to_menu_kb())
        return

    event = await repo.get_event(pool, event_id)
    if event is None or not event["is_active"]:
        await message.answer(texts.EVENTS_NONE, reply_markup=kb.to_menu_kb())
        return
    prices = await repo.get_event_prices(pool, event_id)
    if ttype not in prices or not ev.has_seats(event, ttype):
        await message.answer(texts.EVENT_SOLD_OUT, reply_markup=kb.to_menu_kb())
        return

    code = promo_service.normalize_code(message.text)
    promo = await repo.get_promo_by_code(pool, code) if code else None
    already = (
        await repo.user_redeemed_promo(pool, promo["id"], message.from_user.id)
        if promo is not None else False
    )
    status = promo_service.validate(
        promo, now=datetime.now(timezone.utc), already_used=already
    )
    if status != promo_service.VALID:
        await message.answer(
            _TPROMO_FAIL[status], reply_markup=kb.ticket_promo_retry_kb(event_id, ttype)
        )
        logger.info(
            f"🤖 Бот → @{message.from_user.username or '—'}: промокод на билет «{code}» — {status}"
        )
        return
    # fixed_price-промокоды действуют только на подписку (этап 16).
    if promo["kind"] != promo_service.KIND_PERCENT:
        await message.answer(
            texts.TICKET_PROMO_SUB_ONLY, reply_markup=kb.ticket_promo_retry_kb(event_id, ttype)
        )
        logger.info(
            f"🤖 Бот → @{message.from_user.username or '—'}: промокод «{code}» — только для подписки"
        )
        return

    text, markup, pr = await _ticket_summary_view(
        pool, message.from_user.id, event, ttype, prices, promo_id=promo["id"]
    )
    await repo.set_fsm_state(pool, message.from_user.id, f"screen:ticket:{event_id}:{ttype}")
    await message.answer(text, reply_markup=markup)
    logger.info(
        f"🤖 Бот → @{message.from_user.username or '—'}: промокод «{code}» на билет — "
        f"{fmt_price(pr['final'])} ₽ (применено: {pr['applied']})"
    )


# ── Тоггл оплаты бонусами на сводке билета (этап 17) ─────────────────────────
def _parse_promo_part(raw: str) -> int | None:
    """promo_id из callback (0 — нет промокода)."""
    val = int(raw)
    return val if val != 0 else None


@router.callback_query(F.data.startswith(f"{kb.TBONUS}:"))
async def ticket_bonus_toggle(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    # callback: tbonus:{event_id}:{ticket_type}:{promo_or_0}:{1|0}
    _, event_id_raw, ttype, promo_raw, flag = cb.data.split(":", 4)
    event_id = int(event_id_raw)
    event = await repo.get_event(pool, event_id)
    if event is None or not event["is_active"]:
        await _edit(cb, texts.EVENTS_NONE, kb.to_menu_kb())
        return
    prices = await repo.get_event_prices(pool, event_id)
    if ttype not in prices or not ev.has_seats(event, ttype):
        await cb.answer("Мест нет на этот тип билета.", show_alert=True)
        return
    text, markup, pr = await _ticket_summary_view(
        pool, cb.from_user.id, event, ttype, prices,
        promo_id=_parse_promo_part(promo_raw), use_bonus=(flag == "1"),
    )
    await _edit(cb, text, markup)
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: бонусы {'вкл' if flag == '1' else 'выкл'} "
        f"на билет — итого {fmt_price(pr['final'])} ₽"
    )


# ── Создание платежа за билет ────────────────────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.TPAY_CREATE}:"))
async def ticket_pay_create(cb: CallbackQuery, bot: Bot, pool: asyncpg.Pool) -> None:
    # callback: tpay:create:{event_id}:{ticket_type}:{promo_or_0}:{1|0}
    parts = cb.data.split(":")
    event_id = int(parts[2])
    ttype = parts[3]
    promo_id = _parse_promo_part(parts[4]) if len(parts) > 4 else None
    use_bonus = len(parts) > 5 and parts[5] == "1"
    await cb.answer("Создаю платёж...")
    try:
        status, result = await tickets.start_ticket_payment(
            pool,
            tg_id=cb.from_user.id,
            event_id=event_id,
            ticket_type=ttype,
            return_url=await _return_url(bot),
            promo_id=promo_id,
            use_bonus=use_bonus,
        )
    except YooKassaError:
        await _edit(cb, texts.PAY_CREATE_FAILED, kb.to_menu_kb())
        return

    if status == "no_seats":
        url = await app_settings.support_url(pool)
        await _edit(cb, texts.EVENT_SOLD_OUT, kb.event_sold_out_kb(url or None))
        return
    if status == "bonus_failed":
        await cb.answer(
            "Не удалось списать бонусы — баланс изменился. Открой билет заново.",
            show_alert=True,
        )
        return
    if status == "free":
        await _edit(cb, texts.TICKET_FREE_SUPPORT, kb.to_menu_kb())
        return
    if status != "ok" or result is None:
        await _edit(cb, texts.EVENTS_NONE, kb.to_menu_kb())
        return

    await repo.set_fsm_state(pool, cb.from_user.id, "screen:ticket:pay")
    await _edit(
        cb,
        texts.ticket_pay_created(fmt_price(result["amount"])),
        kb.ticket_pay_kb(result["confirmation_url"], result["payment_id"], event_id),
    )
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: ссылка на оплату билета "
        f"{fmt_price(result['amount'])} ₽ (yk_id={result['payment_id']})"
    )


# ── Проверка оплаты билета вручную ───────────────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.TPAY_CHECK}:"))
async def ticket_pay_check(cb: CallbackQuery, bot: Bot, pool: asyncpg.Pool) -> None:
    yk_id = cb.data.split(":", 2)[2]
    payment = await repo.get_payment_by_yk_id(pool, yk_id)
    if payment is None:
        await cb.answer("Платёж не найден.", show_alert=True)
        return

    status, ticket = await tickets.sync_ticket_payment(pool, bot, payment, notify=False)
    if status == "succeeded" and ticket is not None:
        event = await repo.get_event(pool, ticket["event_id"])
        await repo.set_fsm_state(pool, cb.from_user.id, "screen:ticket:paid")
        await _edit(
            cb,
            texts.ticket_success(
                event["title"], ev.ticket_label(ticket["ticket_type"]),
                event["starts_at"], event["rules_text"],
            ),
            kb.ticket_rules_kb(ticket["id"]),
        )
        logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: билет оплачен (#{ticket['id']})")
    elif status in ("no_seats", "no_event"):
        text = texts.TICKET_NO_EVENT if status == "no_event" else texts.TICKET_SOLD_DURING
        await _edit(cb, text, kb.to_menu_kb())
    elif status == "canceled":
        await _edit(cb, texts.PAY_CANCELED, kb.to_menu_kb())
    else:
        await cb.answer(texts.PAY_STILL_PENDING, show_alert=True)


# ── Согласие с правилами → показать адрес ────────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.TAGREE}:"))
async def ticket_show_address(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    ticket_id = int(cb.data.split(":", 1)[1])
    ticket = await repo.get_ticket(pool, ticket_id)
    # Адрес показываем только владельцу оплаченного билета.
    if ticket is None or ticket["tg_id"] != cb.from_user.id or ticket["status"] != "paid":
        await cb.answer("Билет не найден.", show_alert=True)
        return

    event = await repo.get_event(pool, ticket["event_id"])
    if event is None:
        await cb.answer("Событие не найдено.", show_alert=True)
        return

    await repo.set_ticket_rules_agreed(pool, ticket_id)
    await repo.set_fsm_state(pool, cb.from_user.id, f"screen:ticket:address:{ticket_id}")
    await _edit(cb, texts.ticket_address(event["title"], event["address"]), kb.ticket_address_kb())
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: согласие с правилами, "
        f"показан адрес (билет #{ticket_id})"
    )
