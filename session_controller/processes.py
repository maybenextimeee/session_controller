"""Поиск и закрытие программ. Пока программа открыта, её файлы заблокированы."""

import logging
import re
from collections.abc import Iterable

import psutil

from session_controller.i18n import tr
from session_controller.targets import Target

log = logging.getLogger(__name__)

# Служебные программы внутри MSIX, в том числе оставшиеся после закрытия окна.
_DESKTOP_HELPERS = {"codex-code-mode-host.exe", "codex-computer-use-swift.exe",
                    "node_repl.exe", "node.exe"}
_DESKTOP_RESOURCES = re.compile(
    r"\\windowsapps\\openai\.(?:codex|chatgpt-desktop)_[^\\]+__2p2nqsd0c76g0\\app\\resources\\", re.I
)
_RUNTIME_RESOURCES = re.compile(
    r"\\windowsapps\\openai\.codexprimaryruntime\.[^\\]+__3k8sg7r9htsxt\\dependencies\\", re.I
)


def running(targets: Iterable[Target]) -> list[Target]:
    """Какие из этих программ сейчас запущены."""
    targets = list(targets)
    found = _find(targets)
    return [t for t in targets if found.get(t.id)]


def close(targets: Iterable[Target], timeout: float = 5) -> None:
    targets = list(targets)
    found = _find(targets)
    _stop({proc for group in found.values() for proc in group}, timeout)

    # Между обнаружением помощников и выходом главного процесса мог стартовать ещё один.
    desktop = [t for t in targets if t.id == "chatgpt_codex"]
    if desktop:
        _stop(set(_find(desktop).get("chatgpt_codex", ())), timeout)
    ensure_closed(targets)


def _stop(procs: set[psutil.Process], timeout: float) -> None:
    if not procs:
        return
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
    _, remaining = psutil.wait_procs(alive, timeout=timeout)
    if remaining:
        names = ", ".join(sorted({proc.info["name"] for proc in remaining}))
        raise OSError(tr('Не удалось закрыть: {0}. Закрой программу и повтори попытку.').format(names))


def ensure_closed(targets: Iterable[Target]) -> None:
    remaining = running(targets)
    if remaining:
        names = ", ".join(tr(target.name) for target in remaining)
        raise OSError(tr('Не удалось закрыть: {0}. Закрой программу и повтори попытку.').format(names))


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
    include_desktop = any(t.id == "chatgpt_codex" for t in targets)
    runtime = []
    names = {name.lower() for target in targets for name in target.process_names}
    if include_desktop:
        names.update(_DESKTOP_HELPERS | {"pwsh.exe", "python.exe"})
    for proc in psutil.process_iter(["name"]):
        name = (proc.info["name"] or "").lower()
        if name not in names:
            continue
        try:
            if proc.username() != me:
                continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        try:
            exe = (proc.exe() or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            exe = ""
        if include_desktop:
            if name in _DESKTOP_HELPERS and _DESKTOP_RESOURCES.search(exe):
                found.setdefault("chatgpt_codex", []).append(proc)
            elif name in {"node.exe", "pwsh.exe", "python.exe"} and _RUNTIME_RESOURCES.search(exe):
                runtime.append(proc)
        for target in targets:
            if name not in (n.lower() for n in target.process_names):
                continue
            if not target.matches_exe(exe):
                continue
            found.setdefault(target.id, []).append(proc)
    # Общие интерпретаторы из комплекта runtime принадлежат приложению только
    # если их запустило оно. Отдельно запущенные терминалы и серверы сохраняем.
    owners = set(found.get("chatgpt_codex", ()))
    for proc in runtime:
        try:
            if owners.intersection(proc.parents()):
                found["chatgpt_codex"].append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found
