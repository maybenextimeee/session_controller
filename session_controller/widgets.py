"""Элементы интерфейса, которых нет в Qt в нужном виде: переключатель,
карточки, главная кнопка сессии, нажимаемый значок, плавная прокрутка,
вкладки-переключатель, слой поверх окна, фон окна."""

from session_controller.i18n import tr

from PySide6.QtCore import (
    Property, QEvent, QPoint,
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
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from session_controller import theme


class Background(QWidget):
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), theme.qcolor(theme.current().bg))


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
    NOT_INSTALLED_HINT = "Новая программа станет доступна после перезапуска Session Controller."

    def __init__(self, icon: QIcon, name: str, hint: str, installed: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.installed = installed
        self.setToolTip(hint if installed else tr(self.NOT_INSTALLED_HINT))

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
            tag = QLabel(tr('нет на ПК'))
            tag.setObjectName("tag")
            layout.addWidget(tag)
            self.setEnabled(False)


class RevealRow(QWidget):
    """Раскрывает место в списке, сохраняя размер содержимого."""

    def __init__(self, content, parent):
        super().__init__(parent)
        self.content = content
        content.setParent(self)
        self.progress = 0.0
        self.motion = QVariantAnimation(self)
        self.motion.setStartValue(0.0)
        self.motion.setEndValue(1.0)
        self.motion.setDuration(280)
        self.motion.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.motion.valueChanged.connect(self._frame)
        self.motion.finished.connect(self._settle)
        self.set_expanded(False, animate=False)

    def set_expanded(self, expanded, *, animate=True):
        if expanded:
            self.show()
        direction = (QVariantAnimation.Direction.Forward if expanded
                     else QVariantAnimation.Direction.Backward)
        self.motion.setDirection(direction)
        if not animate:
            self.motion.stop()
            self.motion.setCurrentTime(self.motion.duration() if expanded else 0)
            self._frame(float(expanded))
            self._settle()
        elif self.motion.state() == QVariantAnimation.State.Stopped and self.progress != float(expanded):
            self.motion.start()

    def _frame(self, progress):
        self.progress = progress
        height = self.content.sizeHint().height()
        self.setFixedHeight(round((height + 6) * progress))
        self._place_content(height)

    def _place_content(self, height):
        self.content.setGeometry(0, round(-6 * (1 - self.progress)), self.width(), height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_content(self.content.sizeHint().height())

    def _settle(self):
        self.setVisible(self.progress > 0)


class PinDragLayer(QWidget):
    """Рисует перестановку поверх списка, пока сам layout хранит конечные позиции."""

    def __init__(self, parent, rows, key, press):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.rows = rows
        self.key = key
        first = min(widget.y() for widget in rows.values())
        bottom = max(widget.geometry().bottom() for widget in rows.values())
        self.setGeometry(0, first, parent.width(), bottom - first + 1)
        self.pictures = {k: row.content.grab() for k, row in rows.items()}
        self.dest = self.slot_positions()
        self.start = self.dest.copy()
        self.pointer_y = self.dest[key]
        self.offset = self.mapFromGlobal(press).y() - self.pointer_y
        self.t = 0.0
        self.scale_from, self.scale_to = 1.0, .96
        self.settling = False
        self.motion = QVariantAnimation(self)
        self.motion.setStartValue(0.)
        self.motion.setEndValue(1.)
        self.motion.setDuration(155)
        self.motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.motion.valueChanged.connect(self.frame)
        self.motion.finished.connect(self.finished)
        self.show()
        self.raise_()
        self.motion.start()

    def slot_positions(self):
        return {key: row.y() - self.y() for key, row in self.rows.items()}

    def position(self, key):
        if key == self.key and not self.settling:
            return self.pointer_y
        return self.start[key] + (self.dest[key] - self.start[key]) * self.t

    def scale(self):
        return self.scale_from + (self.scale_to - self.scale_from) * self.t

    def follow(self, point):
        height = self.rows[self.key].content.height()
        self.pointer_y = max(0, min(self.height() - height, self.mapFromGlobal(point).y() - self.offset))
        self.update()

    def slide(self, settling=False):
        starts = {key: self.position(key) for key in self.rows}
        scale = self.scale()
        self.motion.stop()
        self.start, self.dest = starts, self.slot_positions()
        self.scale_from, self.scale_to = scale, 1. if settling else .96
        self.settling = settling
        self.t = 0.
        self.motion.start()

    def frame(self, value):
        self.t = value
        self.update()

    def finished(self):
        if self.settling:
            self.hide()
            self.deleteLater()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), theme.qcolor(theme.current().bg))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for key in (*[k for k in self.rows if k != self.key], self.key):
            image = self.pictures[key]
            size = image.deviceIndependentSize()
            factor = self.scale() if key == self.key else 1.
            width, height = size.width() * factor, size.height() * factor
            bounds = QRectF((self.width() - width) / 2, self.position(key) + (size.height() - height) / 2,
                            width, height)
            painter.drawPixmap(bounds, image, QRectF(image.rect()))


