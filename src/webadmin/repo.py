"""Запросы к БД для веб-админки. Работает через общий пул (src.db)."""
from __future__ import annotations

import asyncpg


async def get_admin_by_login(pool: asyncpg.Pool, login: str) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT id, login, password_hash, is_active FROM admin_users WHERE login = $1",
        login,
    )


async def get_admin_by_id(pool: asyncpg.Pool, admin_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT id, login, password_hash, is_active FROM admin_users WHERE id = $1",
        admin_id,
    )


async def count_admins(pool: asyncpg.Pool) -> int:
    return await pool.fetchval("SELECT count(*) FROM admin_users")


async def create_admin(pool: asyncpg.Pool, login: str, password_hash: str) -> int:
    return await pool.fetchval(
        "INSERT INTO admin_users (login, password_hash) VALUES ($1, $2) RETURNING id",
        login,
        password_hash,
    )


async def update_password(pool: asyncpg.Pool, admin_id: int, password_hash: str) -> None:
    await pool.execute(
        "UPDATE admin_users SET password_hash = $1 WHERE id = $2",
        password_hash,
        admin_id,
    )


async def mark_login(pool: asyncpg.Pool, admin_id: int) -> None:
    await pool.execute(
        "UPDATE admin_users SET last_login_at = now() WHERE id = $1", admin_id
    )


async def table_exists(pool: asyncpg.Pool, table: str) -> bool:
    """Есть ли таблица в нашей схеме (миграции применяет бот; админка их ждёт)."""
    return await pool.fetchval("SELECT to_regclass($1) IS NOT NULL", table)
