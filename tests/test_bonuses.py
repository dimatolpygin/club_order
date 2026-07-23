"""Smoke-тест раздела «Мои бонусы» и кнопок к автосообщениям (этап 41).

Без БД: проверяет текст экрана (три числа, пояснение про «скоро начислится»,
пустое состояние) и состав клавиатур автосообщений — что напоминание о событии
ведёт в «Мои билеты», а сообщение о бонусах в «Мои бонусы»/«Главное меню».
Запуск: python -m tests.test_bonuses
"""
from __future__ import annotations

from src import keyboards as kb
from src import texts


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got} expected={expected}")
    assert got == expected, name


def _callbacks(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]


def _labels(markup) -> list[str]:
    return [b.text for row in markup.inline_keyboard for b in row]


def main() -> None:
    # ── Экран «Мои бонусы»: три числа ────────────────────────────────────────
    full = texts.my_bonuses(1500, 1000, 2500)
    check("экран: доступно", "Доступно сейчас: <b>1500 ₽</b>" in full, True)
    check("экран: скоро начислится", "Скоро начислится: <b>1000 ₽</b>" in full, True)
    check("экран: всего", "Всего начислено за всё время: <b>2500 ₽</b>" in full, True)
    check("экран: пояснение про дату события", "после даты мероприятия" in full, True)

    # Нечего ждать — строку «скоро начислится» и пояснение не показываем.
    no_pending = texts.my_bonuses(300, 0, 300)
    check("нет будущих: без строки «скоро»", "Скоро начислится" in no_pending, False)
    check("нет будущих: без пояснения", "после даты мероприятия" in no_pending, False)
    check("нет будущих: доступно на месте", "Доступно сейчас: <b>300 ₽</b>" in no_pending, True)

    # Пустое состояние — подсказка пригласить друга.
    empty = texts.my_bonuses(0, 0, 0)
    check("пусто: подсказка про приглашение", "Пригласи друга" in empty, True)
    check("не пусто: без подсказки", "Пригласи друга" in full, False)

    # Потратил больше, чем осталось: «всего» не уменьшается вслед за балансом.
    spent = texts.my_bonuses(0, 0, 1000)
    check("после трат: всего сохраняется",
          "Всего начислено за всё время: <b>1000 ₽</b>" in spent, True)

    # ── Клавиатуры автосообщений ─────────────────────────────────────────────
    reminder = _callbacks(kb.event_reminder_kb())
    check("напоминание о событии → «Мои билеты»", kb.NAV_MYTICKETS in reminder, True)
    check("напоминание: подпись кнопки", "Мои билеты" in _labels(kb.event_reminder_kb()), True)

    accrued = _callbacks(kb.bonus_accrued_kb())
    check("начисление → «Мои бонусы»", kb.NAV_BONUSES in accrued, True)
    check("начисление → «Главное меню»", kb.NAV_START in accrued, True)

    # ── Вход в раздел с экрана «Пригласить друга» ────────────────────────────
    ref_screen = _callbacks(kb.referral_link_kb("https://t.me/bot?start=ref_abc"))
    check("экран рефералки → «Мои бонусы»", kb.NAV_BONUSES in ref_screen, True)

    # Из «Моих бонусов» есть выход (не тупик).
    bonuses = _callbacks(kb.bonuses_kb())
    check("бонусы → пригласить друга", kb.NAV_REFERRAL in bonuses, True)
    check("бонусы → главное меню", kb.NAV_START in bonuses, True)

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