class PinButton(QToolButton):
    """Нарисованная векторная булавка с коротким поворотом при закреплении."""

    lifted = Signal(QPointF)
    tapped = Signal()
    dragged = Signal(QPointF)
    dropped = Signal()

    def __init__(self, parent=None, *, reorderable=False):
        super().__init__(parent)
        self.reorderable = reorderable
        self.press_origin = None
        self.dragging = False
        self.motion = QVariantAnimation(self)
        self.motion.setDuration(220)
        self.motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.position = 0.0
        self.motion.valueChanged.connect(self._frame)
        self.toggled.connect(self._toggle)

    def enable_drag(self, card):
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.installEventFilter(self)
        card.installEventFilter(self)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self.press_origin = event.globalPosition()
            self.dragging = False
            self.lifted.emit(self.press_origin)
            if watched is not self:
                event.accept()
                return True
        elif kind == QEvent.Type.MouseMove and self.press_origin is not None:
            if event.buttons() & Qt.MouseButton.LeftButton:
                distance = (event.globalPosition() - self.press_origin).manhattanLength()
                if self.dragging or distance >= QApplication.startDragDistance():
                    self.dragging = True
                    self.dragged.emit(event.globalPosition())
                    return True
        elif kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            if self.press_origin is not None:
                self.press_origin = None
                if self.dragging:
                    self.dragging = False
                    self.setDown(False)
                    self.dropped.emit()
                    return True
                self.tapped.emit()
        elif kind in (QEvent.Type.UngrabMouse, QEvent.Type.Hide) and self.press_origin is not None:
            self.press_origin = None
            self.setDown(False)
            if self.dragging:
                self.dropped.emit()
            else:
                self.tapped.emit()
            self.dragging = False
        return super().eventFilter(watched, event)

    def _frame(self, value):
        self.position = value
        self.update()

    def _toggle(self, checked):
        self.motion.stop()
        end = float(checked)
        if not self.isVisible():
            self._frame(end)
            return
        self.motion.setStartValue(self.position)
        self.motion.setEndValue(end)
        self.motion.start()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.width() / 2, self.height() / 2)
        p.rotate(28 + 12 * self.position)
        t = theme.current()
        ink = QColor.fromRgbF(*(
            a + (b - a) * self.position for a, b in
            zip(theme.qcolor(t.muted).getRgbF(), theme.qcolor(t.text).getRgbF())
        ))
        pen = QPen(ink, 1.5)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        fill = QColor(ink)
        fill.setAlphaF(self.position)
        p.setBrush(fill)
        head = QPainterPath()
        head.moveTo(-4, -7)
        for x, y in ((4, -7), (3, -5), (3, -1), (5, 2), (-5, 2), (-3, -1), (-3, -5)):
            head.lineTo(x, y)
        head.closeSubpath()
        p.drawPath(head)
        p.drawLine(QPointF(0, 2), QPointF(0, 8))


class SettingRow(_ClickableCard):
    """Настройка: заголовок, пояснение мелким шрифтом и переключатель."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        title_label.setWordWrap(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(14)
        layout.addWidget(title_label, 1)
        layout.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)


class SessionButton(QAbstractButton):
    """Главная кнопка с прогрессом операции и временем начала активной сессии."""

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

        self._color_change = QVariantAnimation(self)
        self._color_change.setDuration(120)
        self._color_change.valueChanged.connect(lambda _: self.update())

    def sizeHint(self) -> QSize:
        return QSize(240, self.HEIGHT)

    def _fill_color(self) -> QColor:
        if self._color_change.state() == QVariantAnimation.State.Running:
            return self._color_change.currentValue()
        t = theme.current()
        if self._mode == self.START and self.isEnabled():
            return theme.qcolor(t.inverse_hover if self.underMouse() else t.inverse_bg)
        return theme.qcolor(t.bg if self._mode == self.STOP else t.surface_2)

    def set_state(self, mode: str, title: str, subtitle: str = "") -> None:
        if mode != self._mode:
            previous = self._mode
            fill = self._fill_color()
            self._color_change.stop()
            self._mode = mode
            if self.isVisible() and self.BUSY in (previous, mode):
                self._color_change.setStartValue(fill)
                self._color_change.setEndValue(self._fill_color())
                self._color_change.start()
        self._subtitle = subtitle
        self.setText(title)
        self.update()

    def paintEvent(self, _event) -> None:
        t = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = self._fill_color()
        painter.setBrush(fill)
        if self._mode == self.STOP:
            rect.adjust(1, 1, -1, -1)
            if not t.dark:
                painter.setPen(QPen(theme.qcolor(t.muted), 3))
                painter.drawRoundedRect(rect, 8, 8)
            painter.setPen(QPen(QColor("white"), 2))
            title_color = theme.qcolor(t.text)
        elif self._mode == self.START and self.isEnabled():
            painter.setPen(Qt.PenStyle.NoPen)
            title_color = theme.qcolor(t.inverse_text)
        else:
            painter.setPen(QPen(theme.qcolor(t.border_strong), 1))
            title_color = theme.qcolor(t.muted if self._mode == self.BUSY else t.dim)
        painter.drawRoundedRect(rect, 8, 8)
        if self._color_change.state() == QVariantAnimation.State.Running:
            title_color = QColor("black" if fill.lightness() >= 118 else "white")

        title_font = QFont(theme.fonts().display)
        title_font.setPixelSize(17)
        title_font.setWeight(QFont.Weight.DemiBold)
        sub_font = QFont(theme.fonts().body)
        sub_font.setPixelSize(12)
        title_metrics = QFontMetricsF(title_font)
        sub_metrics = QFontMetricsF(sub_font)

        title_width = title_metrics.horizontalAdvance(self.text())
        block_height = title_metrics.height()
        if self._subtitle:
            block_height += 1 + sub_metrics.height()
        top = (self.height() - block_height) / 2
        left = (self.width() - title_width) / 2
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

    def __init__(self, parent: QWidget | None = None, *, wheel_step: int = 120,
                 wheel_duration: int = 340) -> None:
        super().__init__(parent)
        self._wheel_step = wheel_step
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._target = 0
        self._animation = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._animation.setDuration(wheel_duration)
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
        target = int(max(bar.minimum(), min(bar.maximum(), start - delta / 120 * self._wheel_step)))
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
        height = free_height
        self.child.setGeometry(left + (free_width - width) // 2, top + (free_height - height) // 2,
                               width, height)
