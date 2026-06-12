"""tier_prices: абсолютная цена за период внутри ступени (матрица ступень×период)

Revision ID: 0004_tier_prices
Revises: 0003_payments
Create Date: 2026-06-12

По запросу заказчика: цена за 3/6/12 мес задаётся вручную в каждой ступени, а не
обязательно как ставка×месяцы. Здесь — переопределения цены для конкретного периода.
Если для (ступень, период) записи нет — цена считается как monthly_price×месяцы
(старое поведение сохраняется по умолчанию). Цена за 1 мес = price_tiers.monthly_price
(она же фиксируется за пользователем и используется при продлении), поэтому в матрице
хранятся только многомесячные периоды.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_tier_prices"
down_revision: Union[str, None] = "0003_payments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tier_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tier_id", sa.Integer(), nullable=False),
        sa.Column("months", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["tier_id"], ["price_tiers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tier_id", "months", name="uq_tier_prices_tier_months"),
    )


def downgrade() -> None:
    op.drop_table("tier_prices")
