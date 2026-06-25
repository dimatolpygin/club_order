"""manager_messages — мост «менеджер ↔ покупатель» через бота (этап 21.1)

Прямая связь с покупателем без @username из Telegram-клиента невозможна (нельзя
писать по numeric id). Поэтому менеджер пишет из веб-админки, а доставляет бот
(покупатель уже в диалоге с ботом). Веб-процесс отдельный от бота → очередь:

  · direction='out' — сообщение менеджера покупателю: веб ставит status='pending',
    бот-джоб доставляет → 'sent' / 'failed' (юзер заблокировал бота);
  · direction='in'  — ответ покупателя боту: бот-роутер пересылает всем админам и
    логирует строкой status='received' (история переписки в карточке билета).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0020_manager_messages"
down_revision: Union[str, None] = "0019_refund_notify"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "manager_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        # Покупатель (вторая сторона переписки).
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        # Билет-контекст (необязателен; SET NULL при удалении билета).
        sa.Column(
            "ticket_id", sa.BigInteger(),
            sa.ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True,
        ),
        # 'out' — менеджер→покупатель; 'in' — покупатель→админы.
        sa.Column("direction", sa.Text(), nullable=False),
        # Для 'out' — логин админа-отправителя (аудит).
        sa.Column("admin_login", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        # 'pending'→'sent'/'failed' для out; 'received' для in.
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("delivered_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    # Очередь исходящих (по статусу) и история по пользователю.
    op.create_index("ix_manager_messages_status", "manager_messages", ["status"])
    op.create_index("ix_manager_messages_tg", "manager_messages", ["tg_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_manager_messages_tg", table_name="manager_messages")
    op.drop_index("ix_manager_messages_status", table_name="manager_messages")
    op.drop_table("manager_messages")
