"""Функции Windows, которых нет в Qt. На других системах ничего не делают."""

import logging
import sys
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.ShutdownBlockReasonCreate.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    _user32.ShutdownBlockReasonCreate.restype = wintypes.BOOL
    _user32.ShutdownBlockReasonDestroy.argtypes = [wintypes.HWND]
    _user32.ShutdownBlockReasonDestroy.restype = wintypes.BOOL
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.SendMessageW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    ]
    _user32.SendMessageW.restype = wintypes.LPARAM

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.CreateMutexW.restype = wintypes.HANDLE

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    _shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(_GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p),
    ]
    _shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    _ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    _ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    _ole32.CoTaskMemFree.restype = None

    _wininet = ctypes.WinDLL("wininet", use_last_error=True)
    _wininet.InternetSetOptionW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ]
    _wininet.InternetSetOptionW.restype = wintypes.BOOL

WM_NCACTIVATE = 0x0086
INTERNET_OPTION_REFRESH = 37
INTERNET_OPTION_SETTINGS_CHANGED = 39
_FOLDERID_DOWNLOADS = "{374DE290-123F-4565-9164-39C4925E467B}"


def downloads_folder() -> Path:
    """Папка «Загрузки» текущего пользователя.

    Её можно перенести (например, на другой диск), поэтому спрашиваем Windows,
    а не берём «C:\\Users\\<имя>\\Downloads» наугад.
    """
    if sys.platform == "win32":
        guid_value = uuid.UUID(_FOLDERID_DOWNLOADS)
        guid = _GUID(guid_value.time_low, guid_value.time_mid, guid_value.time_hi_version,
                     (ctypes.c_ubyte * 8)(*guid_value.bytes[8:]))
        path = ctypes.c_wchar_p()
        if _shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path)) == 0:
            try:
                return Path(path.value)
            finally:
                _ole32.CoTaskMemFree(ctypes.cast(path, ctypes.c_void_p))
        log.warning("SHGetKnownFolderPath(Downloads) не сработал — беру папку по умолчанию")
    return Path.home() / "Downloads"


def notify_proxy_changed() -> None:
    """Сообщить Windows, что настройки прокси в реестре изменились.

    Иначе браузеры и программы ещё какое-то время ходили бы через старый прокси.
    """
    if sys.platform != "win32":
        return
    for option in (INTERNET_OPTION_SETTINGS_CHANGED, INTERNET_OPTION_REFRESH):
        if not _wininet.InternetSetOptionW(None, option, None, 0):
            log.warning("InternetSetOptionW(%s): ошибка %s", option, ctypes.get_last_error())


def redraw_title_bar(hwnd: int) -> None:
    """Перерисовать заголовок окна после смены темы.

    Windows 10 запоминает новый цвет заголовка, но рисует его только при
    следующей перерисовке рамки (свернуть, развернуть). Просим перерисовать
    сейчас: «окно неактивно» → «окно в прежнем состоянии».
    """
    if sys.platform != "win32":
        return
    active = _user32.GetForegroundWindow() == hwnd
    _user32.SendMessageW(hwnd, WM_NCACTIVATE, not active, 0)
    _user32.SendMessageW(hwnd, WM_NCACTIVATE, active, 0)


def block_shutdown(hwnd: int, reason: str) -> None:
    """Попросить Windows подождать с выключением и показать пользователю причину."""
    if sys.platform != "win32":
        return
    if not _user32.ShutdownBlockReasonCreate(hwnd, reason):
        log.warning("ShutdownBlockReasonCreate: ошибка %s", ctypes.get_last_error())


def unblock_shutdown(hwnd: int) -> None:
    if sys.platform != "win32":
        return
    if not _user32.ShutdownBlockReasonDestroy(hwnd):
        log.warning("ShutdownBlockReasonDestroy: ошибка %s", ctypes.get_last_error())


_mutex = None


def create_app_mutex(name: str) -> None:
    """Создать именованный мьютекс, пока программа работает.

    По нему установщик понимает, что Session Controller запущен, и просит
    закрыть его перед обновлением или удалением.
    """
    global _mutex
    if sys.platform != "win32" or _mutex is not None:
        return
    _mutex = _kernel32.CreateMutexW(None, False, name)
    if not _mutex:
        log.warning("CreateMutexW: ошибка %s", ctypes.get_last_error())
