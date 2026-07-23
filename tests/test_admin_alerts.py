"""Smoke-тест уведомлений админам о продажах (этап 42).

Без БД: проверяет формат сообщений (шаблон заказчика от 11.07.2026) — состав строк
по билету и по клубу, кликабельную ссылку на покупателя без username, пометку
занятых мест для парных билетов и безлимитную вместимость.
Запуск: python -m tests.test_admin_alerts
"""
from __future__ import annotations

from src import texts


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got} expected={expected}")
    assert got == expected, name


def main() -> None:
    # ── Билет: кто, что, почём + сводка по этому мероприятию ─────────────────
    t = texts.admin_ticket_sale(
        username="ivan", first_name="Иван", user_id=42,
        title="Баня 15 августа", ticket_label="Мужской", price="1 500",
        tickets=3, people=3, amount="4 500", seats=10,
    )
    check("билет: мероприятие", "На мероприятие <b>Баня 15 августа</b>" in t, True)
    check("билет: покупатель с ником", "@ivan" in t, True)
    check("билет: тип и цена", "купил билет (Мужской) за 1 500 ₽" in t, True)
    check("билет: продано из мест", "Всего продано 3 билетов из 10" in t, True)
    check("билет: на сумму", "Всего продано 3 билетов на сумму 4 500 рублей" in t, True)
    check("билет: без пометки мест (нет парных)", "занято мест" in t, False)

    # Парный билет занимает 2 места — расхождение показываем явно.
    pair = texts.admin_ticket_sale(
        username=None, first_name="Аня", user_id=77,
        title="Ретрит", ticket_label="Парный М+Ж", price="6 000",
        tickets=2, people=3, amount="9 000", seats=12,
    )
    check("парный: пометка занятых мест", "(занято мест: 3)" in pair, True)
    check("без username: ссылка на профиль", 'tg://user?id=77' in pair, True)
    check("без username: подпись", "(без username)" in pair, True)

    # Вместимость не задана — «из N» не пишем.
    unlimited = texts.admin_ticket_sale(
        username="x", first_name="X", user_id=1,
        title="Ретрит", ticket_label="Женский", price="100",
        tickets=1, people=1, amount="100", seats=None,
    )
    check("без лимита мест: без «из»", "билетов из" in unlimited, False)
    check("без лимита мест: строка суммы на месте",
          "Всего продано 1 билетов на сумму 100 рублей" in unlimited, True)

    # ── Подписка: новая и продление ──────────────────────────────────────────
    new_sub = texts.admin_subscription_sale(
        username="ivan", first_name="Иван", user_id=42, renewal=False,
        price="2 222", period="1 месяц", members=3, amount="5 000",
    )
    check("подписка: заголовок новой", "<b>НОВАЯ ПОДПИСКА</b>" in new_sub, True)
    check("подписка: действие", "вступил в клуб на 1 месяц за 2 222 ₽" in new_sub, True)
    check("подписка: сводка по клубу",
          "Всего активных подписчиков 3 человек, на сумму 5 000 рублей" in new_sub, True)

    renew = texts.admin_subscription_sale(
        username="ivan", first_name="Иван", user_id=42, renewal=True,
        price="2 222", period="3 месяца", members=3, amount="5 000",
    )
    check("продление: заголовок", "<b>ПРОДЛЕНИЕ ПОДПИСКИ</b>" in renew, True)
    check("продление: действие", "продлил подписку на 3 месяца" in renew, True)

    # ── Выход за неуплату ────────────────────────────────────────────────────
    gone = texts.admin_subscription_expired(
        username=None, first_name=None, user_id=99, members=2, amount="3 000",
    )
    check("выход: заголовок", "<b>ВЫХОД ЗА НЕУПЛАТУ</b>" in gone, True)
    check("выход: удалён из группы", "удалён из группы" in gone, True)
    check("выход: сводка по клубу",
          "Всего активных подписчиков 2 человек, на сумму 3 000 рублей" in gone, True)
    check("выход: профиль без имени", "пользователь" in gone, True)

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
