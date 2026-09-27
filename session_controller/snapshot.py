"""Снимок папки и возврат к нему.

Всё, что происходит за сессию (входы в аккаунты, cookies, пароли), хранится
в папке браузера. Перед сессией копируем эту папку, в конце возвращаем копию
на место — и компьютер снова такой, каким был до тебя.
"""

import os
import shutil
import stat
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

# Кэш не хранит входы в аккаунты, но весит много. Не копируем его.
SKIPPED_NAMES = frozenset({
    # Chromium: Chrome, Edge, Яндекс, Opera, Brave, Vivaldi
    "Cache", "Code Cache", "GPUCache", "GrShaderCache", "GraphiteDawnCache", "ShaderCache",
    "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache", "CacheStorage", "ScriptCache",
    "Crashpad",
    # Firefox
    "cache2", "startupCache",
    # Файлы-замки: существуют только пока браузер открыт
    "lockfile", "parent.lock",
})

TRASH_PREFIX = ".sc-trash-"


def backup(source: Path, destination: Path) -> None:
    _retry(lambda: shutil.copytree(
        _fs(source), _fs(destination), ignore=_skip_cache, dirs_exist_ok=True
    ))


def restore(backup_dir: Path, target: Path) -> None:
    """Вернуть папку target к состоянию из backup_dir. Сам backup_dir не трогаем."""
    remove(target)
    _retry(lambda: shutil.copytree(_fs(backup_dir), _fs(target), dirs_exist_ok=True))


def remove(target: Path) -> None:
    """Удалить папку.

    Сначала переименовываем её — это мгновенно, и входы в аккаунты пропадают
    сразу. Потом уже спокойно удаляем. Если удаление не успело завершиться
    (например, компьютер выключился), остаток подчистит clean_trash().
    """
    if not os.path.lexists(_fs(target)):
        return
    trash = target.with_name(TRASH_PREFIX + uuid.uuid4().hex)
    _retry(lambda: os.rename(_fs(target), _fs(trash)))
    delete_tree(trash)


def clean_trash(folder: Path) -> None:
    """Удалить недоудалённые остатки после remove()."""
    if not folder.is_dir():
        return
    for leftover in folder.glob(TRASH_PREFIX + "*"):
        delete_tree(leftover)


def delete_tree(path: Path) -> None:
    def action() -> None:
        if os.path.lexists(_fs(path)):
            _rmtree(_fs(path))

    _retry(action)


def _skip_cache(_directory: str, names: list[str]) -> list[str]:
    return [name for name in names if name in SKIPPED_NAMES]


def _rmtree(path: str) -> None:
    def make_writable_and_retry(func, failed_path, _exc) -> None:
        # В Windows нельзя удалить файл «только для чтения» — снимаем атрибут.
        os.chmod(failed_path, stat.S_IWRITE)
        func(failed_path)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=make_writable_and_retry)
    else:
        shutil.rmtree(path, onerror=make_writable_and_retry)


def _retry(action: Callable[[], object], attempts: int = 10, delay: float = 0.5) -> None:
    """Повторить действие несколько раз.

    Сразу после закрытия браузера Windows может ещё пару мгновений держать его
    файлы (или их проверяет антивирус), поэтому первая попытка иногда не проходит.
    """
    for attempt in range(attempts):
        try:
            action()
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def _fs(path: Path) -> str:
    r"""Путь для файловых операций.

    В Windows добавляем префикс \\?\, иначе пути длиннее 260 символов не
    скопируются, а внутри профилей браузеров такие встречаются.
    """
    full = os.path.abspath(path)
    if sys.platform != "win32" or full.startswith("\\\\?\\"):
        return full
    if full.startswith("\\\\"):  # сетевой путь \\server\share
        return "\\\\?\\UNC\\" + full[2:]
    return "\\\\?\\" + full
