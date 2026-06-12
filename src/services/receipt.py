"""Формирование чека 54-ФЗ для платежа ЮKassa — ЕДИНАЯ точка.

Email покупателя берётся из users.email; пока сбор реального email не включён,
подставляется заглушка из настроек (RECEIPT_EMAIL_PLACEHOLDER). Когда понадобится
собирать настоящий email — достаточно заполнять users.email, эта функция уже его
подхватит, остальной код менять не нужно.
"""
from __future__ import annotations

from decimal import Decimal

import asyncpg

from ..config import settings


def receipt_email(user: asyncpg.Record | None) -> str:
    """Email для чека: реальный из users.email либо заглушка из настроек."""
    if user is not None and user["email"]:
        return user["email"]
    return settings.receipt_email_placeholder


def build_receipt(user: asyncpg.Record | None, description: str, amount: Decimal) -> dict:
    """Чек из одной позиции (подписка). vat_code=1 — без НДС (УСН)."""
    return {
        "customer": {"email": receipt_email(user)},
        "items": [
            {
                "description": description,
                "quantity": "1.00",
                "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                "vat_code": 1,
                "payment_subject": "service",
                "payment_mode": "full_prepayment",
            }
        ],
    }
