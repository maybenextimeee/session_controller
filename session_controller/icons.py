"""Значки: самой программы и программ из списка «Что очищать».

Значки карточек хранятся в сборке и доступны без подключения к интернету.
"""

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPen, QPixmap

from session_controller import theme
from session_controller.targets import Target

_ICONS_DIR = Path(__file__).with_name("app_icons")
_cache: dict[str, QIcon] = {}
_app_icon: QIcon | None = None


def target_icon(target: Target) -> QIcon:
    if target.id not in _cache:
        icon = QIcon(str(_ICONS_DIR / f"{target.id}.png"))
        if icon.isNull():
            icon = _letter_tile("#5d6579", target.name[:1].upper())
        _cache[target.id] = icon
    return _cache[target.id]


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
