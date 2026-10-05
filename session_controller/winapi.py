"""Функции Windows, которых нет в Qt. На других системах ничего не делают."""

import logging
import sys

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

WM_NCACTIVATE = 0x0086


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
