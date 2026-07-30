"""Пакеты консультаций (этап 47): сид продуктов услуги category='consult'.

Консультации — НЕ событие (как йога, этап 46): общий движок «покупка услуги без
даты/счётчика + редирект к менеджеру». Отличие от йоги — продаётся не «цена ×
количество», а готовый ПАКЕТ на N консультаций со своей ценой (выгода за штуку
задаётся ценой пакета вручную, не формулой). Поэтому каждый пакет — отдельная
строка `service_products` (category='consult'), а покупка идёт в 1 экземпляр
(quantity=1): число консультаций несёт название пакета.

Сид — четыре пакета 1/4/8/12 с ПЛЕЙСХОЛДЕР-ценами (админ правит их в разделе
«Консультации» веб-админки, там же вкл/выкл). subscriber_discount_percent=0 —
скидку участнику клуба задаёт админ. Промокоды и бонусы к консультациям включает
код этапа 47 (в отличие от йоги, где они не нужны). Контакт менеджера-редиректа —
общий с йогой (bot_settings `manager_url`, @zhannazlotnikova).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0031_consult_packages"
down_revision: Union[str, None] = "0030_service_products"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Плейсхолдер-цены отражают «выгоду за штуку» (пакет дешевле N разовых) —
    # админ поправит по факту в разделе «Консультации».
    op.execute(
        """
        INSERT INTO service_products
            (category, code, title, price, subscriber_discount_percent, is_active, sort_order)
        VALUES
            ('consult', 'p1',  '1 консультация',   3000,  0, TRUE, 1),
            ('consult', 'p4',  '4 консультации',   11000, 0, TRUE, 2),
            ('consult', 'p8',  '8 консультаций',   20000, 0, TRUE, 3),
            ('consult', 'p12', '12 консультаций',  28000, 0, TRUE, 4)
        ON CONFLICT (category, code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM service_products WHERE category = 'consult'")
