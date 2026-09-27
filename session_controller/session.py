"""Движок сессии.

Здесь живёт вся логика «начать / завершить сессию». Интерфейс (app.py) только
вызывает эти методы и ничего не знает о том, как именно происходит очистка.

Сейчас это заготовка: методы только меняют состояние. Реальная работа
(временный профиль браузера, журнал, очистка) появится на Этапе 1 — см. docs/PLAN.md.
"""

from datetime import datetime


class Session:
    def __init__(self) -> None:
        self.started_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.started_at is not None

    def start(self) -> None:
        if self.is_active:
            raise RuntimeError("Сессия уже идёт")
        self.started_at = datetime.now()
        # TODO (Этап 1): создать временный профиль и открыть в нём браузер.

    def end(self) -> None:
        if not self.is_active:
            raise RuntimeError("Сессия не запущена")
        # TODO (Этап 1): закрыть браузер сессии и удалить его профиль.
        self.started_at = None
