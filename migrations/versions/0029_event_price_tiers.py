"""Динамические цены ранним покупателям: пороги по датам (цикл 3, этап 45)

«Чем раньше куплен билет — тем дешевле». У мероприятия задаются пороги вида
«за N дней до события → цена» отдельно по типу билета. Цена момента: среди
порогов типа, у которых `days_before >= дней_до_события`, берётся тариф с
НАИМЕНЬШИМ `days_before` (самый близкий к дате); если подходящего порога нет —
базовая цена типа из `event_ticket_prices`. Так цена растёт при приближении даты,
а до первого порога действует базовая цена (нет регресса для событий без порогов).

Цена фиксируется в момент создания платежа (расчёт идёт в `tickets.event_prices_now`
на текущее время), поэтому смена порогов не меняет уже выставленный счёт.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0029_event_price_tiers"
down_revision: Union[str, None] = "0028_subscription_price_lock"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS event_price_tiers (
            id           SERIAL PRIMARY KEY,
            event_id     INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            ticket_type  TEXT NOT NULL,
            days_before  INTEGER NOT NULL,
            price        INTEGER NOT NULL,
            CONSTRAINT ux_event_price_tier UNIQUE (event_id, ticket_type, days_before)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_event_price_tiers_event "
        "ON event_price_tiers(event_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS event_price_tiers")
