"""Услуги «по количеству» без даты/мест: йога и консультации (цикл 3, этапы 46/47)

Йога и консультации — НЕ события (нет даты, мест и счётчика остатка). Это продажа
услуги «по количеству» с редиректом к менеджеру после оплаты. Общая таблица
`service_products` описывает продаваемые продукты по категориям:
  · yoga    — «индивидуальное»/«групповое» занятие (кол-во выбирает пользователь);
  · consult — пакеты 1/4/8/12 (этап 47).

Цена продукта — за единицу; сумма = цена × количество. Скидка подписчику — процентом
на продукт (как у мероприятий). Промокоды/бонусы к услугам подключим на этапе 47.

Платёж услуги идёт через общий конвейер (`payments.kind='service'`): к строке
платежа добавлены `service_product_id` (какой продукт) и `quantity` (сколько единиц);
`event_id`/`ticket_id` не заполняются — билет и доступ в группу услуга не даёт.

Сид: две позиции йоги с ПЛЕЙСХОЛДЕР-ценами (2000/1000 ₽) — админ правит их в разделе
«Йога» веб-админки. Контакт менеджера — в bot_settings (ключ `manager_url`, без
миграции), дефолт — @zhannazlotnikova.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0030_service_products"
down_revision: Union[str, None] = "0029_event_price_tiers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS service_products (
            id                          SERIAL PRIMARY KEY,
            category                    TEXT NOT NULL,
            code                        TEXT NOT NULL,
            title                       TEXT NOT NULL,
            price                       INTEGER NOT NULL DEFAULT 0,
            subscriber_discount_percent INTEGER NOT NULL DEFAULT 0,
            is_active                   BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order                  INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT ux_service_product UNIQUE (category, code)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_service_products_category "
        "ON service_products(category)"
    )

    # Платёж услуги: какой продукт и сколько единиц (билет/событие не заполняются).
    op.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS service_product_id INTEGER")
    op.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS quantity INTEGER")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_payments_service_product'
            ) THEN
                ALTER TABLE payments
                    ADD CONSTRAINT fk_payments_service_product
                    FOREIGN KEY (service_product_id)
                    REFERENCES service_products(id) ON DELETE SET NULL;
            END IF;
        END $$
        """
    )

    # Сид продуктов йоги (плейсхолдер-цены — админ поправит в разделе «Йога»).
    op.execute(
        """
        INSERT INTO service_products
            (category, code, title, price, subscriber_discount_percent, is_active, sort_order)
        VALUES
            ('yoga', 'individual', 'Индивидуальное занятие', 2000, 0, TRUE, 1),
            ('yoga', 'group',      'Групповое занятие',       1000, 0, TRUE, 2)
        ON CONFLICT (category, code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE payments DROP CONSTRAINT IF EXISTS fk_payments_service_product")
    op.execute("ALTER TABLE payments DROP COLUMN IF EXISTS quantity")
    op.execute("ALTER TABLE payments DROP COLUMN IF EXISTS service_product_id")
    op.execute("DROP TABLE IF EXISTS service_products")
