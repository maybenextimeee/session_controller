"""Где лежат файлы самой программы."""

import os
from pathlib import Path


def app_home() -> Path:
    """Папка настроек и данных текущего пользователя."""
    override = os.environ.get("SESSION_CONTROLLER_HOME")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        base = Path(local)
        # Продолжаем пользоваться прежними данными, включая незавершённую сессию.
        existing = base / "SessionControllerCollege"
        if any((existing / file).is_file() for file in ("session.json", "account.dat", "settings.json")):
            return existing
        return base / "SessionController"
    return Path.home() / ".session_controller"
