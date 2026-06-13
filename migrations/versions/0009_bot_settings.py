"""bot_settings: рантайм-настройки, редактируемые из админки (этап 8)

Revision ID: 0009_bot_settings
Revises: 0008_promocodes
Create Date: 2026-06-13

Простое key/value-хранилище для настроек, которые админ меняет на лету без
рестарта (пороги и единица напоминаний из этапа 6). Значения хранятся строками,
типизация — на стороне приложения; отсутствие ключа = используется дефолт из
`.env`. Сейчас сюда кладутся reminder_unit / reminder_*_offset.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_bot_settings"
down_revision: Union[str, None] = "0008_promocodes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bot_settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("bot_settings")
