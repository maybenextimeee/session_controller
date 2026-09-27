"""Диспетчер учётных данных Windows.

Здесь Git, GitHub Desktop, GitHub CLI и многие программы хранят пароли и токены.
Запоминаем, какие записи были до сессии, а в конце удаляем появившиеся.
На других системах ничего не делает.
"""

import logging
import sys

log = logging.getLogger(__name__)

# Служебные записи самой Windows — их не трогаем, даже если они появились за сессию.
SYSTEM_MARKERS = ("virtualapp/didlogical", "SSO_POP_Device")

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    _PCREDENTIAL = ctypes.POINTER(_CREDENTIAL)

    _advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    _advapi.CredEnumerateW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.POINTER(_PCREDENTIAL)),
    ]
    _advapi.CredEnumerateW.restype = wintypes.BOOL
    _advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _advapi.CredDeleteW.restype = wintypes.BOOL
    _advapi.CredFree.argtypes = [ctypes.c_void_p]
    _advapi.CredFree.restype = None

    _ERROR_NOT_FOUND = 1168
    _CRED_ENUMERATE_ALL_CREDENTIALS = 0x1


def list_all() -> list[tuple[str, int]]:
    """Все записи текущего пользователя: [(имя, тип), ...]."""
    if sys.platform != "win32":
        return []

    count = wintypes.DWORD()
    items = ctypes.POINTER(_PCREDENTIAL)()
    if not _advapi.CredEnumerateW(
        None, _CRED_ENUMERATE_ALL_CREDENTIALS, ctypes.byref(count), ctypes.byref(items)
    ):
        error = ctypes.get_last_error()
        if error == _ERROR_NOT_FOUND:
            return []
        raise ctypes.WinError(error)
    try:
        return [(items[i].contents.TargetName, items[i].contents.Type) for i in range(count.value)]
    finally:
        _advapi.CredFree(items)


def delete(name: str, kind: int) -> None:
    if sys.platform != "win32":
        return
    if not _advapi.CredDeleteW(name, kind, 0):
        error = ctypes.get_last_error()
        if error != _ERROR_NOT_FOUND:
            raise ctypes.WinError(error)


def is_system(name: str) -> bool:
    return any(marker in name for marker in SYSTEM_MARKERS)
