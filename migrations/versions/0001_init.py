"""init: users + fsm_states

Revision ID: 0001_init
Revises:
Create Date: 2026-06-12

Базовые таблицы каркаса (этап 0). search_path указывает на схему club_bot
(см. migrations/env.py), поэтому таблицы создаются именно в ней.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_init"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Пользователи бота. email — задел под чек 54-ФЗ (пока заглушка в настройках).
    op.create_table(
        "users",
        sa.Column("tg_id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column(
            "is_blocked", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Текущее FSM-состояние пользователя — чтобы видеть, где он застрял.
    op.create_table(
        "fsm_states",
        sa.Column("tg_id", sa.BigInteger(), primary_key=True),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_fsm_states_state", "fsm_states", ["state"])


def downgrade() -> None:
    op.drop_index("ix_fsm_states_state", table_name="fsm_states")
    op.drop_table("fsm_states")
    op.drop_table("users")
