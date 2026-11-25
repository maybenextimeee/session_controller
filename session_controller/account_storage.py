"""Адрес сервера и вход, сохранённый для текущего пользователя Windows."""

import ctypes
import json
import logging
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger(__name__)

ACCOUNT_SERVER = "https://prolonged-railcar-amazingly.ngrok-free.dev"


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.c_void_p)]


def _dpapi(data: bytes, decrypt: bool) -> bytes:
    # DPAPI привязывает данные к учётной записи Windows на этом компьютере.
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    free = ctypes.WinDLL("kernel32").LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    call = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    call.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                     ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    call.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.addressof(buffer))
    result = _Blob()
    if not call(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        free(result.data)


def server_address(home: Path, previous: str = "") -> str:
    fallback = previous or ACCOUNT_SERVER
    try:
        return (home / "server.txt").read_text(encoding="utf-8-sig").strip() or fallback
    except FileNotFoundError:
        return fallback
    except (OSError, UnicodeError):
        log.exception("Не удалось прочитать файл адреса сервера")
        return fallback

class SavedAccount:
    def __init__(self, home: Path):
        self.path = home / "account.dat"

    def load(self, origin: str) -> str:
        try:
            data = json.loads(_dpapi(self.path.read_bytes(), decrypt=True))
            if data["server"] == origin and isinstance(data["token"], str):
                return data["token"]
        except FileNotFoundError:
            pass
        except (AttributeError, OSError, ValueError, KeyError, TypeError):
            log.warning("Не удалось восстановить вход в аккаунт")
        return ""

    def save(self, origin: str, token: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = _dpapi(json.dumps({"server": origin, "token": token}).encode(), decrypt=False)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(encrypted)
        temporary.replace(self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
        self.path.with_suffix(".tmp").unlink(missing_ok=True)
