"""tickets + расширение payments под билеты (цикл 2, этап 14)

Продажа билетов на офлайн-события переиспользует платёжный конвейер подписок:
строка `payments` (kind='ticket') описывает платёж, а выданный билет — строка
`tickets`. Поле `payments.ticket_id` — защита от дубля при активации (аналог
`subscription_id` для подписок): повторная активация того же платежа не выдаёт
второй билет.

Учёт мест считается по проданным билетам (status='paid') под блокировкой строки
события — см. repo.activate_ticket_payment. Билет НЕ даёт доступ в группу.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013_tickets"
down_revision: Union[str, None] = "0012_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tickets",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "event_id", sa.BigInteger(),
            sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False,
        ),
        # Тип билета: male | female | pair_mf | pair_ff | pair_mm.
        sa.Column("ticket_type", sa.Text(), nullable=False),
        # Цена, по которой билет фактически куплен (после скидок — этапы 15/16).
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        # paid → (refunded — возвраты, этап 18). Для учёта мест считаем только 'paid'.
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'paid'")),
        # Платёж, которым оплачен билет (NULL — ручная выдача/история).
        sa.Column(
            "payment_id", sa.BigInteger(),
            sa.ForeignKey("payments.id", ondelete="SET NULL"), nullable=True,
        ),
        # Согласие с правилами посещения (после него показывается адрес).
        sa.Column("rules_agreed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Подсчёт занятых мест по событию идёт по (event_id, status).
    op.create_index("ix_tickets_event_status", "tickets", ["event_id", "status"])
    op.create_index("ix_tickets_tg", "tickets", ["tg_id"])

    # Расширяем payments под билеты (переиспользование конвейера подписок).
    op.add_column("payments", sa.Column("event_id", sa.BigInteger(), nullable=True))
    op.add_column("payments", sa.Column("ticket_type", sa.Text(), nullable=True))
    op.add_column("payments", sa.Column("ticket_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_payments_event", "payments", "events", ["event_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_payments_ticket", "payments", "tickets", ["ticket_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_payments_ticket", "payments", type_="foreignkey")
    op.drop_constraint("fk_payments_event", "payments", type_="foreignkey")
    op.drop_column("payments", "ticket_id")
    op.drop_column("payments", "ticket_type")
    op.drop_column("payments", "event_id")
    op.drop_index("ix_tickets_tg", table_name="tickets")
    op.drop_index("ix_tickets_event_status", table_name="tickets")
    op.drop_table("tickets")
