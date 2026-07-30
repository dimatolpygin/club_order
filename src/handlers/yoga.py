"""Раздел «Йога» в боте (этап 46): продажа занятий по количеству.

Йога — НЕ событие: описание сверху + продукты (индивидуальное/групповое), выбор
количества → цена = цена продукта × количество → оплата → редирект к менеджеру.
Счётчик остатка и «билет»/доступ в группу услуга НЕ даёт. Логика цены и платежа —
services.service_sales; уведомления админам и статистика — по направлению «Йога».
Тот же движок переиспользуют консультации (этап 47) — здесь только раздел йоги.
"""
from __future__ import annotations

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
import asyncpg

from .. import keyboards as kb
from .. import repo, texts
from ..logger import logger
from ..services import app_settings
from ..services import screens
from ..services import service_sales
from ..services.yookassa import YooKassaError
from ..utils import fmt_price
from .payment import _return_url

router = Router()

CATEGORY = "yoga"


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
    """Разбивка цены услуги: скидка (зачёркнутая база) + итог (этапы 15/40)."""
    base = fmt_price(pr["base_price"])
    final = fmt_price(pr["final"])
    if pr["final"] < pr["base_price"]:
        applied = pr["applied"]
        if applied == "subscriber":
            label = f"Скидка участника −{pr['subscriber_pct']}%"
        elif applied == "referral":
            label = f"Скидка новичка −{pr['referral_amount']} ₽"
        else:
            label = "Скидка"
        return f"Цена: <s>{base} ₽</s>\n<b>{label}: {final} ₽</b>\n"
    return f"<b>Стоимость: {final} ₽</b>\n"


async def _active_product(pool: asyncpg.Pool, product_id: int):
    """Продукт йоги, доступный к продаже (активен, категория йоги, цена > 0)."""
    product = await repo.get_service_product(pool, product_id)
    if (
        product is None or product["category"] != CATEGORY
        or not product["is_active"] or product["price"] <= 0
    ):
        return None
    return product


# ── Раздел «Йога»: описание + форматы ────────────────────────────────────────
@router.callback_query(F.data == kb.NAV_YOGA)
async def yoga_section(cb: CallbackQuery, pool: asyncpg.Pool, state: FSMContext) -> None:
    await state.clear()
    await repo.set_fsm_state(pool, cb.from_user.id, "screen:yoga")
    products = await repo.list_service_products(pool, CATEGORY, active_only=True)
    sellable = [p for p in products if p["price"] > 0]
    if not sellable:
        await _edit(cb, texts.YOGA_NOT_READY, kb.to_menu_kb())
        logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: Йога — раздел не настроен")
        return
    view = await screens.resolve(pool, "yoga")
    await screens.render(
        cb.message, text=view["text"], markup=kb.yoga_products_kb(sellable),
        photo_url=view["photo_url"], edit=True,
    )
    await cb.answer()
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: раздел Йога ({len(sellable)} формат(ов))"
    )


# ── Выбор формата → выбор количества ─────────────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.YPROD}:"))
async def yoga_choose_product(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    product_id = int(cb.data.split(":", 1)[1])
    product = await _active_product(pool, product_id)
    if product is None:
        await _edit(cb, texts.YOGA_NOT_READY, kb.to_menu_kb())
        return
    await repo.set_fsm_state(pool, cb.from_user.id, f"screen:yoga:product:{product_id}")
    text = texts.service_quantity_prompt(product["title"], fmt_price(product["price"]))
    await _edit(cb, text, kb.yoga_quantity_kb(product_id))
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: Йога — формат «{product['title']}»"
    )


# ── Выбор количества → сводка ────────────────────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.YQTY}:"))
async def yoga_choose_quantity(cb: CallbackQuery, pool: asyncpg.Pool) -> None:
    _, pid_raw, qty_raw = cb.data.split(":", 2)
    product_id, quantity = int(pid_raw), int(qty_raw)
    product = await _active_product(pool, product_id)
    if product is None:
        await _edit(cb, texts.YOGA_NOT_READY, kb.to_menu_kb())
        return
    pr = await service_sales.compute_service_pricing(
        pool, tg_id=cb.from_user.id, product=product, quantity=quantity
    )
    await repo.set_fsm_state(
        pool, cb.from_user.id, f"screen:yoga:summary:{product_id}:{quantity}"
    )
    text = texts.service_summary(product["title"], quantity, _price_block(pr))
    await _edit(cb, text, kb.service_summary_kb(product_id, quantity))
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: Йога — «{product['title']}» × "
        f"{quantity} = {fmt_price(pr['final'])} ₽ (скидка: {pr['applied']})"
    )


