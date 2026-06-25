"""menu_buttons — переопределение текста и видимости кнопок меню бота (этап 19)

Кнопки главного меню и приветствия бота можно переименовывать и скрывать из
веб-админки без правки кода. Дефолтные тексты/состав живут в реестре
`services.menu` (источник истины структуры/раскладки); эта таблица хранит ТОЛЬКО
переопределения: своя подпись (`label`, NULL = дефолт из реестра) и видимость
(`is_visible`). Бот при каждом рендере меню сливает реестр с этой таблицей.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0016_menu_buttons"
down_revision: Union[str, None] = "0015_ticket_refund_request"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "menu_buttons",
        # Ключ кнопки из реестра services.menu (join/mysub/events/…).
        sa.Column("key", sa.Text(), primary_key=True),
        # Своя подпись; NULL → дефолтная из реестра.
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("is_visible", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("menu_buttons")
