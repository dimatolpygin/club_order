"""broadcasts — очередь рассылок из веб-админки (этап 26)

Веб-процесс не шлёт сообщения сам (бота держит отдельный процесс): форма рассылки
кладёт задачу в эту таблицу со статусом 'pending', а бот-джоб (services.broadcasts)
забирает её, рассылает по аудитории и проставляет статус/счётчики. Фото веб заливает
в S3 (services.storage, как этап 8) и хранит здесь только публичные URL — бот шлёт
их по ссылке (file_id у веб-загрузки нет). Паттерн очереди — как мост этапа 21.1.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0023_broadcasts"
down_revision: Union[str, None] = "0022_screen_texts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Сегмент аудитории: all / active / former / never (repo.AUDIENCE_*).
        sa.Column("audience", sa.Text(), nullable=False),
        # Текст/подпись (HTML); NULL → только фото.
        sa.Column("body", sa.Text(), nullable=True),
        # Список фото как JSON-массив объектов {"url": "..."} (публичные ссылки S3).
        sa.Column(
            "photos", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
        # pending → sending → done (бот-джоб двигает статус).
        sa.Column(
            "status", sa.Text(), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sent", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("blocked", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # Логин админа веб-панели, создавшего рассылку.
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    # Быстрый отбор ожидающих рассылок ботом.
    op.create_index(
        "ix_broadcasts_pending", "broadcasts", ["id"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_broadcasts_pending", table_name="broadcasts")
    op.drop_table("broadcasts")
