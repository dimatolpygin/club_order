"""Признак зафиксированной промо-цены подписки (цикл 3, этап 44)

Приоритет промокода над скидкой продления. До этапа 43 продление шло по
`subscriptions.fixed_price` (в т.ч. по цене, зафиксированной fixes_price-промокодом).
Этап 43 переключил ВСЕ продления на общую цену продления (renewal_rate) — и этим
случайно обнулил фиксацию промо-цены: подписчик, купивший по спец-цене промокода,
на продлении стал платить обычную цену продления.

Этап 44 возвращает приоритет промокода: если за подпиской закреплена промо-цена
(промокод с fixes_price=true), продление считается по ней, скидка продления НЕ
суммируется. Отличить такую подписку от обычной по `source='promo'` нельзя —
процентный промокод тоже даёт source='promo', но цену не фиксирует. Поэтому вводим
явный флаг `price_locked`.

  · price_locked=false (дефолт) — обычная подписка/процентный промокод: продление
    по текущей цене продления (renewal_rate);
  · price_locked=true — за подпиской закреплена промо-цена (fixed_price): продление
    по ней.

Флаг ставится в момент активации платежа (repo.activate_payment) по промокоду с
fixes_price. Бэкофилл: помечаем true уже оформленные подписки, созданные платежом с
fixes_price-промокодом.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0028_subscription_price_lock"
down_revision: Union[str, None] = "0027_subscription_two_prices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE subscriptions "
        "ADD COLUMN IF NOT EXISTS price_locked BOOLEAN NOT NULL DEFAULT false"
    )
    # Бэкофилл: подписки, оформленные платежом с промокодом-фиксатором цены.
    op.execute(
        """
        UPDATE subscriptions s
        SET price_locked = true
        FROM payments p
        JOIN promo_codes pc ON pc.id = p.promo_id
        WHERE p.subscription_id = s.id AND pc.fixes_price = true
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE subscriptions DROP COLUMN IF EXISTS price_locked")
