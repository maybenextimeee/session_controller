"""Проверка релиза, отмеченного Latest в репозитории GitHub."""

import http.client
import json
import logging
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)

LATEST_RELEASE_URL = "https://api.github.com/repos/maybenextimeee/session_controller/releases/latest"
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
    """Релиз Latest или None, если GitHub недоступен либо вернул некорректные данные."""
    request = urllib.request.Request(
        LATEST_RELEASE_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "SessionController"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return parse_release(json.load(response))
    except (OSError, ValueError, http.client.HTTPException) as error:
        log.info("Не удалось проверить обновления: %s", error)
        return None
