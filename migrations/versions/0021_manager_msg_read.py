"""manager_messages.is_read — непрочитанные ответы покупателей в админке (этап 21.1)

Переписка ведётся и читается в веб-админке (а не в Telegram-аккаунте менеджера).
Ответы покупателя (direction='in') приходят непрочитанными; в списке «Билеты»
показывается пометка «новый ответ», а при открытии переписки входящие помечаются
прочитанными. Read-состояние общее для всех админов (небольшая команда).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0021_manager_msg_read"
down_revision: Union[str, None] = "0020_manager_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "manager_messages",
        sa.Column(
            "is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )


def downgrade() -> None:
    op.drop_column("manager_messages", "is_read")
