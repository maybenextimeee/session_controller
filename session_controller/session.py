"""Движок сессии.

Как это работает:

1. «Начать сессию» — закрываем выбранные программы и запоминаем, как выглядят
   их файлы со входами в аккаунты (и записи в хранилище паролей Windows).
2. Дальше пользуешься всем как обычно: открываешь, закрываешь, входишь в
   аккаунты — всё сохраняется, как на своём компьютере.
3. «Завершить сессию» (или выключение компьютера) — закрываем программы и
   возвращаем всё к запомненному. То, что появилось за сессию, пропадает.

Журнал (session.json) лежит на диске, пока сессия идёт. Благодаря ему сессия
переживает перезапуск программы и компьютера, а если завершение прервалось
на середине, его можно просто повторить.

Интерфейс (app.py) только вызывает эти методы и ничего не знает о том,
как именно устроена очистка.
"""

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import psutil

from session_controller import credentials, processes, registry, snapshot, winapi
from session_controller.targets import CREDENTIALS, INTERNET_SETTINGS, Target

log = logging.getLogger(__name__)

Progress = Callable[[str], None]


class SessionError(Exception):
    pass


class Session:
    def __init__(self, home: Path, targets: list[Target]) -> None:
        self.home = home
        self.targets = targets
        self.journal_path = home / "session.json"
        self.backup_root = home / "backup"

        self.started_at: datetime | None = None
        self._boot_time: float | None = None
        # Что запомнили в начале сессии, по записи на каждую программу (см. _snapshot).
        self._entries: list[dict] = []

    @property
    def is_active(self) -> bool:
        return self.started_at is not None

    def load(self) -> None:
        """Вызвать при запуске программы: подхватить незавершённую сессию, если она есть."""
        for target in self.targets:
            for path in target.paths:
                snapshot.clean_trash(path.parent)

        try:
            data = json.loads(self.journal_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            # Сессии нет. Если остался снимок от неудачного старта — он не нужен.
            snapshot.delete_tree(self.backup_root)
            return

        self.started_at = datetime.fromisoformat(data["started_at"])
        self._boot_time = data["boot_time"]
        self._entries = data["targets"]
        log.info("Найдена незавершённая сессия от %s", self.started_at)

    def installed_targets(self) -> list[Target]:
        return [t for t in self.targets if t.is_installed()]

    def session_targets(self) -> list[Target]:
        """Программы, которые очищаются в текущей сессии."""
        return [_target_from_entry(entry) for entry in self._entries]

    def running(self, targets: list[Target]) -> list[Target]:
        return processes.running(targets)

    def check_can_close(self, targets: list[Target]) -> None:
        """Ошибка, если Session Controller запущен изнутри одной из этих программ."""
        _refuse_if_launched_from(targets)

    def computer_restarted_since_start(self) -> bool:
        """Был ли компьютер перезагружен (или выключен) с начала сессии."""
        if not self.is_active:
            return False
        return abs(psutil.boot_time() - self._boot_time) > 5

    def adopt_current_boot(self) -> None:
        """Сессия пережила перезагрузку и продолжается — запомнить новую загрузку."""
        self._boot_time = psutil.boot_time()
        self._write_journal()

    def start(self, targets: list[Target], progress: Progress | None = None) -> None:
        """Начать сессию для выбранных программ. Открытые программы будут закрыты."""
        if self.is_active:
            raise SessionError("Сессия уже идёт")
        _refuse_if_launched_from(targets)

        processes.close(targets)
        snapshot.delete_tree(self.backup_root)

        entries = []
        try:
            for target in targets:
                if progress:
                    progress(f"Запоминаю: {target.name}…")
                entries.append(self._snapshot(target))
        except OSError as error:
            log.exception("Не удалось сделать снимок")
            snapshot.delete_tree(self.backup_root)
            raise SessionError(f"Не удалось сохранить состояние: {error}") from error

        self.started_at = datetime.now()
        self._boot_time = psutil.boot_time()
        self._entries = entries
        self._write_journal()
        log.info("Сессия начата: %s", ", ".join(t.name for t in targets))

    def end(self, progress: Progress | None = None) -> None:
        """Завершить сессию: вернуть всё к состоянию до её начала."""
        if not self.is_active:
            raise SessionError("Сессия не запущена")

        targets = self.session_targets()
        _refuse_if_launched_from(targets)
        processes.close(targets)

        failed = []
        for entry in self._entries:
            if progress:
                progress(f"Очищаю: {entry['name']}…")
            try:
                self._restore(entry)
            except OSError:
                log.exception("Не удалось очистить %s", entry["name"])
                failed.append(entry["name"])

        if failed:
            # Журнал и снимок оставляем: завершение можно будет просто повторить.
            raise SessionError("Не удалось очистить: " + ", ".join(failed))

        snapshot.delete_tree(self.backup_root)
        self.journal_path.unlink(missing_ok=True)
        self.started_at = None
        self._boot_time = None
        self._entries = []
        log.info("Сессия завершена")

    # ---------- Снимок и восстановление одной программы ----------

    def _snapshot(self, target: Target) -> dict:
        entry = {
            "id": target.id,
            "name": target.name,
            "kind": target.kind,
            "process_names": list(target.process_names),
            "exe_hint": target.exe_hint,
            "paths": [],
            "registry": [],
            "credentials": [],
        }

        if target.kind == CREDENTIALS:
            entry["credentials"] = [list(item) for item in credentials.list_all()]
            return entry

        for index, path in enumerate(target.paths):
            existed = os.path.lexists(path)
            if existed:
                log.info("Снимок: %s (%s)", target.name, path)
                snapshot.backup(path, self._backup_path(target.id, index), target.skip)
            entry["paths"].append({"path": str(path), "existed": existed})

        for key, name in target.registry_values:
            entry["registry"].append({"key": key, "name": name, "value": registry.read(key, name)})

        return entry

    def _restore(self, entry: dict) -> None:
        if entry["kind"] == CREDENTIALS:
            _delete_new_credentials(entry["credentials"])
            return

        for index, item in enumerate(entry["paths"]):
            path = Path(item["path"])
            if item["existed"]:
                snapshot.restore(self._backup_path(entry["id"], index), path)
            else:
                # Появилось за сессию (например, программу запустили впервые) — удаляем.
                snapshot.remove(path)

        for item in entry["registry"]:
            registry.write(item["key"], item["name"], item["value"])
        if any(item["key"] == INTERNET_SETTINGS for item in entry["registry"]):
            winapi.notify_proxy_changed()

    def _backup_path(self, target_id: str, index: int) -> Path:
        return self.backup_root / target_id / str(index)

    def _write_journal(self) -> None:
        data = {
            "started_at": self.started_at.isoformat(),
            "boot_time": self._boot_time,
            "targets": self._entries,
        }
        self.home.mkdir(parents=True, exist_ok=True)
        tmp = self.journal_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.journal_path)


def _delete_new_credentials(before: list[list]) -> None:
    known = {tuple(item) for item in before}
    for name, kind in credentials.list_all():
        if (name, kind) in known or credentials.is_system(name):
            continue
        try:
            credentials.delete(name, kind)
            log.info("Удалена запись из диспетчера учётных данных: %s", name)
        except OSError:
            # Не блокируем завершение сессии из-за одной записи — только пишем в лог.
            log.exception("Не удалось удалить запись %s", name)


def _refuse_if_launched_from(targets: list[Target]) -> None:
    parent = processes.launched_from(targets)
    if parent:
        raise SessionError(
            f"Session Controller запущен изнутри {parent.name} (например, из его терминала), "
            f"поэтому не может закрыть {parent.name}.\n\n"
            f"Запусти Session Controller отдельно (файлом start.bat) "
            f"или сними галочку «{parent.name}» в списке «Что очищать»."
        )


def _target_from_entry(entry: dict) -> Target:
    return Target(
        entry["id"],
        entry["name"],
        kind=entry["kind"],
        paths=tuple(Path(item["path"]) for item in entry["paths"]),
        process_names=tuple(entry["process_names"]),
        exe_hint=entry["exe_hint"],
    )
