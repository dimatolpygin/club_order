"""Согласие на обработку персональных данных (этап 49, 152-ФЗ).

Фиксируем факт согласия у пользователя: дата (`pd_consent_at`) и версия текста
(`pd_consent_version`). NULL = согласие ещё не дано. Версия нужна, чтобы при
существенной правке «Политики» повторно спросить согласие (бампом константы
services.consent.PD_CONSENT_VERSION) — старое согласие с меньшей версией уже не
считается. Существующие пользователи получают NULL и увидят экран согласия при
следующем /start, доступ при этом не теряют (гейт только на стартовом экране бота).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0032_pd_consent"
down_revision: Union[str, None] = "0031_consult_packages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("pd_consent_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("users", sa.Column("pd_consent_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "pd_consent_version")
    op.drop_column("users", "pd_consent_at")
