"""Какие браузеры знает Session Controller, где они хранят данные и как их закрыть."""

import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import psutil

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Browser:
    id: str
    name: str
    # Папка со всеми профилями браузера: cookies, сохранённые пароли, вкладки и т.д.
    data_dir: Path
    process_names: tuple[str, ...]
    # Если имя процесса слишком общее (у Яндекса это browser.exe),
    # дополнительно проверяем, что этот кусок есть в пути к exe.
    exe_hint: str = ""


def known_browsers() -> list[Browser]:
    """Все браузеры, которые мы умеем защищать (установлены они или нет)."""
    browsers: list[Browser] = []

    local = os.environ.get("LOCALAPPDATA")
    if local:
        local_dir = Path(local)
        browsers += [
            Browser("chrome", "Google Chrome",
                    local_dir / "Google" / "Chrome" / "User Data", ("chrome.exe",)),
            Browser("edge", "Microsoft Edge",
                    local_dir / "Microsoft" / "Edge" / "User Data", ("msedge.exe",)),
            Browser("yandex", "Яндекс Браузер",
                    local_dir / "Yandex" / "YandexBrowser" / "User Data", ("browser.exe",),
                    exe_hint="yandex"),
            Browser("brave", "Brave",
                    local_dir / "BraveSoftware" / "Brave-Browser" / "User Data", ("brave.exe",)),
            Browser("vivaldi", "Vivaldi",
                    local_dir / "Vivaldi" / "User Data", ("vivaldi.exe",)),
        ]

    roaming = os.environ.get("APPDATA")
    if roaming:
        roaming_dir = Path(roaming)
        browsers += [
            Browser("opera", "Opera",
                    roaming_dir / "Opera Software" / "Opera Stable", ("opera.exe",)),
            Browser("opera_gx", "Opera GX",
                    roaming_dir / "Opera Software" / "Opera GX Stable", ("opera.exe",)),
            Browser("firefox", "Mozilla Firefox",
                    roaming_dir / "Mozilla" / "Firefox", ("firefox.exe",)),
        ]

    return browsers


def is_running(browser: Browser) -> bool:
    return bool(_processes([browser]))


def close(browsers: Iterable[Browser], timeout: float = 5) -> None:
    """Закрыть браузеры. Пока браузер открыт, его файлы заблокированы."""
    procs = _processes(browsers)
    if not procs:
        return

    log.info("Закрываю процессы браузеров: %s", sorted({p.info["name"] for p in procs}))
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


def _processes(browsers: Iterable[Browser]) -> list[psutil.Process]:
    """Процессы этих браузеров, запущенные текущим пользователем Windows."""
    browsers = list(browsers)
    me = psutil.Process().username()
    found: dict[int, psutil.Process] = {}

    for proc in psutil.process_iter(["name", "exe", "username"]):
        if proc.info["username"] != me:
            continue
        name = (proc.info["name"] or "").lower()
        exe = (proc.info["exe"] or "").lower()
        for browser in browsers:
            if name not in browser.process_names:
                continue
            if browser.exe_hint and browser.exe_hint not in exe:
                continue
            found[proc.pid] = proc

    return list(found.values())
