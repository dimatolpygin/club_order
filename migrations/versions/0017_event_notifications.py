"""event_notifications + events.canceled_at (цикл 2, этап 20)

Уведомления по событиям:
  · напоминание за 1 день до мероприятия всем купившим билеты (kind='day_before');
  · отмена события администратором → уведомление купившим + пометка билетов на
    ручной полный возврат (kind='canceled').

Веб-админка отдельный процесс от бота: рассылку шлёт бот. Поэтому отмена в вебе
лишь проставляет `events.canceled_at` (+ is_active=false), а фоновый джоб бота на
ближайшем проходе уведомляет купивших — тот же паттерн, что у отключения подписки
(этап 19). Таблица `event_notifications` (PK event_id+kind) защищает от повторной
рассылки при повторных прогонах планировщика — аналог `subscription_reminders`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017_event_notifications"
down_revision: Union[str, None] = "0016_menu_buttons"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Момент отмены события администратором (NULL — событие не отменено).
    op.add_column(
        "events", sa.Column("canceled_at", sa.TIMESTAMP(timezone=True), nullable=True)
    )

    op.create_table(
        "event_notifications",
        sa.Column(
            "event_id", sa.BigInteger(),
            sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False,
        ),
        # 'day_before' — напоминание за сутки; 'canceled' — отмена события.
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "sent_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("event_id", "kind", name="pk_event_notifications"),
    )


def downgrade() -> None:
    op.drop_table("event_notifications")
    op.drop_column("events", "canceled_at")
