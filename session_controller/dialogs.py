"""Окна-вопросы и окна-сообщения в оформлении программы.

Стандартные окна Windows (QMessageBox) выбиваются из дизайна и подписывают
кнопки по-английски, поэтому у нас своё окно: значок в цветной плашке,
заголовок, пояснение, при необходимости — список программ, и кнопки.
"""

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from session_controller import theme
from session_controller.icons import make_icon
from session_controller.widgets import Background

APP_NAME = "Session Controller"

# Значки из шрифта Windows (Segoe MDL2 Assets / Segoe Fluent Icons) и запасные символы.
SIGN_OUT = ("", "↪")
WARNING = ("", "!")
ERROR = ("", "!")
INFO = ("", "i")
RESTORED = ("", "↺")
POWER = ("", "⏻")

# Цвет значка.
ACCENT = "accent"
CAUTION = "caution"
DANGER = "danger"

# Вид кнопки.
PRIMARY = "primary"
SECONDARY = "secondary"


@dataclass(frozen=True)
class Button:
    key: str
    text: str
    kind: str = SECONDARY


def _tone_color(tone: str) -> str:
    t = theme.current()
    return {ACCENT: t.accent, CAUTION: t.busy, DANGER: t.danger}[tone]


class IconBadge(QWidget):
    """Значок в скруглённой плашке цвета сообщения."""

    SIZE = 46

    def __init__(self, glyph: tuple[str, str], tone: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        font_name = theme.fonts().icons
        self._text = glyph[0] if font_name else glyph[1]
        self._font = QFont(font_name or theme.fonts().display)
        self._font.setPixelSize(21 if font_name else 22)
        self._tone = tone

    def paintEvent(self, _event) -> None:
        color = theme.qcolor(_tone_color(self._tone))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = QColor(color)
        fill.setAlphaF(0.13)
        edge = QColor(color)
        edge.setAlphaF(0.28)
        painter.setPen(QPen(edge, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.SIZE - 1, self.SIZE - 1), 13, 13)
        painter.setFont(self._font)
        painter.setPen(color)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)


class Dialog(QDialog):
    """Окно с вопросом или сообщением. После exec() выбор лежит в self.choice
    (ключ нажатой кнопки или None, если окно закрыли крестиком или Esc)."""

    def __init__(
        self,
        parent: QWidget | None,
        heading: str,
        text: str,
        buttons: list[Button],
        glyph: tuple[str, str] = INFO,
        tone: str = ACCENT,
        items: list[tuple[QIcon, str]] = (),
        items_title: str = "",
    ) -> None:
        super().__init__(parent)
        self.choice: str | None = None
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(make_icon())
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        # Ширина не меньше 460, но окно станет шире, если кнопки не помещаются.
        self.setMinimumWidth(460)

        heading_label = QLabel(heading)
        heading_label.setObjectName("dialogTitle")
        heading_label.setWordWrap(True)
        text_label = QLabel(text)
        text_label.setObjectName("muted")
        text_label.setWordWrap(True)
        texts = QVBoxLayout()
        texts.setSpacing(5)
        texts.addWidget(heading_label)
        texts.addWidget(text_label)

        top = QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(IconBadge(glyph, tone), 0, Qt.AlignmentFlag.AlignTop)
        top.addLayout(texts, 1)

        root = Background()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 22, 22, 20)
        layout.setSpacing(0)
        layout.addLayout(top)
        if items:
            layout.addSpacing(16)
            layout.addWidget(_items_panel(items, items_title))
        layout.addSpacing(22)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        for button in buttons:
            widget = QPushButton(button.text)
            widget.setObjectName("dialogPrimary" if button.kind == PRIMARY else "dialogSecondary")
            widget.setCursor(Qt.CursorShape.PointingHandCursor)
            widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            widget.clicked.connect(lambda _checked, key=button.key: self._choose(key))
            if button.kind == PRIMARY:
                widget.setDefault(True)
                widget.setFocus()
            row.addWidget(widget)
        layout.addLayout(row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)

    def _choose(self, key: str) -> None:
        self.choice = key
        self.accept()


def _items_panel(items: list[tuple[QIcon, str]], title: str) -> QFrame:
    """Список программ со значками в две колонки."""
    panel = QFrame()
    panel.setObjectName("itemsPanel")
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(14, 11, 14, 12)
    layout.setSpacing(8)
    if title:
        label = QLabel(title.upper())
        label.setObjectName("caps")
        layout.addWidget(label)
    grid = QGridLayout()
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(6)
    for index, (icon, name) in enumerate(items):
        icon_label = QLabel()
        icon_label.setFixedSize(18, 18)
        icon_label.setPixmap(icon.pixmap(18, 18))
        name_label = QLabel(name)
        cell = QHBoxLayout()
        cell.setSpacing(8)
        cell.addWidget(icon_label)
        cell.addWidget(name_label, 1)
        grid.addLayout(cell, index // 2, index % 2)
    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)
    layout.addLayout(grid)
    return panel


def confirm(
    parent: QWidget | None,
    heading: str,
    text: str,
    confirm_text: str,
    glyph: tuple[str, str] = INFO,
    tone: str = ACCENT,
    items: list[tuple[QIcon, str]] = (),
    items_title: str = "",
) -> bool:
    """Спросить «да или нет». True — нажали кнопку подтверждения."""
    dialog = Dialog(
        parent, heading, text,
        [Button("cancel", "Отмена"), Button("ok", confirm_text, PRIMARY)],
        glyph, tone, items, items_title,
    )
    dialog.exec()
    return dialog.choice == "ok"


def inform(
    parent: QWidget | None,
    heading: str,
    text: str,
    glyph: tuple[str, str] = INFO,
    tone: str = ACCENT,
) -> None:
    """Показать сообщение с одной кнопкой «Понятно»."""
    Dialog(parent, heading, text, [Button("ok", "Понятно", PRIMARY)], glyph, tone).exec()
