"""Значения и целые ветки реестра Windows в HKEY_CURRENT_USER: запомнить и вернуть.

Значение хранится как {"type": тип, "data": данные} или None, если его нет.
Ветка — как {"values": {имя: значение}, "keys": {подраздел: ветка}} или None.
На других системах ничего не делает.
"""

import base64
import sys


if sys.platform == "win32":
    import winreg

REG_SZ = 1  # тип «строка»


def read(key: str, name: str) -> dict | None:
    if sys.platform != "win32":
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            data, kind = winreg.QueryValueEx(handle, name)
    except FileNotFoundError:
        return None
    return _pack(kind, data)


def _pack(kind: int, data: object) -> dict:
    if isinstance(data, bytes):
        # Двоичные данные в JSON-журнал не положить — храним их как текст base64.
        return {"type": kind, "data": base64.b64encode(data).decode("ascii"), "base64": True}
    return {"type": kind, "data": data}


def _unpack(value: dict) -> tuple[int, object]:
    data = value["data"]
    if value.get("base64"):
        data = base64.b64decode(data)
    return value["type"], data


def read_string(key: str, name: str) -> str | None:
    value = read(key, name)
    if value and isinstance(value["data"], str):
        return value["data"]
    return None


def subkeys(key: str) -> list[str]:
    """Имена подразделов (пустой список, если раздела нет)."""
    if sys.platform != "win32":
        return []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            count = winreg.QueryInfoKey(handle)[0]
            return [winreg.EnumKey(handle, index) for index in range(count)]
    except OSError:
        return []


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
    kind, data = _unpack(value)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
        winreg.SetValueEx(handle, name, 0, kind, data)


# ---------- Целые ветки ----------

def read_tree(key: str) -> dict | None:
    """Вся ветка: значения и подразделы на любой глубине. None — ветки нет."""
    if sys.platform != "win32":
        return None
    try:
        handle = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key)
    except FileNotFoundError:
        return None
    with handle:
        value_count = winreg.QueryInfoKey(handle)[1]
        values = {}
        for index in range(value_count):
            name, data, kind = winreg.EnumValue(handle, index)
            values[name] = _pack(kind, data)
    return {
        "values": values,
        "keys": {sub: read_tree(rf"{key}\{sub}") for sub in subkeys(key)},
    }


def write_tree(key: str, tree: dict | None) -> None:
    """Сделать ветку ровно такой, как в tree: всё, что появилось потом, удалится.
    tree = None — ветки быть не должно."""
    if sys.platform != "win32":
        return
    delete_tree(key)
    if tree is not None:
        _create_tree(key, tree)


def delete_tree(key: str) -> None:
    """Удалить ветку целиком (несуществующую — не ошибка)."""
    if sys.platform != "win32":
        return
    _check_safe(key)
    for sub in subkeys(key):
        delete_tree(rf"{key}\{sub}")
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
    except FileNotFoundError:
        pass


def _create_tree(key: str, tree: dict) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
        for name, value in tree["values"].items():
            kind, data = _unpack(value)
            winreg.SetValueEx(handle, name, 0, kind, data)
    for sub, subtree in tree["keys"].items():
        _create_tree(rf"{key}\{sub}", subtree)


def _check_safe(key: str) -> None:
    """Защита от ошибки в описании программы: удалять можно только ветку
    конкретной программы вида Software\\<программа>, а не весь Software."""
    parts = [part for part in key.split("\\") if part]
    if len(parts) < 2 or parts[0].lower() != "software":
        raise ValueError(f"Небезопасная ветка реестра для удаления: {key!r}")
