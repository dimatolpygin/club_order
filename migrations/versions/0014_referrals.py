"""referral_links + referrals + bonus_ledger (цикл 2, этап 17)

Реферальная программа для бань. Три таблицы:

- `referral_links` — персональная реф-ссылка пользователя (один код на tg_id).
  Код кладётся в deep-link `https://t.me/<bot>?start=ref_<code>`.
- `referrals` — связь «кто кого привёл». Привязка фиксируется при переходе новичка
  по ссылке (status='pending'); при первой покупке бани новичком — 'qualified'
  (фиксируем event_id, суммы скидки/бонуса на момент покупки); после даты события
  джоб начисляет бонус пригласившему → 'accrued'. Возврат до события → 'void'
  (анти-возврат: бонус не начисляем). Invitee уникален — привести можно лишь раз.
- `bonus_ledger` — журнал движения бонусов (1 бонус = 1 ₽). delta>0 начисление,
  delta<0 списание (оплата бонусами / ручная корректировка). Баланс = SUM(delta).
  Идемпотентность: частичные уникальные индексы не дают начислить бонус по одной
  реферальной связи дважды и списать по одному платежу дважды.

Суммы рефералки (скидка новичку, бонус пригласившему) хранятся в bot_settings
(ключи referral_newbie_discount / referral_referrer_bonus, дефолты 500/1000),
правятся в админке без рестарта — отдельная таблица настроек не нужна.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014_referrals"
down_revision: Union[str, None] = "0013_tickets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "referral_links",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "referrals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("referrer_tg_id", sa.BigInteger(), nullable=False),
        # Приглашённый может быть приведён только раз (первая привязка побеждает).
        sa.Column("invitee_tg_id", sa.BigInteger(), nullable=False, unique=True),
        # Баня, на которой новичок «квалифицировал» связь (NULL до первой покупки).
        sa.Column("event_id", sa.BigInteger(), nullable=True),
        # pending → qualified → accrued | void.
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        # Суммы фиксируются на момент квалификации (правка дефолтов задним числом не влияет).
        sa.Column("discount_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("bonus_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("qualified_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("accrued_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_referrals_referrer", "referrals", ["referrer_tg_id"])
    op.create_index("ix_referrals_status", "referrals", ["status"])

    op.create_table(
        "bonus_ledger",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        # delta в рублях (1 бонус = 1 ₽): >0 начисление, <0 списание.
        sa.Column("delta", sa.Numeric(10, 2), nullable=False),
        # referral_bonus | spend | refund | manual.
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "referral_id", sa.BigInteger(),
            sa.ForeignKey("referrals.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "payment_id", sa.BigInteger(),
            sa.ForeignKey("payments.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_bonus_ledger_tg", "bonus_ledger", ["tg_id"])
    # Идемпотентность: один бонус на реферальную связь и одно списание на платёж.
    op.create_index(
        "uq_bonus_referral_accrual", "bonus_ledger", ["referral_id"],
        unique=True, postgresql_where=sa.text("reason = 'referral_bonus'"),
    )
    op.create_index(
        "uq_bonus_payment_spend", "bonus_ledger", ["payment_id"],
        unique=True, postgresql_where=sa.text("reason = 'spend'"),
    )


def downgrade() -> None:
    op.drop_index("uq_bonus_payment_spend", table_name="bonus_ledger")
    op.drop_index("uq_bonus_referral_accrual", table_name="bonus_ledger")
    op.drop_index("ix_bonus_ledger_tg", table_name="bonus_ledger")
    op.drop_table("bonus_ledger")
    op.drop_index("ix_referrals_status", table_name="referrals")
    op.drop_index("ix_referrals_referrer", table_name="referrals")
    op.drop_table("referrals")
    op.drop_table("referral_links")
