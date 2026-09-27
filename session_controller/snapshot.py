"""Снимок папки или файла и возврат к нему.

Всё, что происходит за сессию (входы в аккаунты, cookies, пароли), хранится
в файлах программ. Перед сессией копируем их, в конце возвращаем копию
на место — и компьютер снова такой, каким был до тебя.
"""

import fnmatch
import os
import shutil
import stat
import sys
import time
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path

# Кэш не хранит входы в аккаунты, но весит много. Не копируем его.
SKIPPED_NAMES = (
    # Chromium и Electron: Chrome, Edge, Яндекс, Opera, Discord, VS Code, Steam…
    "Cache", "Code Cache", "GPUCache", "GrShaderCache", "GraphiteDawnCache", "ShaderCache",
    "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache", "CacheStorage", "ScriptCache",
    "Crashpad",
    # Firefox
    "cache2", "startupCache",
    # Файлы-замки: существуют только пока программа открыта
    "lockfile", "parent.lock",
)

TRASH_PREFIX = ".sc-trash-"


def backup(source: Path, destination: Path, skip: Iterable[str] = ()) -> None:
    """Скопировать папку или файл source в destination."""
    if os.path.isdir(_fs(source)):
        ignore = _make_ignore(SKIPPED_NAMES + tuple(skip))
        _retry(lambda: shutil.copytree(
            _fs(source), _fs(destination), ignore=ignore, dirs_exist_ok=True
        ))
    else:
        os.makedirs(_fs(destination.parent), exist_ok=True)
        _retry(lambda: shutil.copy2(_fs(source), _fs(destination)))


def restore(backup_path: Path, target: Path) -> None:
    """Вернуть target к состоянию из backup_path. Сам backup_path не трогаем."""
    remove(target)
    if os.path.isdir(_fs(backup_path)):
        _retry(lambda: shutil.copytree(_fs(backup_path), _fs(target), dirs_exist_ok=True))
    else:
        os.makedirs(_fs(target.parent), exist_ok=True)
        _retry(lambda: shutil.copy2(_fs(backup_path), _fs(target)))


def remove(target: Path) -> None:
    """Удалить папку или файл.

    Папку сначала переименовываем — это мгновенно, и входы в аккаунты пропадают
    сразу. Потом уже спокойно удаляем. Если удаление не успело завершиться
    (например, компьютер выключился), остаток подчистит clean_trash().
    """
    path = _fs(target)
    if not os.path.lexists(path):
        return
    if os.path.isdir(path) and not os.path.islink(path):
        trash = target.with_name(TRASH_PREFIX + uuid.uuid4().hex)
        _retry(lambda: os.rename(path, _fs(trash)))
        delete_tree(trash)
    else:
        _retry(lambda: _remove_file(path))


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


def _make_ignore(patterns: tuple[str, ...]) -> Callable[[str, list[str]], list[str]]:
    def ignore(_directory: str, names: list[str]) -> list[str]:
        return [n for n in names if any(fnmatch.fnmatch(n, p) for p in patterns)]

    return ignore


def _remove_file(path: str) -> None:
    if os.path.lexists(path):
        # В Windows нельзя удалить файл «только для чтения» — снимаем атрибут.
        os.chmod(path, stat.S_IWRITE)
        os.remove(path)


def _rmtree(path: str) -> None:
    def make_writable_and_retry(func, failed_path, _exc) -> None:
        os.chmod(failed_path, stat.S_IWRITE)
        func(failed_path)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=make_writable_and_retry)
    else:
        shutil.rmtree(path, onerror=make_writable_and_retry)


def _retry(action: Callable[[], object], attempts: int = 10, delay: float = 0.5) -> None:
    """Повторить действие несколько раз.

    Сразу после закрытия программы Windows может ещё пару мгновений держать её
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
