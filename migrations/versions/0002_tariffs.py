"""tariffs: price_tiers + durations + subscriptions (+ сид по ТЗ)

Revision ID: 0002_tariffs
Revises: 0001_init
Create Date: 2026-06-12

Ценовые ступени по числу мест, длительности подписки и сами подписки.
Цены/лимиты/длительности — редактируемы админом (этап 2/8), здесь только сид-пример.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_tariffs"
down_revision: Union[str, None] = "0001_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ценовые ступени: помесячная ставка + лимит мест (NULL = безлимит).
    op.create_table(
        "price_tiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("monthly_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("seat_limit", sa.Integer(), nullable=True),  # NULL = безлимит
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Доступные длительности подписки (в месяцах).
    op.create_table(
        "durations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("months", sa.Integer(), nullable=False, unique=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    # Подписки. Заполняются оплатой (этап 3) и ручным добавлением (этап 8).
    # На этапе 2 нужны для подсчёта занятых мест по ступени.
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("tier_id", sa.Integer(), nullable=True),  # NULL = промо/кастом
        sa.Column("fixed_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("months", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "start_date", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("end_date", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("source", sa.Text(), nullable=False, server_default="payment"),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["tier_id"], ["price_tiers.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_subs_tier_status", "subscriptions", ["tier_id", "status"])
    op.create_index("ix_subs_tg_status", "subscriptions", ["tg_id", "status"])
    op.create_index("ix_subs_end_date", "subscriptions", ["end_date"])

    # ── Сид-пример из ТЗ (админ потом меняет под реальные условия) ────────────
    op.bulk_insert(
        sa.table(
            "price_tiers",
            sa.column("name", sa.Text),
            sa.column("monthly_price", sa.Numeric),
            sa.column("seat_limit", sa.Integer),
            sa.column("sort_order", sa.Integer),
        ),
        [
            {"name": "Первые места", "monthly_price": 1111, "seat_limit": 11, "sort_order": 10},
            {"name": "Второй круг", "monthly_price": 2222, "seat_limit": 11, "sort_order": 20},
            {"name": "Третий круг", "monthly_price": 3333, "seat_limit": 11, "sort_order": 30},
            {"name": "Четвёртый круг", "monthly_price": 4444, "seat_limit": 11, "sort_order": 40},
            {"name": "Стандарт", "monthly_price": 5555, "seat_limit": None, "sort_order": 50},
        ],
    )
    op.bulk_insert(
        sa.table(
            "durations",
            sa.column("months", sa.Integer),
            sa.column("sort_order", sa.Integer),
        ),
        [
            {"months": 1, "sort_order": 10},
            {"months": 3, "sort_order": 20},
            {"months": 6, "sort_order": 30},
            {"months": 12, "sort_order": 40},
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_subs_end_date", table_name="subscriptions")
    op.drop_index("ix_subs_tg_status", table_name="subscriptions")
    op.drop_index("ix_subs_tier_status", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("durations")
    op.drop_table("price_tiers")
