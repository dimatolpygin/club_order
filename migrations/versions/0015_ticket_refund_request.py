"""tickets.refund_requested — пометка «возврат запрошен» (цикл 2, этап 18)

Пользователь может запросить возврат за билет. Возврат — ручной (менеджер
возвращает деньги переводом), поэтому запрос НЕ отменяет билет автоматически:
статус остаётся 'paid' (место не освобождаем до фактического возврата — иначе
овербукинг и риск при отказе менеджера). Запрос лишь ставит флаг `refund_requested`
(+ время), чтобы:
- в «Моих билетах» показать метку «возврат запрошен» и убрать кнопку повторного
  запроса (нельзя слать заявку дважды);
- менеджер позже (веб-админка, отд. этап) отметил фактический возврат → статус
  'refunded' уберёт билет из списка и освободит место.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015_ticket_refund_request"
down_revision: Union[str, None] = "0014_referrals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column(
            "refund_requested", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tickets",
        sa.Column("refund_requested_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tickets", "refund_requested_at")
    op.drop_column("tickets", "refund_requested")
