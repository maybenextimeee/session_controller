"""Элементы интерфейса, которых нет в Qt в нужном виде: переключатель,
карточки, главная кнопка сессии, нажимаемый значок, плавная прокрутка,
вкладки-переключатель, слой поверх окна, фон окна."""

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QIcon,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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


class ElidedLabel(QLabel):
    """Надпись в одну строку: если не помещается, заканчивается на «…»."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._full_text = text
        # Надпись может сжиматься уже своего текста — тогда и нужно многоточие.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        elided = self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, self.width()
        )
        if elided != self.text():
            self.setText(elided)


class TargetCard(_ClickableCard):
    """Программа из списка «Что очищать»: значок, название, переключатель.

    Если программы нет на компьютере (installed=False), вместо переключателя —
    пометка «нет на ПК», и нажать на карточку нельзя.
    """

    ICON_SIZE = 22
    NOT_INSTALLED_HINT = (
        "Этой программы нет на компьютере.\n"
        "Если её установят и запустят во время сессии,\n"
        "при завершении её данные тоже удалятся."
    )

    def __init__(self, icon: QIcon, name: str, hint: str, installed: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.installed = installed
        self.setToolTip(hint if installed else self.NOT_INSTALLED_HINT)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(self.ICON_SIZE, self.ICON_SIZE)
        self.icon_label.setPixmap(icon.pixmap(self.ICON_SIZE, self.ICON_SIZE))

        title = ElidedLabel(name)
        title.setObjectName("cardTitle")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 11, 12, 11)
        layout.setSpacing(10)
        layout.addWidget(self.icon_label)
        layout.addWidget(title, 1)
        if installed:
            layout.addWidget(self.switch)
        else:
            self.switch.setParent(self)
            self.switch.hide()
            tag = QLabel("нет на ПК")
            tag.setObjectName("tag")
            layout.addWidget(tag)
            self.setEnabled(False)


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


class SessionButton(QAbstractButton):
    """Главная кнопка внизу окна: начать или завершить сессию.

    Всё о сессии написано прямо на ней: вторая строка — сколько идёт сессия,
    пульсирующая точка — сессия идёт или программа занята.
    """

    START = "start"
    STOP = "stop"
    BUSY = "busy"
    HEIGHT = 58

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._mode = self.START
        self._subtitle = ""

        self._phase = 0.0
        self._pulse = QVariantAnimation(self)
        self._pulse.setStartValue(0.0)
        self._pulse.setEndValue(1.0)
        self._pulse.setDuration(1800)
        self._pulse.setLoopCount(-1)
        self._pulse.valueChanged.connect(self._on_phase)

        # Нажатие: кнопка чуть «вдавливается» и мягко возвращается.
        self._press = 0.0
        self._press_animation = QVariantAnimation(self)
        self._press_animation.valueChanged.connect(self._on_press)
        self.pressed.connect(lambda: self._animate_press(1.0, 90))
        self.released.connect(lambda: self._animate_press(0.0, 260))

    def sizeHint(self) -> QSize:
        return QSize(240, self.HEIGHT)

    def set_state(self, mode: str, title: str, subtitle: str = "") -> None:
        self._mode = mode
        self._subtitle = subtitle
        self.setText(title)
        if mode in (self.STOP, self.BUSY):
            if self._pulse.state() == QVariantAnimation.State.Stopped:
                self._pulse.start()
        else:
            self._pulse.stop()
            self._phase = 0.0
        self.update()

    def _on_phase(self, value: float) -> None:
        self._phase = value
        self.update()

    def _on_press(self, value: float) -> None:
        self._press = value
        self.update()

    def _animate_press(self, end: float, duration: int) -> None:
        self._press_animation.stop()
        self._press_animation.setStartValue(self._press)
        self._press_animation.setEndValue(end)
        self._press_animation.setDuration(duration)
        self._press_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._press_animation.start()

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
        t = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        scale = 1 - 0.025 * self._press
        center = QPointF(self.width() / 2, self.height() / 2)
        painter.translate(center)
        painter.scale(scale, scale)
        painter.translate(-center)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hovered = self.underMouse() and self.isEnabled()
        if self._mode == self.START and self.isEnabled():
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0, QColor("#5af0b8" if hovered else theme.MINT))
            gradient.setColorAt(1, QColor("#d2f77a" if hovered else theme.LIME))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            title_color = QColor(theme.ON_ACCENT)
        elif self._mode == self.STOP:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.qcolor(t.inverse_hover if hovered else t.inverse_bg))
            title_color = theme.qcolor(t.inverse_text)
        else:
            painter.setPen(QPen(theme.qcolor(t.border_strong), 1))
            painter.setBrush(theme.qcolor(t.surface_2))
            title_color = theme.qcolor(t.muted if self._mode == self.BUSY else t.dim)
        painter.drawRoundedRect(rect, 14, 14)

        title_font = QFont(theme.fonts().display)
        title_font.setPixelSize(17)
        title_font.setWeight(QFont.Weight.DemiBold)
        sub_font = QFont(theme.fonts().body)
        sub_font.setPixelSize(12)
        title_metrics = QFontMetricsF(title_font)
        sub_metrics = QFontMetricsF(sub_font)

        dot = self._mode in (self.STOP, self.BUSY)
        dot_space = 18 if dot else 0
        title_width = title_metrics.horizontalAdvance(self.text())
        block_height = title_metrics.height()
        if self._subtitle:
            block_height += 1 + sub_metrics.height()
        top = (self.height() - block_height) / 2
        left = (self.width() - title_width - dot_space) / 2 + dot_space

        if dot:
            if self._mode == self.BUSY:
                dot_color = theme.qcolor(t.busy)
            else:
                # На светлой кнопке мятная точка теряется — берём тёмно-зелёную.
                dot_color = QColor("#0f9d68") if t.dark else QColor(theme.MINT)
            dot_center = QPointF(left - 12, top + title_metrics.height() / 2)
            halo = QColor(dot_color)
            halo.setAlphaF(0.45 * (1 - self._phase))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            radius = 3.5 + 4.5 * self._phase
            painter.drawEllipse(dot_center, radius, radius)
            painter.setBrush(dot_color)
            painter.drawEllipse(dot_center, 3.5, 3.5)

        painter.setFont(title_font)
        painter.setPen(title_color)
        painter.drawText(QPointF(left, top + title_metrics.ascent()), self.text())

        if self._subtitle:
            sub_color = QColor(title_color)
            sub_color.setAlphaF(0.65)
            painter.setFont(sub_font)
            painter.setPen(sub_color)
            sub_width = sub_metrics.horizontalAdvance(self._subtitle)
            sub_top = top + title_metrics.height() + 1
            painter.drawText(QPointF((self.width() - sub_width) / 2, sub_top + sub_metrics.ascent()),
                             self._subtitle)


class PressableIcon(QWidget):
    """Значок программы в шапке: его приятно нажимать — он сжимается
    и пружинит обратно. Больше ничего не делает."""

    def __init__(self, icon: QIcon, size: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon = icon
        self._scale = 1.0
        self._animation = QPropertyAnimation(self, b"scale", self)

    def _get_scale(self) -> float:
        return self._scale

    def _set_scale(self, value: float) -> None:
        self._scale = value
        self.update()

    scale = Property(float, _get_scale, _set_scale)

    def _animate(self, end: float, duration: int, curve: QEasingCurve) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._scale)
        self._animation.setEndValue(end)
        self._animation.setDuration(duration)
        self._animation.setEasingCurve(curve)
        self._animation.start()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._animate(0.82, 110, QEasingCurve(QEasingCurve.Type.OutQuad))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            spring = QEasingCurve(QEasingCurve.Type.OutBack)
            spring.setOvershoot(3.0)
            self._animate(1.0, 480, spring)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        side = self.width()
        painter.translate(side / 2, side / 2)
        painter.scale(self._scale, self._scale)
        pixmap = self._icon.pixmap(side, side)
        painter.drawPixmap(QRectF(-side / 2, -side / 2, side, side), pixmap,
                           QRectF(pixmap.rect()))


class SmoothScrollArea(QScrollArea):
    """Прокрутка, которая колёсиком мыши едет плавно, а не прыгает по строкам."""

    STEP = 120  # на сколько пикселей сдвигает один щелчок колёсика

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._target = 0
        self._animation = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._animation.setDuration(340)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def sizeHint(self) -> QSize:
        # Обычный QScrollArea просит не больше ~400 px в высоту — нам нужен
        # полный размер содержимого, а прокрутка — только если окно меньше.
        widget = self.widget()
        return widget.sizeHint() if widget else super().sizeHint()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        # Тачпады сами присылают мелкие плавные сдвиги — их не трогаем.
        if not event.pixelDelta().isNull() or delta == 0:
            super().wheelEvent(event)
            return
        bar = self.verticalScrollBar()
        running = self._animation.state() == QPropertyAnimation.State.Running
        start = self._target if running else bar.value()
        target = int(max(bar.minimum(), min(bar.maximum(), start - delta / 120 * self.STEP)))
        if target == bar.value():
            event.ignore()
            return
        self._target = target
        self._animation.stop()
        self._animation.setStartValue(bar.value())
        self._animation.setEndValue(target)
        self._animation.start()
        event.accept()


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


class Overlay(QWidget):
    """Слой поверх окна: затемнение и карточка с содержимым.

    Открывается плавно: затемнение проявляется, карточка всплывает снизу
    и чуть увеличивается. Закрывается по клику мимо карточки, по Esc или
    кнопкой закрытия в самой карточке — так же плавно, в обратную сторону.
    """

    closed = Signal()
    # Карточка не больше этой ширины и 80 % высоты окна — окно под ней видно.
    PANEL_WIDTH = 440
    OPEN_MS = 300
    CLOSE_MS = 190

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.panel = QFrame(self)
        self.panel.setObjectName("sheet")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._progress = 0.0
        self._closing = False
        self._snapshot: QPixmap | None = None
        self._animation = QPropertyAnimation(self, b"progress", self)
        self._animation.finished.connect(self._on_animation_finished)
        parent.installEventFilter(self)
        self.hide()

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        self._progress = value
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def open(self) -> None:
        if self.isVisible() and not self._closing:
            return
        self.setGeometry(self.parentWidget().rect())
        self.panel.setGeometry(self._panel_rect())
        self._animate(opening=True)
        self.raise_()
        self.show()
        self.setFocus()

    def close_overlay(self) -> None:
        if self.isVisible() and not self._closing:
            self._animate(opening=False)

    def _animate(self, opening: bool) -> None:
        # Пока идёт анимация, рисуем снимок карточки, а саму карточку прячем:
        # снимок можно плавно проявлять и сдвигать, не перерисовывая каждую кнопку.
        self._snapshot = self.panel.grab()
        self.panel.hide()
        self._closing = not opening
        self._animation.stop()
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(1.0 if opening else 0.0)
        self._animation.setDuration(self.OPEN_MS if opening else self.CLOSE_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic if opening
                                       else QEasingCurve.Type.InCubic)
        self._animation.start()

    def _on_animation_finished(self) -> None:
        self._snapshot = None
        if self._closing:
            self._closing = False
            self.hide()
            self.closed.emit()
        else:
            self.panel.show()
        self.update()

    def _panel_rect(self) -> QRect:
        width = max(min(self.PANEL_WIDTH, self.width() - 40), 280)
        height = max(min(int(self.height() * 0.8), self.height() - 40), 300)
        return QRect((self.width() - width) // 2, (self.height() - height) // 2, width, height)

    def eventFilter(self, watched, event) -> bool:
        # Слой всегда растянут на всё окно, даже если окно изменили в размере.
        if watched is self.parentWidget() and event.type() == event.Type.Resize:
            self.setGeometry(watched.rect())
        return False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.panel.setGeometry(self._panel_rect())

    def mousePressEvent(self, event) -> None:
        if not self._panel_rect().contains(event.position().toPoint()):
            self.close_overlay()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close_overlay()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        scrim = theme.qcolor(theme.current().scrim)
        scrim.setAlphaF(scrim.alphaF() * self._progress)
        painter.fillRect(self.rect(), scrim)

        if self._snapshot is None:
            return
        # Карточка всплывает на 24 px снизу и растёт от 94 % до полного размера.
        p = self._progress
        target = QRectF(self._panel_rect())
        scale = 0.94 + 0.06 * p
        center = target.center() + QPointF(0, 24 * (1 - p))
        size = target.size() * scale
        rect = QRectF(center.x() - size.width() / 2, center.y() - size.height() / 2,
                      size.width(), size.height())
        painter.setOpacity(p)
        painter.drawPixmap(rect, self._snapshot, QRectF(self._snapshot.rect()))


class CenteredColumn(QWidget):
    """Держит содержимое колонкой по центру: не шире max_width и не выше, чем
    нужно содержимому. Лишнее место делится поровну по краям — на большом окне
    интерфейс не растягивается на весь экран."""

    def __init__(self, child: QWidget, max_width: int, margins: tuple[int, int, int, int],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.child = child
        self.max_width = max_width
        self.margins = margins  # слева, сверху, справа, снизу
        child.setParent(self)

    def sizeHint(self) -> QSize:
        left, top, right, bottom = self.margins
        return QSize(self.max_width + left + right, self.child.sizeHint().height() + top + bottom)

    def minimumSizeHint(self) -> QSize:
        left, top, right, bottom = self.margins
        minimum = self.child.minimumSizeHint()
        return QSize(minimum.width() + left + right, minimum.height() + top + bottom)

    def event(self, event) -> bool:
        # Содержимое поменяло желаемый размер (например, открыли настройки).
        if event.type() == event.Type.LayoutRequest:
            self.updateGeometry()
            self._place()
        return super().event(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place()

    def _place(self) -> None:
        left, top, right, bottom = self.margins
        free_width = self.width() - left - right
        free_height = self.height() - top - bottom
        width = min(free_width, self.max_width)
        height = min(free_height, self.child.sizeHint().height())
        self.child.setGeometry(left + (free_width - width) // 2, top + (free_height - height) // 2,
                               width, height)
