"""duration_units: единицы длительности (минута/час/день/месяц) для гибких подписок

Revision ID: 0006_duration_units
Revises: 0005_subscription_lifecycle
Create Date: 2026-06-13

Раньше длительность была только в месяцах. Теперь у каждой длительности есть
единица (unit): minute/hour/day/month. Числовое поле `months` сохраняет имя по
истории, но трактуется как ЗНАЧЕНИЕ периода (сколько единиц). Цена за период
задаётся админом per (ступень, значение, единица) в tier_prices. Снимок единицы
кладётся в payments/subscriptions, чтобы корректно считать и продлевать end_date.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_duration_units"
down_revision: Union[str, None] = "0005_subscription_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def _unit_col() -> sa.Column:
    return sa.Column("unit", sa.Text(), nullable=False, server_default="month")


def upgrade() -> None:
    # durations: единица + уникальность по (значение, единица).
    op.add_column("durations", _unit_col())
    op.drop_constraint("durations_months_key", "durations", type_="unique")
    op.create_unique_constraint(
        "uq_durations_value_unit", "durations", ["months", "unit"]
    )

    # tier_prices: цена за период теперь привязана к (ступень, значение, единица).
    op.add_column("tier_prices", _unit_col())
    op.drop_constraint("uq_tier_prices_tier_months", "tier_prices", type_="unique")
    op.create_unique_constraint(
        "uq_tier_prices_tier_period", "tier_prices", ["tier_id", "months", "unit"]
    )

    # Снимок единицы периода на платеже и подписке (для расчёта/продления end_date).
    op.add_column("payments", _unit_col())
    op.add_column("subscriptions", _unit_col())


def downgrade() -> None:
    op.drop_column("subscriptions", "unit")
    op.drop_column("payments", "unit")
    op.drop_constraint("uq_tier_prices_tier_period", "tier_prices", type_="unique")
    op.create_unique_constraint(
        "uq_tier_prices_tier_months", "tier_prices", ["tier_id", "months"]
    )
    op.drop_column("tier_prices", "unit")
    op.drop_constraint("uq_durations_value_unit", "durations", type_="unique")
    op.create_unique_constraint("durations_months_key", "durations", ["months"])
    op.drop_column("durations", "unit")
