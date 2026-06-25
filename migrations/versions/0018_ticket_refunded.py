"""tickets.refunded_at + refunded_by — отметка фактического возврата (цикл 2, этап 21)

На этапе 18/20 билет лишь помечается на возврат (`refund_requested`, статус остаётся
`paid`, место занято). Менеджер возвращает деньги вручную переводом и отмечает факт
в веб-админке: статус → `refunded`, фиксируется когда (`refunded_at`) и кто
(`refunded_by` — логин администратора панели, для аудита). Перевод в `refunded`
освобождает место (занятость считается по `status='paid'`) и убирает билет из
«Моих билетов» у пользователя.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018_ticket_refunded"
down_revision: Union[str, None] = "0017_event_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tickets", sa.Column("refunded_at", sa.TIMESTAMP(timezone=True), nullable=True)
    )
    # Логин администратора веб-панели, отметившего возврат (аудит «кто»).
    op.add_column("tickets", sa.Column("refunded_by", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tickets", "refunded_by")
    op.drop_column("tickets", "refunded_at")
