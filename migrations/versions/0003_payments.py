"""payments: платежи ЮKassa (этап 3)

Revision ID: 0003_payments
Revises: 0002_tariffs
Create Date: 2026-06-12

Каждое создание платежа в ЮKassa порождает строку в payments. Фоновый поллер
(APScheduler) опрашивает pending-платежи; при succeeded подписка активируется и
её id записывается в payments.subscription_id — это и есть защита от дубля:
повторная активация того же платежа не создаёт вторую подписку.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_payments"
down_revision: Union[str, None] = "0002_tariffs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        # id платежа в ЮKassa (UUID-строка). Уникален — по нему ищем при polling.
        sa.Column("yookassa_payment_id", sa.Text(), nullable=False, unique=True),
        # Ключ идемпотентности запроса создания (UUID) — чтобы повтор не плодил платежи.
        sa.Column("idempotence_key", sa.Text(), nullable=False),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("tier_id", sa.Integer(), nullable=True),  # NULL = промо/кастом
        sa.Column("months", sa.Integer(), nullable=False, server_default="1"),
        # Зафиксированная помесячная ставка на момент оплаты.
        sa.Column("fixed_price", sa.Numeric(10, 2), nullable=False),
        # Итоговая сумма платежа = fixed_price × months.
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        # pending → succeeded / canceled (статус из ЮKassa).
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("confirmation_url", sa.Text(), nullable=True),
        # Подписка, созданная при успешной оплате (NULL пока не активирован).
        sa.Column("subscription_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["tier_id"], ["price_tiers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["subscriptions.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_payments_status", "payments", ["status"])
    op.create_index("ix_payments_tg", "payments", ["tg_id"])


def downgrade() -> None:
    op.drop_index("ix_payments_tg", table_name="payments")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_table("payments")
