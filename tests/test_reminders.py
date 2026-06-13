"""Изолированный smoke-тест логики выбора напоминаний (этап 6).

Проверяет чистую функцию due_reminder_kinds без БД и сети:
последовательность early→soon→last, отсутствие дублей и подавление устаревших
напоминаний у короткой подписки. Запуск: python -m tests.test_reminders
"""
from __future__ import annotations

from src.services.reminders import due_reminder_kinds

OFFSETS = {"early": 3, "soon": 1, "last": 0}  # дефолтные пороги (в единицах)


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got} expected={expected}")
    assert got == expected, name


def main() -> None:
    # Далеко до конца — ничего не шлём.
    check("4 ед. осталось → ничего",
          due_reminder_kinds(4, OFFSETS, set()), ([], None))

    # Вошли в окно early (3): шлём early.
    check("3 ед., ничего не отправлено → early",
          due_reminder_kinds(3, OFFSETS, set()), (["early"], "early"))

    # early уже отправлен, 1 ед. → остаётся только soon.
    check("1 ед., early отправлен → soon",
          due_reminder_kinds(1, OFFSETS, {"early"}),
          (["soon"], "soon"))

    # early+soon отправлены, 0 ед. (последний период) → last.
    check("0 ед., early+soon отправлены → last",
          due_reminder_kinds(0, OFFSETS, {"early", "soon"}),
          (["last"], "last"))

    # Всё отправлено → дублей нет.
    check("0 ед., всё отправлено → ничего",
          due_reminder_kinds(0, OFFSETS, {"early", "soon", "last"}), ([], None))

    # Короткая подписка: сразу 0 ед., ничего не отправлено.
    # Все окна открыты → шлём только last, остальные «займём» без рассылки.
    check("0 ед., короткая подписка → подавляем устаревшие, шлём last",
          due_reminder_kinds(0, OFFSETS, set()),
          (["early", "soon", "last"], "last"))

    # Подписка создана в окне soon (1 ед.), ничего не отправлено.
    check("1 ед., короткая подписка → eligible early+soon, шлём soon",
          due_reminder_kinds(1, OFFSETS, set()),
          (["early", "soon"], "soon"))

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
