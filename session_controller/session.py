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

from session_controller.i18n import tr

import json
import logging
import os
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import psutil

from session_controller import credentials, processes, registry, snapshot, winapi
from session_controller.targets import CREDENTIALS, DOWNLOADS, INTERNET_SETTINGS, VPN, Target

log = logging.getLogger(__name__)

# Сообщает о ходе работы: сколько программ уже обработано, сколько всего и
# какая обрабатывается сейчас. Нужно, чтобы интерфейс показывал прогресс.
Progress = Callable[[int, int, str], None]


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
            try:
                snapshot.delete_tree(self.backup_root)
            except OSError:
                log.exception("Не удалось удалить оставшийся снимок")
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
            raise SessionError(tr('Сессия уже идёт'))
        _refuse_if_launched_from(targets)

        for group in _close_groups(targets):
            processes.close(group)
        snapshot.delete_tree(self.backup_root)

        entries = []
        try:
            for index, target in enumerate(targets):
                if progress:
                    progress(index + 1, len(targets), target.name)
                entries.append(self._snapshot(target))
        except OSError as error:
            log.exception("Не удалось сделать снимок")
            snapshot.delete_tree(self.backup_root)
            raise SessionError(tr('Не удалось сохранить состояние: {0}').format(error)) from error

        self.started_at = datetime.now()
        self._boot_time = psutil.boot_time()
        self._entries = entries
        self._write_journal()
        log.info("Сессия начата: %s", ", ".join(t.name for t in targets))

    def end(self, progress: Progress | None = None) -> None:
        """Завершить сессию: вернуть всё к состоянию до её начала."""
        if not self.is_active:
            raise SessionError(tr('Сессия не запущена'))

        targets = self.session_targets()
        _refuse_if_launched_from(targets)
        entries = {entry["id"]: entry for entry in self._entries}
        index = 0
        for group in _close_groups(targets):
            processes.close(group)
            failed = []
            for target in group:
                index += 1
                if progress:
                    progress(index, len(targets), target.name)
                try:
                    self._restore(entries[target.id])
                except OSError as error:
                    log.exception("Не удалось очистить %s", target.name)
                    failed.append(f"{tr(target.name)} — {error}")
            if failed:
                raise SessionError(tr('Не удалось очистить: ') + "\n".join(failed))

        self.finish_without_cleanup()

    def finish_without_cleanup(self) -> None:
        """Забыть снимок и журнал. Программы и их текущее состояние не трогаем."""
        if not self.is_active:
            raise SessionError(tr('Сессия не запущена'))
        # Сначала фиксируем завершение. При сбое в удалении снимка восстановление
        # с частично удалённой копией не запустится после перезагрузки.
        self.journal_path.unlink(missing_ok=True)
        self.started_at = None
        self._boot_time = None
        self._entries = []
        log.info("Сессия завершена")
        try:
            snapshot.delete_tree(self.backup_root)
        except OSError as error:
            raise SessionError(tr('Сессия завершена, но не удалось удалить резервную копию: {0}').format(error)) from error

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

        if target.kind == DOWNLOADS:
            # Саму папку не копируем — она бывает огромной. Хватит списка имён.
            folder = target.paths[0]
            entry["paths"].append({"path": str(folder), "existed": folder.is_dir()})
            entry["downloads"] = _folder_names(folder)
            log.info("Снимок: Загрузки (%s), там %d шт.", folder, len(entry["downloads"]))
            return entry

        for index, path in enumerate(target.paths):
            existed = os.path.lexists(path)
            if existed:
                log.info("Снимок: %s (%s)", target.name, path)
                snapshot.backup(path, self._backup_path(target.id, index), target.skip,
                                chatgpt_profile=target.id == "chatgpt_codex")
            entry["paths"].append({"path": str(path), "existed": existed})

        for key, name in target.registry_values:
            entry["registry"].append({"key": key, "name": name, "value": registry.read(key, name)})

        entry["registry_trees"] = [
            {"key": key, "tree": registry.read_tree(key)} for key in target.registry_keys
        ]
        return entry

    def _restore(self, entry: dict) -> None:
        if entry["kind"] == CREDENTIALS:
            _delete_new_credentials(entry["credentials"])
            return

        if entry["kind"] == DOWNLOADS:
            _delete_new_downloads(Path(entry["paths"][0]["path"]), entry["downloads"])
            return

        if entry["id"] == "chatgpt_codex":
            # Обработать и хранилища настольного ChatGPT, если отдельный файл Codex занят.
            errors = []
            for index, item in enumerate(entry["paths"]):
                source = self._backup_path(entry["id"], index) if item["existed"] else None
                path = Path(item["path"])
                try:
                    try:
                        snapshot.sync_profile(source, path)
                    except OSError as error:
                        if getattr(error, "winerror", None) != 32:
                            raise
                        processes.close([_target_from_entry(entry)])
                        snapshot.sync_profile(source, path)
                except OSError as error:
                    log.exception("Не удалось восстановить профиль %s", path)
                    errors.append(str(error))
            if errors:
                raise OSError("\n".join(errors))
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
        # В журналах старых версий веток реестра нет — поэтому .get.
        for item in entry.get("registry_trees", []):
            registry.write_tree(item["key"], item["tree"])
        if any(item["key"] == INTERNET_SETTINGS for item in entry["registry"]):
            winapi.notify_proxy_changed()

    def new_downloads(self) -> list[Path]:
        """Что появилось в «Загрузках» за сессию — если их очистка включена."""
        for entry in self._entries:
            if entry["kind"] == DOWNLOADS:
                return new_downloads(Path(entry["paths"][0]["path"]), entry["downloads"])
        return []

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


