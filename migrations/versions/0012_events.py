"""events + event_ticket_prices: офлайн-события «Фокус.Энергия» (цикл 2, этап 12)

Мероприятия (бани, ретриты) и цены по типам билетов. Учёт мест: общий (seats_total)
или раздельный по полу (seats_male/seats_female) при включённом гендер-балансе.
Скидка подписчику, адрес и правила хранятся на событии (адрес показывается боту
после согласия с правилами — этап 14).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012_events"
down_revision: Union[str, None] = "0011_admin_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        # Тип события: 'banya' (Энерго Баня) | 'retreat' (ретрит). Текстом — расширяемо.
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.TIMESTAMP(timezone=True), nullable=False),
        # Гендер-баланс: True → места раздельно (male/female), False → общий пул (total).
        sa.Column("gender_balance", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("seats_total", sa.Integer(), nullable=True),
        sa.Column("seats_male", sa.Integer(), nullable=True),
        sa.Column("seats_female", sa.Integer(), nullable=True),
        # Только для бань: показывать это событие заранее вместе с ближайшим.
        sa.Column("show_in_advance", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        # Скидка подписчику клуба на это событие, % (0..100).
        sa.Column("subscriber_discount_percent", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("address", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("rules_text", sa.Text(), nullable=False, server_default=sa.text("''")),
        # Показывать ли событие в боте (мягкое скрытие без удаления).
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_events_kind_starts", "events", ["kind", "starts_at"])

    op.create_table(
        "event_ticket_prices",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "event_id", sa.BigInteger(),
            sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False,
        ),
        # Тип билета: male | female | pair_mf | pair_ff | pair_mm.
        sa.Column("ticket_type", sa.Text(), nullable=False),
        # Цена в рублях (целое). Строка есть → тип продаётся; нет строки → не продаётся.
        sa.Column("price", sa.Integer(), nullable=False),
        sa.UniqueConstraint("event_id", "ticket_type", name="ux_event_ticket_type"),
    )


def downgrade() -> None:
    op.drop_table("event_ticket_prices")
    op.drop_index("ix_events_kind_starts", table_name="events")
    op.drop_table("events")
