"""subscription_reminders: учёт отправленных напоминаний о продлении (этап 6)

Revision ID: 0007_subscription_reminders
Revises: 0006_duration_units
Create Date: 2026-06-13

Фоновый джоб (APScheduler) шлёт до трёх напоминаний на подписку — «early» (за
несколько дней), «soon» (за день) и «last» (в последний день). Чтобы повторные
прогоны планировщика не дублировали отправку, факт отправки фиксируется здесь:
одна строка на пару (подписка, тип). Первичный ключ (subscription_id, kind) +
INSERT ... ON CONFLICT DO NOTHING даёт атомарную «заявку» на отправку — гонка
двух прогонов не пошлёт сообщение дважды.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_subscription_reminders"
down_revision: Union[str, None] = "0006_duration_units"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscription_reminders",
        sa.Column("subscription_id", sa.BigInteger(), nullable=False),
        # Тип напоминания: early | soon | last (порог каждого задаётся настройкой).
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "sent_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("subscription_id", "kind"),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["subscriptions.id"], ondelete="CASCADE"
        ),
    )


def downgrade() -> None:
    op.drop_table("subscription_reminders")
