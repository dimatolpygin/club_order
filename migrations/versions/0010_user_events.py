"""user_events: журнал действий пользователей для просмотра пути

Revision ID: 0010_user_events
Revises: 0009_bot_settings
Create Date: 2026-06-15

Append-only лог действий: каждое нажатие кнопки / команда / сообщение пишется
строкой (middleware). Нужен, чтобы в админке смотреть «путь» конкретного
пользователя — что и в каком порядке он нажимал. Рост таблицы ограничен:
на вставке хвост старше последних N записей на пользователя подрезается
(repo.add_event), поэтому отдельная чистка не нужна.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010_user_events"
down_revision: Union[str, None] = "0009_bot_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_user_events_tg_id_id", "user_events", ["tg_id", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_user_events_tg_id_id", table_name="user_events")
    op.drop_table("user_events")
