"""tickets.refund_notified_at + refund_notify_failed — уведомление о возврате (этап 21.1)

Веб-админка отдельный процесс от бота: рассылку шлёт бот. Отметка возврата (этап 21)
ставит билет в очередь уведомления; фоновый бот-джоб шлёт пользователю «возврат
произведён». Результат фиксируем здесь:
  · refund_notified_at  — уведомление доставлено (NULL — ещё не доставлено);
  · refund_notify_failed — бот не смог доставить (пользователь заблокировал бота).
    Менеджер видит пометку «не доставлено» в админке рядом с tg-ссылкой и связывается
    вручную. failed=true исключает билет из повторных попыток.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0019_refund_notify"
down_revision: Union[str, None] = "0018_ticket_refunded"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("refund_notified_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column(
            "refund_notify_failed", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tickets", "refund_notify_failed")
    op.drop_column("tickets", "refund_notified_at")
