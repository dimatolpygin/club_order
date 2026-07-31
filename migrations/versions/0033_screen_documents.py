"""Документы к экрану бота (screen_texts.documents) — оферта/политика и т.п. (этап 49+).

К экрану согласия на обработку ПД (и другим экранам, поддерживающим документы)
можно приложить НЕСКОЛЬКО файлов из веб-админки (оферта, политика обработки ПД и
т.д.). Раньше к экрану крепилась только одна картинка (0025). Храним список
объектов [{"url": <публичный S3-URL>, "name": <имя файла для показа>}] в JSONB.
NULL/[] = без документов (экран работает как раньше). Бот присылает эти файлы
отдельными сообщениями перед текстом экрана.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0033_screen_documents"
down_revision: Union[str, None] = "0032_pd_consent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "screen_texts",
        sa.Column("documents", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("screen_texts", "documents")
