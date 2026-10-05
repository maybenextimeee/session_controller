"""Элементы интерфейса, которых нет в Qt в нужном виде: переключатель,
карточки, фон со свечением и сеткой, как на сайте."""

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from session_controller import theme


class Background(QWidget):
    """Фон окна: два мягких цветных пятна и тонкая сетка, тающая книзу."""

    GRID_STEP = 36

    def paintEvent(self, _event) -> None:
        t = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        painter.fillRect(rect, theme.qcolor(t.bg))

        for center, color in (
            (QPointF(rect.width() * 0.05, -rect.height() * 0.05), t.glow_1),
            (QPointF(rect.width() * 1.0, rect.height() * 0.15), t.glow_2),
        ):
            glow = QRadialGradient(center, max(rect.width(), rect.height()) * 0.6)
            glow.setColorAt(0, theme.qcolor(color))
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            painter.fillRect(rect, glow)

        fade = QLinearGradient(0, 0, 0, rect.height() * 0.55)
        fade.setColorAt(0, theme.qcolor(t.grid))
        fade.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setPen(QPen(fade, 1))
        step = self.GRID_STEP
        for x in range(step, int(rect.width()), step):
            painter.drawLine(QPointF(x + 0.5, 0), QPointF(x + 0.5, rect.height()))
        for y in range(step, int(rect.height() * 0.55), step):
            painter.drawLine(QPointF(0, y + 0.5), QPointF(rect.width(), y + 0.5))


class Switch(QAbstractButton):
    """Переключатель вкл/выкл вместо галочки."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._position = 0.0
        self._instant = False
        self._animation = QPropertyAnimation(self, b"position", self)
        self._animation.setDuration(140)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(38, 22)

    def setChecked(self, checked: bool) -> None:  # noqa: N802 (имя из Qt)
        """Поставить положение сразу, без анимации (анимация — только по клику)."""
        self._instant = True
        try:
            super().setChecked(checked)
        finally:
            self._instant = False
        self._position = 1.0 if self.isChecked() else 0.0
        self.update()

    def _animate(self, checked: bool) -> None:
        if self._instant:
            return
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def _get_position(self) -> float:
        return self._position

    def _set_position(self, value: float) -> None:
        self._position = value
        self.update()

    position = Property(float, _get_position, _set_position)

    def paintEvent(self, _event) -> None:
        t = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        opacity = 1.0 if self.isEnabled() else 0.45

        track = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        radius = track.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setOpacity(opacity)
        painter.setBrush(theme.qcolor(t.border_strong))
        painter.drawRoundedRect(track, radius, radius)

        # Включённое состояние — градиент сайта, проявляется по ходу анимации.
        if self._position > 0:
            gradient = QLinearGradient(track.topLeft(), track.topRight())
            gradient.setColorAt(0, QColor(theme.GRADIENT_FROM))
            gradient.setColorAt(1, QColor(theme.GRADIENT_TO))
            painter.setOpacity(opacity * self._position)
            painter.setBrush(gradient)
            painter.drawRoundedRect(track, radius, radius)
            painter.setOpacity(opacity)

        knob = track.height() - 6
        x = track.left() + 3 + (track.width() - knob - 6) * self._position
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(x, track.top() + 3, knob, knob))


class _ClickableCard(QFrame):
    """Карточка, которая переключает свой Switch по клику в любом месте."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.switch = Switch()
        self.switch.toggled.connect(self._restyle)
        self._fade = QGraphicsOpacityEffect(self)
        self._fade.setOpacity(1.0)
        self.setGraphicsEffect(self._fade)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.switch.toggle()
        super().mouseReleaseEvent(event)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == event.Type.EnabledChange:
            self._fade.setOpacity(1.0 if self.isEnabled() else 0.7)
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.isEnabled()
                           else Qt.CursorShape.ArrowCursor)

    def _restyle(self) -> None:
        self.setProperty("checked", self.switch.isChecked())
        self.style().unpolish(self)
        self.style().polish(self)


class TargetCard(_ClickableCard):
    """Программа из списка «Что очищать»: значок, название, переключатель."""

    ICON_SIZE = 22

    def __init__(self, icon: QIcon, name: str, hint: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setToolTip(hint)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(self.ICON_SIZE, self.ICON_SIZE)
        self.icon_label.setPixmap(icon.pixmap(self.ICON_SIZE, self.ICON_SIZE))

        title = QLabel(name)
        title.setObjectName("cardTitle")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        layout.addWidget(self.icon_label)
        layout.addWidget(title, 1)
        layout.addWidget(self.switch)


class SettingRow(_ClickableCard):
    """Настройка: заголовок, пояснение мелким шрифтом и переключатель."""

    def __init__(self, title: str, description: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        title_label.setWordWrap(True)
        self.description_label = QLabel(description)
        self.description_label.setObjectName("muted")
        self.description_label.setWordWrap(True)

        texts = QVBoxLayout()
        texts.setSpacing(3)
        texts.addWidget(title_label)
        texts.addWidget(self.description_label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)
        layout.addLayout(texts, 1)
        layout.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)


class Dot(QWidget):
    """Цветная точка статуса с мягким ореолом."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._color = QColor("#888888")

    def set_color(self, color: str) -> None:
        self._color = theme.qcolor(color)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        halo = QColor(self._color)
        halo.setAlphaF(0.22)
        painter.setBrush(halo)
        painter.drawEllipse(QRectF(0, 0, 14, 14))
        painter.setBrush(self._color)
        painter.drawEllipse(QRectF(3.5, 3.5, 7, 7))


class StatusPill(QFrame):
    """Плашка статуса, как «● Открыт к стажировкам» на сайте."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pill")
        # Высота ровно в два радиуса скругления (13 px в стиле) — получается «таблетка».
        self.setFixedHeight(26)
        self.dot = Dot()
        self.label = QLabel()
        self.label.setObjectName("statusText")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 12, 0)
        layout.setSpacing(7)
        layout.addWidget(self.dot)
        layout.addWidget(self.label)

    def set_status(self, color: str, text: str) -> None:
        self.dot.set_color(color)
        self.label.setText(text)
