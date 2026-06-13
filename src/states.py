"""FSM-состояния. Параллельно с Redis-хранилищем aiogram пишем текущее состояние
в таблицу club_bot.fsm_states (repo.set_fsm_state) — чтобы видеть, где застрял юзер.
"""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SupportStates(StatesGroup):
    # Ждём текст обращения в поддержку (тема хранится в data["topic"]).
    waiting_message = State()


class PromoStates(StatesGroup):
    # Ждём, пока пользователь пришлёт промокод сообщением.
    waiting_code = State()


class AdminStates(StatesGroup):
    # Пошаговый ввод в админ-панели. Контекст (id ступени и т.п.) — в data.
    tier_price = State()
    tier_limit = State()
    tier_name = State()
    tier_period_price = State()  # цена за период (data: tier_id, value, unit)
    dur_add_value = State()   # ввод числа новой длительности (единица — кнопкой)
    dur_add_unit = State()    # выбор единицы новой длительности (data: dur_value)
    member_id = State()
    member_value = State()    # ввод числа срока выдаваемой подписки
    member_unit = State()     # выбор единицы срока (data: member_tg_id, member_value)
    user_lookup = State()    # поиск участника по tg_id
    broadcast_compose = State()  # сбор текста и/или фото рассылки (отправка — кнопкой)
    # Создание промокода (тип и фиксация цены — кнопками, остальное вводом).
    promo_code = State()      # ввод самого кода
    promo_value = State()     # значение (ставка ₽/мес или процент), data: kind
    promo_limit = State()     # лимит активаций (0 = безлимит)
    promo_expiry = State()    # срок действия в днях (0 = бессрочно)
    # Правка порогов напоминаний на лету (единица — кнопкой). data: rem_kind.
    rem_offset = State()
