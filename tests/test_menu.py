"""Изолированный smoke-тест контекстных раскладок меню (этап 31).

Проверяет services.menu без БД: какие кнопки на верхнем уровне у гостя и подписчика,
состав подменю «О клубе», отсутствие промокода на верхнем уровне, компактность и
объединённую раскладку для редактора админки. Запуск: python -m tests.test_menu
"""
from __future__ import annotations

from src.services import menu


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got} expected={expected}")
    assert got == expected, name


def _keys(layout: list[list[str]]) -> list[str]:
    return [k for row in layout for k in row]


def main() -> None:
    guest = _keys(menu._top_layout(False))
    sub = _keys(menu._top_layout(True))
    about = _keys(menu.ABOUTMENU_LAYOUT)

    # Гость: главное действие — вступить; нет управления подпиской.
    check("гость: есть «вступить»", "join" in guest, True)
    check("гость: нет «продлить»", "renew" not in guest, True)
    check("гость: нет «моя подписка»", "mysub" not in guest, True)
    check("гость: «вступить» — первое (главное действие)", guest[0], "join")

    # Подписчик: ОДИН раздел «Моя подписка» (продление — внутри него, не дублируется);
    # нет «вступить».
    check("подписчик: есть «моя подписка»", "mysub" in sub, True)
    check("подписчик: нет «продлить» на верхнем уровне (оно внутри «Моя подписка»)",
          "renew" not in sub, True)
    check("подписчик: нет «вступить»", "join" not in sub, True)
    check("подписчик: «моя подписка» — первое (раздел подписки)", sub[0], "mysub")

    # Промокода на верхнем уровне нет (ввод — в флоу оплаты).
    check("гость: нет промокода наверху", "promo" not in guest, True)
    check("подписчик: нет промокода наверху", "promo" not in sub, True)

    # Хаб «О клубе» есть у обоих; подменю — инфо + рефералка.
    check("гость: есть «О клубе»", "aboutmenu" in guest, True)
    check("подписчик: есть «О клубе»", "aboutmenu" in sub, True)
    check("подменю «О клубе»: состав", about, ["about", "rules", "referral"])

    # Компактность верхнего уровня.
    check("гость: рядов ≤ 3", len(menu._top_layout(False)) <= 3, True)
    check("подписчик: рядов ≤ 4", len(menu._top_layout(True)) <= 4, True)

    # Редактор админки: объединённая раскладка содержит все ключи верхнего уровня.
    union = set(_keys(menu.LAYOUTS["welcome"]))
    top_all = {"join", "mysub", "events", "mytickets", "aboutmenu", "support"}
    check("union для редактора покрывает верхний уровень", top_all.issubset(union), True)
    check("редактор: экран «О клубе» правит инфо-кнопки",
          _keys(menu.LAYOUTS["aboutmenu"]), ["about", "rules", "referral"])

    # «Продлить» — не самостоятельная кнопка меню (живёт внутри «Моя подписка»).
    check("«renew» не в реестре кнопок меню", "renew" not in menu.BUTTON_DEFS, True)

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