def _close_groups(targets: list[Target]) -> Iterator[list[Target]]:
    apps = [target for target in targets if target.kind != VPN]
    vpns = [target for target in targets if target.kind == VPN]
    if apps:
        yield apps
    if vpns:
        # Программа могла перезапуститься, пока восстанавливались другие профили.
        processes.ensure_closed(apps)
        yield vpns


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


def _folder_names(folder: Path) -> list[str]:
    """Что лежит в папке сейчас — только верхний уровень."""
    try:
        return sorted(item.name for item in folder.iterdir())
    except FileNotFoundError:
        return []


def new_downloads(folder: Path, before: list[str]) -> list[Path]:
    """Файлы и папки, которых не было в списке before.

    Имена сравниваем без учёта регистра, как Windows: «Отчёт.pdf» и «отчёт.pdf» —
    один и тот же файл, и его, раз он был до сессии, не трогаем.
    """
    known = {name.casefold() for name in before}
    try:
        return sorted((item for item in folder.iterdir() if item.name.casefold() not in known),
                      key=lambda item: item.name.casefold())
    except FileNotFoundError:
        return []


def _delete_new_downloads(folder: Path, before: list[str]) -> None:
    """Удалить насовсем то, что появилось в «Загрузках» за сессию. Саму папку
    и то, что лежало в ней раньше, не трогаем."""
    failed = []
    for item in new_downloads(folder, before):
        try:
            snapshot.remove(item)
            log.info("Удалено из «Загрузок»: %s", item.name)
        except OSError:
            log.exception("Не удалось удалить из «Загрузок»: %s", item)
            failed.append(item.name)
    if failed:
        # Скорее всего, файл открыт в другой программе. Журнал остаётся —
        # завершение можно повторить, закрыв этот файл.
        raise OSError("не удалось удалить " + ", ".join(failed))


def _refuse_if_launched_from(targets: list[Target]) -> None:
    parent = processes.launched_from(targets)
    if parent:
        raise SessionError(
            tr('Session Controller запущен изнутри {0} (например, из его терминала), поэтому не может закрыть {1}.\n\nЗапусти Session Controller отдельно (файлом start.bat) или сними галочку «{2}» в списке «Что очищать».').format(tr(parent.name), tr(parent.name), tr(parent.name))
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
