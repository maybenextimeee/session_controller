"""Значки: самой программы и программ из списка «Что очищать».

Значки браузеров и приложений берём прямо из их exe, как это делает Проводник:
так они всегда настоящие и не нужно хранить чужие логотипы в репозитории.
Если exe не нашёлся — рисуем цветной квадрат с буквами.
"""

import math
import sys
from pathlib import Path

from PySide6.QtCore import QFileInfo, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFileIconProvider

from session_controller import theme
from session_controller.targets import Target

if sys.platform == "win32":
    import winreg

# Для запасного значка: фирменный цвет и буквы.
_MONOGRAMS = {
    "chrome": ("#4285f4", "G"),
    "edge": ("#0c88d8", "E"),
    "yandex": ("#fc3f1d", "Я"),
    "brave": ("#fb542b", "B"),
    "vivaldi": ("#ef3939", "V"),
    "opera": ("#ff1b2d", "O"),
    "opera_gx": ("#fa1e4e", "GX"),
    "firefox": ("#ff7139", "F"),
    "telegram": ("#26a5e4", "T"),
    "discord": ("#5865f2", "D"),
    "vscode": ("#007acc", "VS"),
    "steam": ("#2a475e", "S"),
    "git": ("#f05032", "G"),
}

# Значок «ключ» из шрифта значков Windows (Segoe MDL2 Assets / Segoe Fluent Icons).
_KEY_GLYPH = ""
_WINDOWS_BLUE = "#0078d4"

_cache: dict[str, QIcon] = {}
_app_icon: QIcon | None = None


def target_icon(target: Target, icon_font: str = "") -> QIcon:
    if target.id in _cache:
        return _cache[target.id]

    exe = _find_exe(target)
    icon = QFileIconProvider().icon(QFileInfo(str(exe))) if exe else QIcon()
    if icon.isNull():
        if target.id == "windows_credentials" and icon_font:
            icon = _glyph_tile(_WINDOWS_BLUE, _KEY_GLYPH, icon_font)
        else:
            color, letters = _MONOGRAMS.get(target.id, ("#5d6579", target.name[:1].upper()))
            icon = _letter_tile(color, letters)
    _cache[target.id] = icon
    return icon


def _find_exe(target: Target) -> Path | None:
    for path in target.exe_paths:
        if path.is_file():
            return path
    for process in target.process_names:
        path = _app_path(process)
        if path and (not target.exe_hint or target.exe_hint in str(path).lower()):
            return path
    return None


def _app_path(exe_name: str) -> Path | None:
    """Где установлена программа, по разделу реестра App Paths (его заполняют установщики)."""
    if sys.platform != "win32":
        return None
    key = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, key) as handle:
                value, _kind = winreg.QueryValueEx(handle, "")
        except OSError:
            continue
        path = Path(str(value).strip('"'))
        if path.is_file():
            return path
    return None


def _letter_tile(color: str, letters: str) -> QIcon:
    size = 64
    pixmap, painter = _tile(QColor(color), size)
    font = QFont("Segoe UI")
    font.setBold(True)
    font.setPixelSize(int(size * (0.5 if len(letters) == 1 else 0.38)))
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, letters)
    painter.end()
    return QIcon(pixmap)


def _glyph_tile(color: str, glyph: str, icon_font: str) -> QIcon:
    size = 64
    pixmap, painter = _tile(QColor(color), size)
    font = QFont(icon_font)
    font.setPixelSize(int(size * 0.5))
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    return QIcon(pixmap)


def _tile(color: QColor, size: int) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(QRectF(4, 4, size - 8, size - 8), 14, 14)
    return pixmap, painter


def make_icon() -> QIcon:
    """Значок программы: мятно-лаймовый квадрат с «кольцом сессии».

    Кольцо с разрывом — сессия, которую можно замкнуть и завершить,
    точка в разрыве — момент, когда всё возвращается как было.
    """
    global _app_icon
    if _app_icon is not None:
        return _app_icon

    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0, QColor(theme.MINT))
    gradient.setColorAt(1, QColor(theme.LIME))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(QRectF(8, 8, size - 16, size - 16), 62, 62)

    ink = QColor(theme.ON_ACCENT)
    center, radius = size / 2, 62
    pen = QPen(ink, 28)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    ring = QRectF(center - radius, center - radius, radius * 2, radius * 2)
    # Углы в Qt — в 1/16 градуса, против часовой стрелки от «трёх часов».
    # Разрыв — справа сверху, от 22° до 98°.
    painter.drawArc(ring, 98 * 16, 284 * 16)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ink)
    angle = math.radians(60)
    dot = QPointF(center + radius * math.cos(angle), center - radius * math.sin(angle))
    painter.drawEllipse(dot, 15, 15)
    painter.end()

    _app_icon = QIcon(pixmap)
    return _app_icon
