"""Движок сессии.

Как это работает:

1. «Начать сессию» — закрываем браузеры и делаем снимок их папок с данными.
2. Дальше ты пользуешься браузером как обычно: открываешь, закрываешь, входишь
   в аккаунты — всё сохраняется, как на своём компьютере.
3. «Завершить сессию» (или выключение компьютера) — закрываем браузеры и
   возвращаем их папки к снимку. Всё, что появилось за сессию, пропадает.

Журнал (session.json) лежит на диске, пока сессия идёт. Благодаря ему сессия
переживает перезапуск программы и компьютера, а если завершение прервалось
на середине, его можно просто повторить.

Интерфейс (app.py) только вызывает эти методы и ничего не знает о том,
как именно устроена очистка.
"""

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import psutil

from session_controller import browsers as browsers_mod
from session_controller import snapshot
from session_controller.browsers import Browser

log = logging.getLogger(__name__)


class SessionError(Exception):
    pass


class Session:
    def __init__(self, home: Path, browsers: list[Browser]) -> None:
        self.home = home
        self.browsers = browsers
        self.journal_path = home / "session.json"
        self.backup_root = home / "backup"

        self.started_at: datetime | None = None
        self._boot_time: float | None = None
        # Что было на момент начала сессии: [{"browser": Browser, "existed": bool}, ...]
        self._entries: list[dict] = []

    @property
    def is_active(self) -> bool:
        return self.started_at is not None

    def load(self) -> None:
        """Вызвать при запуске программы: подхватить незавершённую сессию, если она есть."""
        for browser in self.browsers:
            snapshot.clean_trash(browser.data_dir.parent)

        try:
            data = json.loads(self.journal_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            # Сессии нет. Если остался снимок от неудачного старта — он не нужен.
            snapshot.delete_tree(self.backup_root)
            return

        self.started_at = datetime.fromisoformat(data["started_at"])
        self._boot_time = data["boot_time"]
        self._entries = [
            {"browser": _browser_from_json(entry["browser"]), "existed": entry["existed"]}
            for entry in data["browsers"]
        ]
        log.info("Найдена незавершённая сессия от %s", self.started_at)

    def installed_browsers(self) -> list[Browser]:
        return [b for b in self.browsers if b.data_dir.is_dir()]

    def running_browsers(self) -> list[Browser]:
        return [b for b in self.installed_browsers() if browsers_mod.is_running(b)]

    def computer_restarted_since_start(self) -> bool:
        """Был ли компьютер перезагружен (или выключен) с начала сессии."""
        if not self.is_active:
            return False
        return abs(psutil.boot_time() - self._boot_time) > 5

    def adopt_current_boot(self) -> None:
        """Сессия пережила перезагрузку и продолжается — запомнить новую загрузку."""
        self._boot_time = psutil.boot_time()
        self._write_journal(self.started_at, self._boot_time, self._entries)

    def start(self) -> None:
        """Начать сессию. Открытые браузеры будут закрыты."""
        if self.is_active:
            raise SessionError("Сессия уже идёт")

        browsers_mod.close(self.browsers)
        snapshot.delete_tree(self.backup_root)

        entries = []
        try:
            for browser in self.browsers:
                existed = browser.data_dir.is_dir()
                if existed:
                    log.info("Снимок: %s (%s)", browser.name, browser.data_dir)
                    snapshot.backup(browser.data_dir, self.backup_root / browser.id)
                entries.append({"browser": browser, "existed": existed})
        except OSError as error:
            log.exception("Не удалось сделать снимок")
            snapshot.delete_tree(self.backup_root)
            raise SessionError(f"Не удалось сохранить состояние браузеров: {error}") from error

        started_at = datetime.now()
        boot_time = psutil.boot_time()
        self._write_journal(started_at, boot_time, entries)

        self.started_at = started_at
        self._boot_time = boot_time
        self._entries = entries
        log.info("Сессия начата")

    def end(self) -> None:
        """Завершить сессию: вернуть браузеры к состоянию до её начала."""
        if not self.is_active:
            raise SessionError("Сессия не запущена")

        browsers_mod.close(entry["browser"] for entry in self._entries)

        failed = []
        for entry in self._entries:
            browser = entry["browser"]
            try:
                if entry["existed"]:
                    snapshot.restore(self.backup_root / browser.id, browser.data_dir)
                else:
                    # Браузер впервые запустили во время сессии — удаляем всё целиком.
                    snapshot.remove(browser.data_dir)
            except OSError:
                log.exception("Не удалось очистить %s", browser.name)
                failed.append(browser.name)

        if failed:
            # Журнал и снимок оставляем: завершение можно будет просто повторить.
            raise SessionError("Не удалось очистить: " + ", ".join(failed))

        snapshot.delete_tree(self.backup_root)
        self.journal_path.unlink(missing_ok=True)
        self.started_at = None
        self._boot_time = None
        self._entries = []
        log.info("Сессия завершена")

    def _write_journal(self, started_at: datetime, boot_time: float, entries: list[dict]) -> None:
        data = {
            "started_at": started_at.isoformat(),
            "boot_time": boot_time,
            "browsers": [
                {"browser": _browser_to_json(e["browser"]), "existed": e["existed"]}
                for e in entries
            ],
        }
        self.home.mkdir(parents=True, exist_ok=True)
        tmp = self.journal_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.journal_path)


def _browser_to_json(browser: Browser) -> dict:
    data = asdict(browser)
    data["data_dir"] = str(browser.data_dir)
    data["process_names"] = list(browser.process_names)
    return data


def _browser_from_json(data: dict) -> Browser:
    return Browser(
        id=data["id"],
        name=data["name"],
        data_dir=Path(data["data_dir"]),
        process_names=tuple(data["process_names"]),
        exe_hint=data.get("exe_hint", ""),
    )
