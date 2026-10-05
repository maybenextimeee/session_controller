"""Элементы интерфейса, которых нет в Qt в нужном виде: переключатель,
карточки, пульсирующая точка статуса, вкладки-переключатель, фон окна."""

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from session_controller import theme


class Background(QWidget):
    """Фон окна: точечная сетка, тающая книзу, и мягкое мятное свечение."""

    DOT_STEP = 18

    def paintEvent(self, _event) -> None:
        t = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        painter.fillRect(rect, theme.qcolor(t.bg))

        size = max(rect.width(), rect.height())
        for center, radius, color in (
            (QPointF(rect.width() * 0.92, rect.height() * 0.02), size * 0.62, t.glow_1),
            (QPointF(rect.width() * 0.02, rect.height() * 1.0), size * 0.55, t.glow_2),
        ):
            glow = QRadialGradient(center, radius)
            glow.setColorAt(0, theme.qcolor(color))
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            painter.fillRect(rect, glow)

        # Точки видны сверху и постепенно исчезают к середине окна.
        dot = theme.qcolor(t.dots)
        base_alpha = dot.alphaF()
        fade_to = rect.height() * 0.6
        painter.setPen(Qt.PenStyle.NoPen)
        step = self.DOT_STEP
        y = step / 2
        while y < fade_to:
            dot.setAlphaF(base_alpha * (1 - y / fade_to))
            painter.setBrush(dot)
            x = step / 2
            while x < rect.width():
                painter.drawEllipse(QPointF(x, y), 1.0, 1.0)
                x += step
            y += step


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
        self._animation.setDuration(160)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(40, 22)

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
        painter.setOpacity(opacity)

        track = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        radius = track.height() / 2
        painter.setPen(QPen(theme.qcolor(t.border_strong), 1))
        painter.setBrush(theme.qcolor(t.surface_2))
        painter.drawRoundedRect(track, radius, radius)

        # Включённое состояние — фирменный градиент, проявляется по ходу анимации.
        if self._position > 0:
            gradient = QLinearGradient(track.topLeft(), track.bottomRight())
            gradient.setColorAt(0, QColor(theme.MINT))
            gradient.setColorAt(1, QColor(theme.LIME))
            painter.setOpacity(opacity * self._position)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawRoundedRect(track, radius, radius)
            painter.setOpacity(opacity)

        knob = track.height() - 6
        x = track.left() + 3 + (track.width() - knob - 6) * self._position
        off_knob = QColor(theme.qcolor(t.muted) if t.dark else QColor("#ffffff"))
        on_knob = QColor(theme.ON_ACCENT)
        knob_color = on_knob if self._position >= 0.5 else off_knob
        painter.setPen(Qt.PenStyle.NoPen if t.dark or self._position >= 0.5
                       else QPen(theme.qcolor(t.border_strong), 1))
        painter.setBrush(knob_color)
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
            self._fade.setOpacity(1.0 if self.isEnabled() else 0.6)
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
        layout.setContentsMargins(12, 11, 12, 11)
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
        self.description_label.setObjectName("small")
        self.description_label.setWordWrap(True)

        texts = QVBoxLayout()
        texts.setSpacing(3)
        texts.addWidget(title_label)
        texts.addWidget(self.description_label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(14)
        layout.addLayout(texts, 1)
        layout.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)


class PulseDot(QWidget):
    """Точка статуса. Во время сессии вокруг неё расходятся мягкие круги."""

    SIZE = 16

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._color = QColor("#888888")
        self._phase = 0.0
        self._pulse = QVariantAnimation(self)
        self._pulse.setStartValue(0.0)
        self._pulse.setEndValue(1.0)
        self._pulse.setDuration(1800)
        self._pulse.setLoopCount(-1)
        self._pulse.valueChanged.connect(self._on_phase)

    def set_state(self, color: str, pulsing: bool) -> None:
        self._color = theme.qcolor(color)
        if pulsing and self._pulse.state() == QVariantAnimation.State.Stopped:
            self._pulse.start()
        elif not pulsing:
            self._pulse.stop()
            self._phase = 0.0
        self.update()

    def _on_phase(self, value: float) -> None:
        self._phase = value
        self.update()

    # Пока окно спрятано в трей, анимация не нужна — не тратим на неё процессор.
    def hideEvent(self, event) -> None:
        if self._pulse.state() == QVariantAnimation.State.Running:
            self._pulse.pause()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        if self._pulse.state() == QVariantAnimation.State.Paused:
            self._pulse.resume()
        super().showEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        center = QPointF(self.SIZE / 2, self.SIZE / 2)
        if self._pulse.state() != QVariantAnimation.State.Stopped:
            halo = QColor(self._color)
            halo.setAlphaF(0.45 * (1 - self._phase))
            painter.setBrush(halo)
            radius = 3.5 + 4.5 * self._phase
            painter.drawEllipse(center, radius, radius)
        painter.setBrush(self._color)
        painter.drawEllipse(center, 3.5, 3.5)


class StatusPill(QFrame):
    """Плашка статуса: точка и короткая надпись капсом."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pill")
        # Высота ровно в два радиуса скругления (12 px в стиле) — получается «таблетка».
        self.setFixedHeight(24)
        self.dot = PulseDot()
        self.label = QLabel()
        self.label.setObjectName("statusText")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 11, 0)
        layout.setSpacing(5)
        layout.addWidget(self.dot)
        layout.addWidget(self.label)

    def set_status(self, color: str, text: str, pulsing: bool = False) -> None:
        self.dot.set_state(color, pulsing)
        self.label.setText(text.upper())
        self.label.setStyleSheet(f"color: {color};")


class Segmented(QFrame):
    """Выбор одного варианта из нескольких — кнопки в общей «дорожке»."""

    chosen = Signal(str)

    def __init__(self, options: dict[str, str], current: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("segmented")
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        for key, label in options.items():
            button = QPushButton(label)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(key == current)
            button.clicked.connect(lambda _checked, k=key: self.chosen.emit(k))
            self.group.addButton(button)
            self.buttons[key] = button
            layout.addWidget(button, 1)
