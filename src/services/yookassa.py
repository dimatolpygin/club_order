"""Тонкий async-клиент ЮKassa (REST API v3, без вебхука).

Только две операции, нужные на этапе 3:
  · create_payment — создать платёж, получить confirmation_url;
  · get_payment    — узнать текущий статус (для polling и кнопки «Проверить»).

Авторизация — HTTP Basic (shop_id:secret_key). Создание платежа требует
заголовок Idempotence-Key (UUID) — повтор с тем же ключом не плодит платежи.
aiohttp поставляется как зависимость aiogram, отдельной строки в requirements не нужно.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import aiohttp

from ..config import settings
from ..logger import logger

_API_URL = "https://api.yookassa.ru/v3/payments"
_TIMEOUT = aiohttp.ClientTimeout(total=30)


class YooKassaError(RuntimeError):
    """Ошибка обращения к API ЮKassa (сеть/HTTP/невалидный ответ)."""


def _auth() -> aiohttp.BasicAuth:
    return aiohttp.BasicAuth(settings.yookassa_shop_id, settings.yookassa_secret_key)


def new_idempotence_key() -> str:
    return str(uuid.uuid4())


async def create_payment(
    *,
    amount: Decimal,
    description: str,
    return_url: str,
    metadata: dict,
    receipt: dict,
    idempotence_key: str,
) -> dict:
    """Создаёт платёж с capture=true (сразу списывается при подтверждении).

    Возвращает JSON-объект платежа ЮKassa (id, status, confirmation.confirmation_url...).
    """
    body = {
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": description,
        "metadata": metadata,
        "receipt": receipt,
    }
    headers = {"Idempotence-Key": idempotence_key}
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.post(
                _API_URL, json=body, headers=headers, auth=_auth()
            ) as resp:
                data = await resp.json()
                if resp.status not in (200, 201):
                    logger.error(f"ЮKassa create_payment HTTP {resp.status}: {data}")
                    raise YooKassaError(f"Создание платежа отклонено (HTTP {resp.status})")
                return data
    except aiohttp.ClientError as e:
        logger.error(f"ЮKassa create_payment сеть: {e}")
        raise YooKassaError("Сеть недоступна при создании платежа") from e


async def get_payment(payment_id: str) -> dict:
    """Возвращает актуальный объект платежа по его id."""
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(f"{_API_URL}/{payment_id}", auth=_auth()) as resp:
                data = await resp.json()
                if resp.status != 200:
                    logger.error(f"ЮKassa get_payment HTTP {resp.status}: {data}")
                    raise YooKassaError(f"Не удалось получить платёж (HTTP {resp.status})")
                return data
    except aiohttp.ClientError as e:
        logger.error(f"ЮKassa get_payment сеть: {e}")
        raise YooKassaError("Сеть недоступна при проверке платежа") from e
