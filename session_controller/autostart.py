"""Автозапуск вместе с Windows: значение в разделе Run реестра текущего пользователя.

Работает только в собранной версии (exe): запускать исходники через реестр
неудобно — там нет виртуальной среды и рабочей папки.
"""

import sys

from session_controller import registry

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# То же имя использует установщик (packaging/installer.iss).
VALUE_NAME = "SessionController"


def is_supported() -> bool:
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def command() -> str:
    # --minimized: при входе в Windows сразу прятаться в трей, без окна.
    return f'"{sys.executable}" --minimized'


def is_enabled() -> bool:
    return registry.read_string(RUN_KEY, VALUE_NAME) is not None


def set_enabled(enabled: bool) -> None:
    value = {"type": registry.REG_SZ, "data": command()} if enabled else None
    registry.write(RUN_KEY, VALUE_NAME, value)


def refresh_path() -> None:
    """Если программу перенесли в другую папку, поправить путь в автозапуске."""
    current = registry.read_string(RUN_KEY, VALUE_NAME)
    if current is not None and current != command():
        set_enabled(True)
