"""subscription_lifecycle: продление подписок + авто-окончание (этап 5)

Revision ID: 0005_subscription_lifecycle
Revises: 0004_tier_prices
Create Date: 2026-06-13

Колонка payments.kind различает первичную покупку ('new') и продление ('renewal'):
при активации платежа 'new' создаётся новая подписка (end = now + months), а
'renewal' продлевает существующую активную подписку (end_date += months) с
сохранением зафиксированной ставки. Частичный индекс по активным подпискам
ускоряет фоновую проверку окончаний (APScheduler помечает истёкшие 'expired').
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_subscription_lifecycle"
down_revision: Union[str, None] = "0004_tier_prices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("kind", sa.Text(), nullable=False, server_default="new"),
    )
    # Быстрый поиск истёкших активных подписок фоновой проверкой окончаний.
    op.create_index(
        "ix_subs_active_due",
        "subscriptions",
        ["end_date"],
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("ix_subs_active_due", table_name="subscriptions")
    op.drop_column("payments", "kind")
