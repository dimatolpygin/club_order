"""admin_users: учётные записи администраторов веб-панели

Revision ID: 0011_admin_users
Revises: 0010_user_events
Create Date: 2026-06-22

Логины/пароли для входа в веб-админку (цикл 2, этап 11). Пароль хранится только
в виде хэша (pbkdf2_sha256, см. src/webadmin/auth.py). Это НЕ Telegram-админы
(`admin_ids`/`/admin`) — отдельная сущность для веб-входа.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011_admin_users"
down_revision: Union[str, None] = "0010_user_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("login", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ux_admin_users_login", "admin_users", ["login"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ux_admin_users_login", table_name="admin_users")
    op.drop_table("admin_users")
