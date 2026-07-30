"""Раздел «Консультации» в боте (этап 47): продажа пакетов 1/4/8/12.

Консультации — НЕ событие (как йога, этап 46): описание сверху + пакеты (каждый
пакет — своя цена, число консультаций в названии). Пользователь выбирает пакет →
сводка с ценой (скидка участника / промокод / бонусы — по правилам циклов 1–2) →
оплата → редирект к менеджеру. Счётчик остатка и «билет»/доступ в группу услуга
НЕ даёт. Логика цены и платежа — services.service_sales (общий движок услуг);
уведомления админам и статистика — по направлению «Консультации».

Отличие от йоги: здесь впервые к услугам подключены промокоды и бонусы (для йоги
решением раунда 4 они не нужны). Покупается один пакет (количество = 1), поэтому
экрана выбора количества нет — из списка пакетов сразу в сводку.
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
from ..services import promo as promo_service
from ..services import screens
from ..services import service_sales
from ..services.yookassa import YooKassaError
from ..states import ConsultPromoStates
from ..utils import fmt_price
from .payment import _return_url

router = Router()

CATEGORY = "consult"

# Один пакет = одна покупка; количество единиц фиксировано.
QUANTITY = 1

# Сообщение на каждый невалидный статус промокода в флоу консультаций
# (тексты not_found/expired/exhausted/already_used нейтральны — переиспользуем).
_CPROMO_FAIL = {
    promo_service.NOT_FOUND: texts.TICKET_PROMO_NOT_FOUND,
    promo_service.EXPIRED: texts.TICKET_PROMO_EXPIRED,
    promo_service.EXHAUSTED: texts.TICKET_PROMO_EXHAUSTED,
    promo_service.ALREADY_USED: texts.TICKET_PROMO_ALREADY_USED,
}


async def _edit(cb: CallbackQuery, text: str, markup) -> None:
    # Текущее сообщение может быть фото (описание раздела с картинкой): по фото
    # edit_text невозможен — заменяем сообщение (удаляем и шлём заново).
    if cb.message.photo:
        with suppress(TelegramBadRequest):
            await cb.message.delete()
        await cb.message.answer(text, reply_markup=markup)
    else:
        with suppress(TelegramBadRequest):  # «message is not modified» — не критично
            await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


def _price_block(pr: dict) -> str:
    """Разбивка цены пакета: скидка (зачёркнутая база) + бонусы + итог (этапы 15–17)."""
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


async def _active_product(pool: asyncpg.Pool, product_id: int):
    """Пакет консультаций, доступный к продаже (активен, категория consult, цена > 0)."""
    product = await repo.get_service_product(pool, product_id)
    if (
        product is None or product["category"] != CATEGORY
        or not product["is_active"] or product["price"] <= 0
    ):
        return None
    return product


async def _summary_view(
    pool: asyncpg.Pool, tg_id: int, product,
    *, promo_id: int | None = None, use_bonus: bool = False,
):
    """Готовит (text, markup, pr) сводки пакета (скидки + промо + бонусы, этапы 15–17).

    Расчёт — единый `service_sales.compute_service_pricing` (тот же, что при создании
    платежа), поэтому показ и оплата всегда совпадают.
    """
    pr = await service_sales.compute_service_pricing(
        pool, tg_id=tg_id, product=product, quantity=QUANTITY,
        promo_id=promo_id, use_bonus=use_bonus,
    )
    # Промокод введён, но выгоднее другая скидка — поясняем (его не применяем).
    note = ""
    if promo_id is not None and pr["applied"] != "promo" and pr["promo"] is not None:
        note = (
            "<i>Промокод применён, но другая скидка выгоднее — оставили её "
            "(скидки не суммируются).</i>\n\n"
        )
    text = texts.consult_summary(product["title"], note + _price_block(pr))
    markup = kb.consult_summary_kb(
        product["id"], pr["applied_promo_id"],
        use_bonus=use_bonus and pr["bonus_used"] > 0, bonus_cap=pr["bonus_cap"],
    )
    return text, markup, pr


# ── Раздел «Консультации»: описание + пакеты ─────────────────────────────────
@router.callback_query(F.data == kb.NAV_CONSULT)
async def consult_section(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    await repo.set_fsm_state(pool, cb.from_user.id, "screen:consult")
    products = await repo.list_service_products(pool, CATEGORY, active_only=True)
    sellable = [p for p in products if p["price"] > 0]
    if not sellable:
        await _edit(cb, texts.CONSULT_NOT_READY, kb.to_menu_kb())
        logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: Консультации — раздел не настроен")
        return
    view = await screens.resolve(pool, "consult")
    await screens.render(
        cb.message, text=view["text"], markup=kb.consult_packages_kb(sellable),
        photo_url=view["photo_url"], edit=True,
    )
    await cb.answer()
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: раздел Консультации ({len(sellable)} пакет(ов))"
    )


# ── Выбор пакета → сводка ────────────────────────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.CPKG}:"))
async def consult_open_package(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()  # сбрасываем возможный незавершённый ввод промокода
    product_id = int(cb.data.split(":", 1)[1])
    product = await _active_product(pool, product_id)
    if product is None:
        await _edit(cb, texts.CONSULT_NOT_READY, kb.to_menu_kb())
        return
    await repo.set_fsm_state(pool, cb.from_user.id, f"screen:consult:package:{product_id}")
    text, markup, pr = await _summary_view(pool, cb.from_user.id, product)
    await _edit(cb, text, markup)
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: Консультации — пакет «{product['title']}» "
        f"= {fmt_price(pr['final'])} ₽ (скидка: {pr['applied']})"
    )


# ── Ввод промокода для пакета ────────────────────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.CPROMO}:"))
async def consult_promo_enter(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    product_id = int(cb.data.split(":", 1)[1])
    await state.set_state(ConsultPromoStates.waiting_code)
    await state.update_data(product_id=product_id)
    await repo.set_fsm_state(pool, cb.from_user.id, f"screen:consult:promo:{product_id}")
    await _edit(cb, texts.CONSULT_PROMO_ENTER, kb.consult_promo_enter_kb(product_id))
    logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: ввод промокода на консультации")


@router.message(ConsultPromoStates.waiting_code)
async def consult_promo_entered(
    message: Message, state: FSMContext, pool: asyncpg.Pool
) -> None:
    data = await state.get_data()
    product_id = data.get("product_id")
    await state.clear()
    if product_id is None:
        await message.answer(texts.CONSULT_NOT_READY, reply_markup=kb.to_menu_kb())
        return

    product = await _active_product(pool, product_id)
    if product is None:
        await message.answer(texts.CONSULT_NOT_READY, reply_markup=kb.to_menu_kb())
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
            _CPROMO_FAIL[status], reply_markup=kb.consult_promo_retry_kb(product_id)
        )
        logger.info(
            f"🤖 Бот → @{message.from_user.username or '—'}: промокод на консультации «{code}» — {status}"
        )
        return
    # fixed_price-промокоды действуют только на подписку.
    if promo["kind"] != promo_service.KIND_PERCENT:
        await message.answer(
            texts.CONSULT_PROMO_SUB_ONLY, reply_markup=kb.consult_promo_retry_kb(product_id)
        )
        logger.info(
            f"🤖 Бот → @{message.from_user.username or '—'}: промокод «{code}» — только для подписки"
        )
        return

    text, markup, pr = await _summary_view(
        pool, message.from_user.id, product, promo_id=promo["id"]
    )
    await repo.set_fsm_state(pool, message.from_user.id, f"screen:consult:package:{product_id}")
    await message.answer(text, reply_markup=markup)
    logger.info(
        f"🤖 Бот → @{message.from_user.username or '—'}: промокод «{code}» на консультации — "
        f"{fmt_price(pr['final'])} ₽ (применено: {pr['applied']})"
    )


# ── Тоггл оплаты бонусами на сводке пакета ───────────────────────────────────
def _parse_promo_part(raw: str) -> int | None:
    """promo_id из callback (0 — нет промокода)."""
    val = int(raw)
    return val if val != 0 else None


@router.callback_query(F.data.startswith(f"{kb.CBONUS}:"))
async def consult_bonus_toggle(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    # callback: cbonus:{product_id}:{promo_or_0}:{1|0}
    _, pid_raw, promo_raw, flag = cb.data.split(":", 3)
    product = await _active_product(pool, int(pid_raw))
    if product is None:
        await _edit(cb, texts.CONSULT_NOT_READY, kb.to_menu_kb())
        return
    text, markup, pr = await _summary_view(
        pool, cb.from_user.id, product,
        promo_id=_parse_promo_part(promo_raw), use_bonus=(flag == "1"),
    )
    await _edit(cb, text, markup)
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: бонусы {'вкл' if flag == '1' else 'выкл'} "
        f"на консультации — итого {fmt_price(pr['final'])} ₽"
    )


# ── Создание платежа ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.CPAY}:"))
async def consult_pay_create(cb: CallbackQuery, bot: Bot, pool: asyncpg.Pool) -> None:
    # callback: cpay:{product_id}:{promo_or_0}:{1|0}
    _, pid_raw, promo_raw, flag = cb.data.split(":", 3)
    product_id = int(pid_raw)
    await cb.answer("Создаю платёж...")
    try:
        status, result = await service_sales.start_service_payment(
            pool, tg_id=cb.from_user.id, product_id=product_id, quantity=QUANTITY,
            return_url=await _return_url(bot),
            promo_id=_parse_promo_part(promo_raw), use_bonus=(flag == "1"),
        )
    except YooKassaError:
        await _edit(cb, texts.PAY_CREATE_FAILED, kb.to_menu_kb())
        return

    if status == "bonus_failed":
        await cb.answer(
            "Не удалось списать бонусы — баланс изменился. Открой пакет заново.",
            show_alert=True,
        )
        return
    if status == "free":
        await _edit(cb, texts.SERVICE_FREE, kb.to_menu_kb())
        return
    if status != "ok" or result is None:
        await _edit(cb, texts.CONSULT_NOT_READY, kb.to_menu_kb())
        return

    await repo.set_fsm_state(pool, cb.from_user.id, "screen:consult:pay")
    await _edit(
        cb, texts.service_pay_created(fmt_price(result["amount"])),
        kb.consult_pay_kb(result["confirmation_url"], result["payment_id"]),
    )
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: ссылка на оплату консультаций "
        f"{fmt_price(result['amount'])} ₽ (yk_id={result['payment_id']})"
    )


# ── Проверка оплаты вручную ──────────────────────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.CCHECK}:"))
async def consult_pay_check(cb: CallbackQuery, bot: Bot, pool: asyncpg.Pool) -> None:
    yk_id = cb.data.split(":", 1)[1]
    payment = await repo.get_payment_by_yk_id(pool, yk_id)
    if payment is None:
        await cb.answer("Платёж не найден.", show_alert=True)
        return

    status, paid = await service_sales.sync_service_payment(pool, bot, payment, notify=False)
    if status == "succeeded" and paid is not None:
        await _show_paid(cb, pool, paid)
        logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: консультации оплачены")
    elif status == "canceled":
        await _edit(cb, texts.PAY_CANCELED, kb.consult_canceled_kb())
    else:
        await cb.answer(texts.PAY_STILL_PENDING, show_alert=True)


# ── Отмена незавершённого платежа (возврат бонусов) ──────────────────────────
@router.callback_query(F.data.startswith(f"{kb.CCANCEL}:"))
async def consult_pay_cancel(cb: CallbackQuery, bot: Bot, pool: asyncpg.Pool) -> None:
    yk_id = cb.data.split(":", 1)[1]
    status, paid = await service_sales.cancel_service_payment(pool, bot, yk_id)
    if status == "not_found":
        await cb.answer("Платёж не найден.", show_alert=True)
        return
    if status == "succeeded" and paid is not None:
        await _show_paid(cb, pool, paid)
        await cb.answer("Платёж уже оплачен.")
        return

    await repo.set_fsm_state(pool, cb.from_user.id, "screen:consult:canceled")
    await _edit(cb, texts.ticket_pay_canceled(status == "canceled_refunded"), kb.consult_canceled_kb())
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: отмена оплаты консультаций "
        f"(yk_id={yk_id}, бонусы возвращены={status == 'canceled_refunded'})"
    )


async def _show_paid(cb: CallbackQuery, pool: asyncpg.Pool, paid: dict) -> None:
    url = await app_settings.manager_url(pool)
    await repo.set_fsm_state(pool, cb.from_user.id, "screen:consult:paid")
    await _edit(
        cb,
        texts.consult_success(paid["product"]["title"], fmt_price(paid["amount"])),
        kb.service_paid_kb(url),
    )
