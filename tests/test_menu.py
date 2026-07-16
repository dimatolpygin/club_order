"""Изолированный smoke-тест раскладок нового главного меню (этап 39).

Проверяет services.menu без БД: схему верхнего уровня у гостя и подписчика
(Клуб · Бани/Ретриты · Йога/Консультации · Пригласить друга · Мои билеты/Поддержка),
вынос рефералки из «О клубе» на главную, скрытые по умолчанию Йога/Консультации и
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

    # Верхняя кнопка «Клуб» контекстна по подписке.
    check("гость: «вступить» — первая (главное действие)", guest[0], "join")
    check("гость: нет «моя подписка»", "mysub" not in guest, True)
    check("подписчик: «моя подписка» — первая", sub[0], "mysub")
    check("подписчик: нет «вступить»", "join" not in sub, True)
    # «Продлить» — не самостоятельная кнопка (внутри «Моя подписка»).
    check("гость: нет «продлить»", "renew" not in guest, True)
    check("подписчик: нет «продлить» на верхнем уровне", "renew" not in sub, True)

    # Схема заказчика (прав.txt): Бани/Ретриты, Йога/Консультации, Пригласить друга,
    # Мои билеты/Поддержка — присутствуют у обоих.
    for who, keys in (("гость", guest), ("подписчик", sub)):
        for key in ("banya", "retreat", "yoga", "consult", "referral", "mytickets", "support"):
            check(f"{who}: есть «{key}»", key in keys, True)
    # Бани и Ретриты стоят одним рядом (два входа рядом) у обоих статусов.
    check("гость: Бани/Ретриты одним рядом", ["banya", "retreat"] in menu.LAYOUT_GUEST, True)
    check("подписчик: Бани/Ретриты одним рядом", ["banya", "retreat"] in menu.LAYOUT_SUB, True)

    # Рефералка переехала из «О клубе» на главную.
    check("рефералка на главной (гость)", "referral" in guest, True)
    check("«О клубе»: только инфо-экраны (без рефералки)", about, ["about", "rules"])
    check("рефералки нет в «О клубе»", "referral" not in about, True)

    # Йога/Консультации скрыты по умолчанию (открываются на этапах 46/47).
    check("йога скрыта по умолчанию", "yoga" in menu.DEFAULT_HIDDEN, True)
    check("консультации скрыты по умолчанию", "consult" in menu.DEFAULT_HIDDEN, True)
    check("бани видимы по умолчанию", "banya" not in menu.DEFAULT_HIDDEN, True)

    # Промокода на верхнем уровне нет (ввод — в флоу оплаты).
    check("гость: нет промокода наверху", "promo" not in guest, True)
    check("подписчик: нет промокода наверху", "promo" not in sub, True)

    # «О клубе» доступен с главной (инфо-экраны не потеряны).
    check("гость: есть «О клубе»", "aboutmenu" in guest, True)
    check("подписчик: есть «О клубе»", "aboutmenu" in sub, True)

    # Редактор админки: объединённая раскладка содержит все ключи верхнего уровня.
    union = set(_keys(menu.LAYOUTS["welcome"]))
    top_all = {
        "join", "mysub", "banya", "retreat", "yoga", "consult",
        "referral", "mytickets", "aboutmenu", "support",
    }
    check("union для редактора покрывает верхний уровень", top_all.issubset(union), True)
    check("редактор: экран «О клубе» правит инфо-кнопки",
          _keys(menu.LAYOUTS["aboutmenu"]), ["about", "rules"])

    # «renew» — не в реестре кнопок меню.
    check("«renew» не в реестре кнопок меню", "renew" not in menu.BUTTON_DEFS, True)
    # Старый общий ключ «events» заменён на banya/retreat.
    check("«events» убран из реестра (заменён на banya/retreat)",
          "events" not in menu.BUTTON_DEFS, True)

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
