"""FSM-состояния. Параллельно с Redis-хранилищем aiogram пишем текущее состояние
в таблицу club_bot.fsm_states (repo.set_fsm_state) — чтобы видеть, где застрял юзер.
"""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SupportStates(StatesGroup):
    # Ждём текст обращения в поддержку (тема хранится в data["topic"]).
    waiting_message = State()
