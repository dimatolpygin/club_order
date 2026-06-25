"""screen_texts — переопределение текста экранов бота из веб-админки (этап 22)

Тексты инфо-экранов бота (приветствие, главное меню, что внутри, правила,
поддержка) можно править из веб-админки без правки кода. Дефолтные тексты живут
в реестре `services.screens` (источник истины, ссылается на `texts.py`); эта
таблица хранит ТОЛЬКО переопределения: свой текст (`body`, NULL = дефолт из
реестра). Бот при каждом рендере экрана сливает реестр с этой таблицей —
применяется на лету, как `menu_buttons` для кнопок (этап 19).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0022_screen_texts"
down_revision: Union[str, None] = "0021_manager_msg_read"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "screen_texts",
        # Ключ экрана из реестра services.screens (start/menu/about/rules/support/…).
        sa.Column("key", sa.Text(), primary_key=True),
        # Свой текст экрана (HTML); NULL → дефолтный из реестра.
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("screen_texts")
