"""Значения реестра Windows в HKEY_CURRENT_USER: запомнить и вернуть.

Значение хранится как {"type": тип, "data": данные} или None, если его нет.
На других системах ничего не делает.
"""

import base64
import sys


if sys.platform == "win32":
    import winreg


def read(key: str, name: str) -> dict | None:
    if sys.platform != "win32":
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            data, kind = winreg.QueryValueEx(handle, name)
    except FileNotFoundError:
        return None
    if isinstance(data, bytes):
        # Двоичные данные в JSON-журнал не положить — храним их как текст base64.
        return {"type": kind, "data": base64.b64encode(data).decode("ascii"), "base64": True}
    return {"type": kind, "data": data}


def read_string(key: str, name: str) -> str | None:
    value = read(key, name)
    if value and isinstance(value["data"], str):
        return value["data"]
    return None


def write(key: str, name: str, value: dict | None) -> None:
    """Записать значение, а если value is None — удалить его."""
    if sys.platform != "win32":
        return
    if value is None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as handle:
                winreg.DeleteValue(handle, name)
        except FileNotFoundError:
            pass
        return
    data = value["data"]
    if value.get("base64"):
        data = base64.b64decode(data)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
        winreg.SetValueEx(handle, name, 0, value["type"], data)
