"""Значки: самой программы и программ из списка «Что очищать».

Значки карточек хранятся в сборке и доступны без подключения к интернету.
"""

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap

from session_controller.targets import Target

_ICONS_DIR = Path(__file__).with_name("app_icons")
_cache: dict[str, QIcon] = {}
_app_icon: QIcon | None = None


def target_icon(target: Target) -> QIcon:
    if target.id not in _cache:
        icon = QIcon(str(_ICONS_DIR / f"{target.id}.png"))
        if icon.isNull():
            icon = _letter_tile("#777777", target.name[:1].upper())
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
    """Диск и полоса на квадратной основе."""
    global _app_icon
    if _app_icon is None:
        pixmap, painter = _tile(QColor("#f4f4f4"), 256)
        painter.setBrush(QColor("#171717"))
        painter.drawEllipse(QRectF(44, 80, 96, 96))
        painter.drawRoundedRect(QRectF(162, 58, 42, 140), 4, 4)
        painter.end()
        _app_icon = QIcon(pixmap)
    return _app_icon
