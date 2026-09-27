"""Где лежат файлы самой программы."""

import os
from pathlib import Path


def app_home() -> Path:
    """%LOCALAPPDATA%\\SessionController — настройки, журнал сессии, снимки, лог."""
    override = os.environ.get("SESSION_CONTROLLER_HOME")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "SessionController"
    return Path.home() / ".session_controller"
