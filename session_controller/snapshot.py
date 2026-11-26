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
from concurrent.futures import Future, ThreadPoolExecutor
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


# Относительно корня .codex. В каталогах пользователя те же имена могут
# означать совсем другие файлы. Служебные ресурсы оставляем на месте на обоих этапах.
_CODEX_RUNTIME = {
    ".": (".codex-provisioning-*.guard", ".sandbox", ".sandbox-bin", ".sandbox-secrets"),
    ".tmp": ("plugins", "plugins-clone-*", "bundled-marketplaces"),
    "plugins/.plugin-appserver": ("*.exe",),
}


_RUNTIME_BY_ROOT = {
    ".codex": _CODEX_RUNTIME,
    "localcache": {
        "roaming/codex/web/codex": ("component_crx_cache", "extensions_crx_cache", "WasmTtsEngine",
                                      "WidevineCdm", "OnDeviceHeadSuggestModel", "CertificateRevocation"),
    },
}


def _runtime_names(root: Path, directory: Path, names: Iterable[str]) -> set[str]:
    rules = _RUNTIME_BY_ROOT.get(root.name.casefold(), {})
    patterns = rules.get(directory.relative_to(root).as_posix().casefold(), ())
    if not patterns:
        return set()
    return {name for name in names if any(fnmatch.fnmatchcase(name.casefold(), p.casefold()) for p in patterns)}


def backup(source: Path, destination: Path, skip: Iterable[str] = (), *, chatgpt_profile: bool = False) -> None:
    """Скопировать папку или файл source в destination."""
    if os.path.isdir(_fs(source)):
        skip_cache = _make_ignore(SKIPPED_NAMES + tuple(skip))
        root = Path(_fs(source))

        def ignore(directory: str, names: list[str]) -> set[str]:
            ignored = set(skip_cache(directory, names))
            if chatgpt_profile:
                ignored.update(_runtime_names(root, Path(directory), names))
            return ignored
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


def sync_profile(backup_path: Path | None, target: Path) -> None:
    """Вернуть содержимое профиля, даже если Windows держит сам каталог открытым."""
    pending: list[Future] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        _sync_item(backup_path, target, root=True, profile_root=target, pool=pool, pending=pending)
        for task in pending:
            task.result()


def _sync_item(source: Path | None, target: Path, *, root: bool = False,
               profile_root: Path, pool: ThreadPoolExecutor, pending: list[Future]) -> bool:
    """True, если новый каталог остался контейнером для служебных файлов."""
    # None означает отсутствие до сессии. Потерянный снимок должен дать ошибку.
    saved = os.lstat(_fs(source)) if source is not None else None
    if saved and _is_link(saved):
        raise OSError(f"Не удалось восстановить ссылку из снимка: {source}")
    try:
        live = os.lstat(_fs(target))
    except FileNotFoundError:
        live = None

    if live and _is_link(live):
        # Удаляем саму ссылку или junction, никогда не обходим её содержимое.
        is_dir_link = getattr(live, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_DIRECTORY
        unlink = os.rmdir if is_dir_link else os.unlink
        _retry(lambda: unlink(_fs(target)))
        live = None

    saved_dir = saved is not None and stat.S_ISDIR(saved.st_mode)
    live_dir = live is not None and stat.S_ISDIR(live.st_mode)
    if live_dir or saved_dir:
        if live and not live_dir:
            remove(target)
        if saved_dir:
            os.makedirs(_fs(target), exist_ok=True)
        children = {Path(name) for name in os.listdir(_fs(target))}
        original = {Path(name) for name in os.listdir(_fs(source))} if saved_dir else set()
        names = children | original
        excluded = {Path(name) for name in _runtime_names(profile_root, target, (item.name for item in names))}
        retained = bool(children & excluded)
        first_error = None
        for name in names - excluded:
            try:
                if _sync_item(source / name if name in original else None, target / name,
                              profile_root=profile_root, pool=pool, pending=pending):
                    retained = True
            except OSError as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error
        if saved_dir:
            return False
        if retained and saved is None:
            return True
        try:
            os.rmdir(_fs(target))
        except OSError as error:
            # Новый пустой корень может удерживаться процессом как рабочая папка.
            if not (root and saved is None and getattr(error, "winerror", None) == 32
                    and not os.listdir(_fs(target))):
                raise
        live = None

    if saved is None:
        if live:
            remove(target)
        return False
    # У сохранённого файла все родители есть в снимке. Они не будут удаляться,
    # пока независимые файлы сверяются и восстанавливаются рабочими потоками.
    pending.append(pool.submit(_restore_file, source, target, saved, live))
    return False


def _restore_file(source: Path, target: Path, saved: os.stat_result, live: os.stat_result | None) -> None:
    if live and saved.st_size == live.st_size and (saved.st_size == 0 or _same_contents(source, target)):
        return
    os.makedirs(_fs(target.parent), exist_ok=True)
    # Замена через новый файл не меняет содержимое других жёстких ссылок
    # и не оставляет частично записанный файл профиля при обрыве копирования.
    staged = target.with_name(".sc-restore-" + uuid.uuid4().hex)
    try:
        _retry(lambda: shutil.copy2(_fs(source), _fs(staged)))
        if live and not live.st_mode & stat.S_IWRITE:
            os.chmod(_fs(target), stat.S_IWRITE)
        _retry(lambda: os.replace(_fs(staged), _fs(target)))
    finally:
        if os.path.lexists(_fs(staged)):
            _remove_file(_fs(staged))


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _same_contents(source: Path, target: Path) -> bool:
    with open(_fs(source), "rb") as before, open(_fs(target), "rb") as current:
        while True:
            block = before.read(256 * 1024)
            if block != current.read(256 * 1024):
                return False
            if not block:
                return True


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
