"""tickets.attended_at + attended_by — чек-ин на точке (цикл 2, этап 34)

На входе админ отмечает пришедших по оплаченным билетам. Факт прихода фиксируется
временем (`attended_at`) и логином администратора панели (`attended_by` — аудит «кто
отметил»). NULL = не пришёл. Отметка идемпотентна (повтор не задваивает) и снимаема
(ошибочное нажатие). Влияет только на чек-ин — учёт мест/возвраты не затрагивает.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0024_ticket_checkin"
down_revision: Union[str, None] = "0023_broadcasts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tickets", sa.Column("attended_at", sa.TIMESTAMP(timezone=True), nullable=True)
    )
    # Логин администратора веб-панели, отметившего приход (аудит «кто»).
    op.add_column("tickets", sa.Column("attended_by", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tickets", "attended_by")
    op.drop_column("tickets", "attended_at")