# ── Создание платежа ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.YPAY}:"))
async def yoga_pay_create(cb: CallbackQuery, bot: Bot, pool: asyncpg.Pool) -> None:
    _, pid_raw, qty_raw = cb.data.split(":", 2)
    product_id, quantity = int(pid_raw), int(qty_raw)
    await cb.answer("Создаю платёж...")
    try:
        status, result = await service_sales.start_service_payment(
            pool, tg_id=cb.from_user.id, product_id=product_id,
            quantity=quantity, return_url=await _return_url(bot),
        )
    except YooKassaError:
        await _edit(cb, texts.PAY_CREATE_FAILED, kb.to_menu_kb())
        return

    if status == "free":
        await _edit(cb, texts.SERVICE_FREE, kb.to_menu_kb())
        return
    if status != "ok" or result is None:
        await _edit(cb, texts.YOGA_NOT_READY, kb.to_menu_kb())
        return

    await repo.set_fsm_state(pool, cb.from_user.id, "screen:yoga:pay")
    await _edit(
        cb, texts.service_pay_created(fmt_price(result["amount"])),
        kb.service_pay_kb(result["confirmation_url"], result["payment_id"]),
    )
    logger.info(
        f"🤖 Бот → @{cb.from_user.username or '—'}: ссылка на оплату услуги "
        f"{fmt_price(result['amount'])} ₽ (yk_id={result['payment_id']})"
    )


# ── Проверка оплаты вручную ──────────────────────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.YCHECK}:"))
async def yoga_pay_check(cb: CallbackQuery, bot: Bot, pool: asyncpg.Pool) -> None:
    yk_id = cb.data.split(":", 1)[1]
    payment = await repo.get_payment_by_yk_id(pool, yk_id)
    if payment is None:
        await cb.answer("Платёж не найден.", show_alert=True)
        return

    status, paid = await service_sales.sync_service_payment(pool, bot, payment, notify=False)
    if status == "succeeded" and paid is not None:
        await _show_paid(cb, pool, paid)
        logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: услуга оплачена")
    elif status == "canceled":
        await _edit(cb, texts.PAY_CANCELED, kb.service_canceled_kb())
    else:
        await cb.answer(texts.PAY_STILL_PENDING, show_alert=True)


# ── Отмена незавершённого платежа ────────────────────────────────────────────
@router.callback_query(F.data.startswith(f"{kb.YCANCEL}:"))
async def yoga_pay_cancel(cb: CallbackQuery, bot: Bot, pool: asyncpg.Pool) -> None:
    yk_id = cb.data.split(":", 1)[1]
    payment = await repo.get_payment_by_yk_id(pool, yk_id)
    if payment is None:
        await cb.answer("Платёж не найден.", show_alert=True)
        return

    # Перед отменой убеждаемся, что платёж действительно не оплачен (не теряем оплату).
    status, paid = await service_sales.sync_service_payment(pool, bot, payment, notify=False)
    if status == "succeeded" and paid is not None:
        await _show_paid(cb, pool, paid)
        await cb.answer("Платёж уже оплачен.")
        return
    if status == "pending":
        await repo.mark_payment_canceled(pool, yk_id)

    await repo.set_fsm_state(pool, cb.from_user.id, "screen:yoga:canceled")
    await _edit(cb, texts.PAY_CANCELED, kb.service_canceled_kb())
    logger.info(f"🤖 Бот → @{cb.from_user.username or '—'}: отмена оплаты услуги (yk_id={yk_id})")


async def _show_paid(cb: CallbackQuery, pool: asyncpg.Pool, paid: dict) -> None:
    url = await app_settings.manager_url(pool)
    await repo.set_fsm_state(pool, cb.from_user.id, "screen:yoga:paid")
    await _edit(
        cb,
        texts.service_success(
            paid["product"]["title"], paid["quantity"], fmt_price(paid["amount"])
        ),
        kb.service_paid_kb(url),
    )
