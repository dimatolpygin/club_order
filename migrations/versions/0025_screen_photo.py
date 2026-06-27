"""screen_texts.photo_url — картинка к инфо-экрану бота (цикл 2, этап 37)

К любому редактируемому инфо-экрану (этап 22) можно прикрепить картинку из веб-админки.
NULL = экран без фото (показывается ровно как раньше, текстом). При наличии фото бот
шлёт фото с подписью (≤1024 символов). Картинка хранится в S3, в колонке — публичный URL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0025_screen_photo"
down_revision: Union[str, None] = "0024_ticket_checkin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("screen_texts", sa.Column("photo_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("screen_texts", "photo_url")
