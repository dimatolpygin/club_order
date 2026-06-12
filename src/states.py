"""FSM-состояния. Параллельно с Redis-хранилищем aiogram пишем текущее состояние
в таблицу club_bot.fsm_states (repo.set_fsm_state) — чтобы видеть, где застрял юзер.
"""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SupportStates(StatesGroup):
    # Ждём текст обращения в поддержку (тема хранится в data["topic"]).
    waiting_message = State()


class AdminStates(StatesGroup):
    # Пошаговый ввод в админ-панели. Контекст (id ступени и т.п.) — в data.
    tier_price = State()
    tier_limit = State()
    tier_name = State()
    tier_period_price = State()  # цена за конкретный период внутри ступени (data: tier_id, months)
    dur_add = State()
    member_id = State()
    member_months = State()
    user_lookup = State()    # поиск участника по tg_id
    broadcast_text = State()  # текст рассылки (подтверждение — кнопкой)
