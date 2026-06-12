"""Слой доступа к данным. Все таблицы — в схеме club_bot (search_path задан в db.py)."""
from __future__ import annotations

import asyncpg


async def upsert_user(
    pool: asyncpg.Pool, tg_id: int, username: str | None, first_name: str | None
) -> None:
    """Создаёт/обновляет запись пользователя при любом входящем действии."""
    await pool.execute(
        """
        INSERT INTO users(tg_id, username, first_name)
        VALUES($1, $2, $3)
        ON CONFLICT (tg_id) DO UPDATE
            SET username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                updated_at = now()
        """,
        tg_id,
        username,
        first_name,
    )


async def set_fsm_state(pool: asyncpg.Pool, tg_id: int, state: str | None) -> None:
    """Фиксирует текущее FSM-состояние пользователя (чтобы видеть, где застрял).

    state=None означает выход из сценария.
    """
    await pool.execute(
        """
        INSERT INTO fsm_states(tg_id, state)
        VALUES($1, $2)
        ON CONFLICT (tg_id) DO UPDATE
            SET state = EXCLUDED.state,
                updated_at = now()
        """,
        tg_id,
        state,
    )
