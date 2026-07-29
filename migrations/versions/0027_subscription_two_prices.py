"""Две цены подписки: вход/продление вместо ступеней по местам (цикл 3, этап 43)

Заказчик убирает авто-ступени цены по числу занятых мест совсем (упрощение цикла 1).
Остаются ровно ДВЕ цены (₽/мес), обе в bot_settings:
  · subscription_entry_price   — цена ВХОДА (новичок / после перерыва);
  · subscription_renewal_price — цена ПРОДЛЕНИЯ (непрерывный подписчик).

Регулировка стоимости для первых участников — теперь промокодами (этап 7), а не
ступенью для первых мест.

Сид: обе цены заполняются ТЕКУЩЕЙ входной ставкой (monthly_price активной ступени
с наименьшим sort_order) — цена для пользователей не меняется до правки админом.
Так существующие подписки не дорожают/не ломаются: продление считается по новой
цене продления, которая на момент миграции равна прежней входной ставке.

Таблицы price_tiers / tier_prices НЕ удаляются (исторические платежи/подписки
ссылаются на tier_id по FK). Движок цены их больше не читает: расчёт ставки по
местам отключён в services.tariffs, а веб-админка правит две цены в настройках.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0027_subscription_two_prices"
down_revision: Union[str, None] = "0026_referral_categories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KEY_ENTRY = "subscription_entry_price"
KEY_RENEWAL = "subscription_renewal_price"
# Страховочный дефолт, если ни одной активной ступени нет (пустая БД/тесты).
_FALLBACK = "1000"


def _seed(key: str) -> None:
    op.execute(
        f"""
        INSERT INTO bot_settings(key, value)
        VALUES(
            '{key}',
            COALESCE(
                (SELECT monthly_price::text FROM price_tiers
                 WHERE is_active = true ORDER BY sort_order, id LIMIT 1),
                '{_FALLBACK}'
            )
        )
        ON CONFLICT (key) DO NOTHING
        """
    )


def upgrade() -> None:
    _seed(KEY_ENTRY)
    _seed(KEY_RENEWAL)


def downgrade() -> None:
    op.execute(f"DELETE FROM bot_settings WHERE key IN ('{KEY_ENTRY}', '{KEY_RENEWAL}')")
