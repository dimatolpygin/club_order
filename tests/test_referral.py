"""Изолированный smoke-тест чистых хелперов рефералки (этап 17).

Проверяет services.referral без БД и сети: генерацию кода, сборку и разбор
deep-link `start`-payload. Запуск: python -m tests.test_referral
"""
from __future__ import annotations

from src.services import referral as ref


def check(name: str, got, expected) -> None:
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {name}: got={got} expected={expected}")
    assert got == expected, name


def main() -> None:
    # Код: фиксированная длина, только из разрешённого алфавита.
    code = ref.new_code()
    check("код: длина 8", len(code), 8)
    check("код: только из алфавита",
          all(ch in "ABCDEFGHJKMNPQRSTUVWXYZ23456789" for ch in code), True)
    check("код: два вызова различаются (вероятностно)",
          ref.new_code() != ref.new_code() or ref.new_code() != ref.new_code(), True)

    # Deep-link и payload.
    check("payload: префикс ref_", ref.start_payload("ABC123"), "ref_ABC123")
    check("ссылка: полный вид",
          ref.deep_link("neirosha1_bot", "ABC123"),
          "https://t.me/neirosha1_bot?start=ref_ABC123")

    # Разбор payload.
    check("разбор: валидный ref_-payload → код (верхний регистр)",
          ref.parse_start_payload("ref_abc123"), "ABC123")
    check("разбор: не реферальный payload → None",
          ref.parse_start_payload("menu"), None)
    check("разбор: пусто/None → None",
          (ref.parse_start_payload(None), ref.parse_start_payload("")), (None, None))
    check("разбор: пустой код после префикса → None",
          ref.parse_start_payload("ref_"), None)
    check("разбор: мусор в коде → None",
          ref.parse_start_payload("ref_abc!@#"), None)
    # Круговой обход: payload(code) → parse вернёт тот же код.
    c = ref.new_code()
    check("round-trip: parse(start_payload(code)) == code",
          ref.parse_start_payload(ref.start_payload(c)), c)

    print("\nВсе проверки пройдены.")


if __name__ == "__main__":
    main()
