"""referral_rules по категориям + категория/срок начисления в referrals (цикл 3, этап 40)

Реферальная программа перестаёт быть «только про баню».

- `referral_rules` — суммы реф-программы **по категории покупки** (banya, retreat,
  subscription, yoga, consult). Для скидки новичку и для бонуса пригласившему
  отдельно задаётся ТИП значения: 'fixed' (рубли) или 'percent' (процент от суммы
  покупки). Источник истины вместо глобальных ключей bot_settings
  (referral_newbie_discount / referral_referrer_bonus, этап 17).
  Сид: все категории заполняются ТЕКУЩИМИ глобальными суммами (или дефолтами
  500/1000) — поведение бань не меняется, остальные категории стартуют с тех же
  значений и дальше правятся админом по отдельности.

- `referrals.category` — категория покупки, квалифицировавшей связь (до этого была
  только баня, поэтому старые строки бэкфиллим в 'banya').
- `referrals.accrue_after` — момент, с которого бонус пригласившему можно начислять:
  для билетов это дата события (как было), для покупок без даты (подписка, йога,
  консультации) — момент оплаты, т.е. начисление сразу. Джоб начисления теперь
  смотрит на это поле, а не на join с events.

Старые ключи bot_settings остаются нетронутыми (не мешают), но больше не читаются.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0026_referral_categories"
down_revision: Union[str, None] = "0025_screen_photo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Категории покупок, на которые распространяется реф-программа (этап 40).
CATEGORIES = ("banya", "retreat", "subscription", "yoga", "consult")


def upgrade() -> None:
    op.create_table(
        "referral_rules",
        sa.Column("category", sa.Text(), primary_key=True),
        # 'fixed' — значение в рублях; 'percent' — процент от суммы покупки.
        sa.Column(
            "discount_kind", sa.Text(), nullable=False, server_default=sa.text("'fixed'")
        ),
        sa.Column(
            "discount_value", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "bonus_kind", sa.Text(), nullable=False, server_default=sa.text("'fixed'")
        ),
        sa.Column(
            "bonus_value", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "discount_kind IN ('fixed','percent')", name="ck_referral_rules_discount_kind"
        ),
        sa.CheckConstraint(
            "bonus_kind IN ('fixed','percent')", name="ck_referral_rules_bonus_kind"
        ),
        sa.CheckConstraint("discount_value >= 0", name="ck_referral_rules_discount_value"),
        sa.CheckConstraint("bonus_value >= 0", name="ck_referral_rules_bonus_value"),
    )

    # Сид: текущие глобальные суммы этапа 17 (или дефолты 500/1000) во все категории.
    for category in CATEGORIES:
        op.execute(
            f"""
            INSERT INTO referral_rules(category, discount_kind, discount_value,
                                       bonus_kind, bonus_value)
            VALUES(
                '{category}',
                'fixed',
                COALESCE((SELECT value::numeric FROM bot_settings
                          WHERE key = 'referral_newbie_discount'), 500),
                'fixed',
                COALESCE((SELECT value::numeric FROM bot_settings
                          WHERE key = 'referral_referrer_bonus'), 1000)
            )
            ON CONFLICT (category) DO NOTHING
            """
        )

    op.add_column("referrals", sa.Column("category", sa.Text(), nullable=True))
    op.add_column(
        "referrals", sa.Column("accrue_after", sa.TIMESTAMP(timezone=True), nullable=True)
    )
    # Бэкфилл: всё, что было квалифицировано до этапа 40, — бани; момент начисления
    # берём из даты события (ровно то, по чему джоб отбирал строки раньше).
    op.execute("UPDATE referrals SET category = 'banya' WHERE event_id IS NOT NULL")
    op.execute(
        """
        UPDATE referrals r
        SET accrue_after = e.starts_at
        FROM events e
        WHERE r.event_id = e.id AND r.accrue_after IS NULL
        """
    )
    op.create_index("ix_referrals_accrue_after", "referrals", ["accrue_after"])


def downgrade() -> None:
    op.drop_index("ix_referrals_accrue_after", table_name="referrals")
    op.drop_column("referrals", "accrue_after")
    op.drop_column("referrals", "category")
    op.drop_table("referral_rules")
