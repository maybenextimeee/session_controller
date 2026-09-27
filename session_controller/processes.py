"""Поиск и закрытие программ. Пока программа открыта, её файлы заблокированы."""

import logging
from collections.abc import Iterable

import psutil

from session_controller.targets import Target

log = logging.getLogger(__name__)


def running(targets: Iterable[Target]) -> list[Target]:
    """Какие из этих программ сейчас запущены."""
    targets = list(targets)
    found = _find(targets)
    return [t for t in targets if found.get(t.id)]


def close(targets: Iterable[Target], timeout: float = 5) -> None:
    procs = {p.pid: p for group in _find(targets).values() for p in group}
    if not procs:
        return

    procs = list(procs.values())
    log.info("Закрываю процессы: %s", sorted({p.info["name"] for p in procs}))
    for proc in procs:
        try:
            proc.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(procs, timeout=timeout)

    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(alive, timeout=timeout)


def launched_from(targets: Iterable[Target]) -> Target | None:
    """Не запущен ли Session Controller изнутри одной из этих программ.

    Например, из терминала VS Code: если закрыть VS Code, закроется и
    Session Controller — прямо посреди работы.
    """
    targets = list(targets)
    try:
        parents = {p.pid for p in psutil.Process().parents()}
    except psutil.Error:
        return None
    for target_id, procs in _find(targets).items():
        if any(p.pid in parents for p in procs):
            return next(t for t in targets if t.id == target_id)
    return None


def _find(targets: Iterable[Target]) -> dict[str, list[psutil.Process]]:
    """Процессы этих программ, запущенные текущим пользователем Windows."""
    targets = [t for t in targets if t.process_names]
    if not targets:
        return {}

    me = psutil.Process().username()
    found: dict[str, list[psutil.Process]] = {}
    for proc in psutil.process_iter(["name", "exe", "username"]):
        if proc.info["username"] != me:
            continue
        name = (proc.info["name"] or "").lower()
        exe = (proc.info["exe"] or "").lower()
        for target in targets:
            if name not in (n.lower() for n in target.process_names):
                continue
            if target.exe_hint and target.exe_hint.lower() not in exe:
                continue
            found.setdefault(target.id, []).append(proc)
    return found
