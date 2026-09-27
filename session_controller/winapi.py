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
