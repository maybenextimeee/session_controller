"""Проверка обновлений: нет ли на GitHub версии новее установленной.

Раз в сутки программа спрашивает у GitHub, какой релиз последний. Это обычный
запрос к открытой странице релизов — никаких данных о пользователе в нём нет.
Если версия новее, в окне появляется кнопка «Новая версия» со ссылкой на загрузку.

Модуль ничего не знает про интерфейс — как session.py.
"""

import json
import logging
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)

LATEST_RELEASE_URL = (
    "https://api.github.com/repos/maybenextimeee/session_controller/releases/latest"
)
TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class Release:
    version: str  # без буквы v: "0.7.0"
    url: str      # страница релиза, откуда скачивать


def parse_version(text: str) -> tuple[int, ...] | None:
    """«v0.7.0» или «0.7.0» → (0, 7, 0). Если не похоже на версию — None."""
    parts = text.strip().lstrip("vV").split(".")
    try:
        numbers = tuple(int(part) for part in parts)
    except ValueError:
        return None
    return numbers if numbers else None


def is_newer(latest: str, current: str) -> bool:
    """Новее ли latest, чем current. 0.7 и 0.7.0 — одна и та же версия."""
    new, old = parse_version(latest), parse_version(current)
    if new is None or old is None:
        return False
    width = max(len(new), len(old))
    return new + (0,) * (width - len(new)) > old + (0,) * (width - len(old))


def parse_release(data: object) -> Release | None:
    """Релиз из ответа GitHub. Черновики и предварительные версии не предлагаем."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag, url = data.get("tag_name"), data.get("html_url")
    if not isinstance(tag, str) or not isinstance(url, str) or parse_version(tag) is None:
        return None
    return Release(version=tag.strip().lstrip("vV"), url=url)


def fetch_latest() -> Release | None:
    """Последний релиз на GitHub. Сетевые ошибки пробрасывает — пусть решает вызывающий."""
    request = urllib.request.Request(
        LATEST_RELEASE_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "SessionController"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return parse_release(json.load(response))


def newer_release(current: str) -> Release | None:
    """Релиз новее текущей версии или None (нет новее или не удалось проверить)."""
    try:
        release = fetch_latest()
    except Exception as error:  # нет интернета, GitHub недоступен, лимит запросов…
        log.info("Не удалось проверить обновления: %s", error)
        return None
    if release is not None and is_newer(release.version, current):
        log.info("Доступна новая версия %s", release.version)
        return release
    log.info("Обновлений нет (последняя версия на GitHub: %s)",
             release.version if release else "не найдена")
    return None
