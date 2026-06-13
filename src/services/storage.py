"""Загрузка медиа в S3-совместимое хранилище (Beget) для рассылки (этап 8).

Фото из админ-рассылки заливаются в S3 и раздаются Telegram по публичной ссылке.
boto3 синхронный, поэтому вызовы выполняем в пуле потоков, чтобы не блокировать
event loop. Если S3 не настроен (см. settings.s3_enabled) — функции не вызываются,
рассылка остаётся текстовой.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
from uuid import uuid4

from ..config import settings
from ..logger import logger


@lru_cache(maxsize=1)
def _client():
    """Ленивая инициализация S3-клиента (один на процесс)."""
    import boto3  # импорт здесь — boto3 нужен только при включённом S3

    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        region_name=settings.s3_region or None,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )


def _put_sync(key: str, data: bytes, content_type: str) -> None:
    _client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
        ACL="public-read",
    )


async def upload_photo(data: bytes, ext: str = "jpg") -> str:
    """Заливает фото в S3 и возвращает публичный URL. Бросает исключение при ошибке."""
    key = f"broadcast/{uuid4().hex}.{ext}"
    content_type = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    await asyncio.to_thread(_put_sync, key, data, content_type)
    base = (settings.s3_public_base_url or settings.s3_endpoint).rstrip("/")
    url = f"{base}/{settings.s3_bucket}/{key}"
    logger.info(f"🖼 Фото загружено в S3: {url}")
    return url
