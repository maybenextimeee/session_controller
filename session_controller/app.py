"""Главное окно Session Controller и значок в трее."""

import getpass
import logging
import sys
import threading
from collections.abc import Callable
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QFileInfo, QLockFile, QObject, Qt, QThread, QTimer, QUrl, Signal, Slot, QPoint, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QFileIconProvider,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from session_controller import __version__, autostart, dialogs, theme, updates
from session_controller.icons import make_icon, target_icon
from session_controller.paths import app_home
from session_controller.session import Session, SessionError
from session_controller.settings import Settings
from session_controller.targets import (
    AI,
    APP,
    BROWSER,
    CREDENTIALS,
    VPN,
    Target,
    downloads_target,
    known_targets,
)
from session_controller.widgets import (
    CenteredColumn,
    Background,
    Overlay,
    PressableIcon,
    RevealRow,
    Segmented,
    SessionButton,
    SettingRow,
    SmoothScrollArea,
    TargetCard,
    PinButton,
)
from session_controller.winapi import (
    block_shutdown,
    create_app_mutex,
    downloads_folder,
    redraw_title_bar,
    unblock_shutdown,
)

from session_controller import i18n
from session_controller.i18n import tr
from session_controller.pins import initial_pins

log = logging.getLogger(__name__)

APP_NAME = "Session Controller"
# Сколько удаляемых файлов из «Загрузок» показывать в окне подтверждения.
MAX_LISTED_DOWNLOADS = 6
REPO_URL = "https://github.com/maybenextimeee/session_controller"
# По этому имени установщик понимает, что программа запущена (AppMutex в installer.iss).
APP_MUTEX = "SessionControllerMutex"
# Через этот канал вторая копия программы просит первую показать окно.
INSTANCE_SERVER = f"SessionController-{getpass.getuser()}"

# Значки из шрифта Windows (Segoe MDL2 Assets / Segoe Fluent Icons) и запасные символы.
GEAR_GLYPH, GEAR_FALLBACK = "\ue713", "⚙"
BACK_GLYPH, BACK_FALLBACK = "\ue72b", "←"
CLOSE_GLYPH, CLOSE_FALLBACK = "\ue711", "✕"

# Всё содержимое окна — в колонке не шире этой: на большом окне она стоит по
# центру, а не растягивается на весь экран.
CONTENT_WIDTH = 576
WINDOW_MARGINS = (22, 18, 22, 22)  # слева, сверху, справа, снизу

class _SessionThread(QThread):
    """Файловая операция в фоне. Результат читается после сигнала QThread.finished."""
    progress = Signal(int, int, str)

    def __init__(self, task, parent):
        super().__init__(parent)
        self.task = task
        self.error = None

    def run(self):
        try:
            self.task(self.progress.emit)
        except Exception as error:
            log.exception("Ошибка при выполнении операции сессии")
            self.error = str(error)


class _UpdateChecker(QObject):
    """Раз в сутки спрашивает GitHub о новой версии — в отдельном потоке, чтобы
    окно не ждало медленный интернет."""

    found = Signal(str, str)  # версия, ссылка на страницу загрузки

    FIRST_CHECK_MS = 15_000            # через 15 секунд после запуска
    INTERVAL_MS = 24 * 60 * 60 * 1000  # потом раз в сутки

    def __init__(self, parent: QObject, enabled: Callable[[], bool]) -> None:
        super().__init__(parent)
        self._enabled = enabled
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)

    def start(self) -> None:
        QTimer.singleShot(self.FIRST_CHECK_MS, self.check)
        self._timer.start(self.INTERVAL_MS)

    def check(self) -> None:
        if self._enabled():
            threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        release = updates.newer_release(__version__)
        if release is not None:
            self.found.emit(release.version, release.url)


class MainWindow(QMainWindow):
    def __init__(
        self,
        session: Session,
        settings: Settings,
        settings_path: Path,
        themes: theme.ThemeManager,
    ) -> None:
        super().__init__()
        self.session = session
        self.settings = settings
        i18n.set_language(settings.language)
        self.installed_ids = {t.id for t in session.installed_targets()}
        if settings.pinned_targets is None:
            settings.pinned_targets = initial_pins(session.targets, self.installed_ids)
            settings.save(settings_path)
        self.settings_path = settings_path
        self.themes = themes
        self._user_quit = False
        self._busy = False
        self._task_thread: _SessionThread | None = None
        self._task_done = None
        self._page_motion = None
        self._update_url = REPO_URL + "/releases/latest"
        self.update_checker = _UpdateChecker(self, lambda: self.settings.check_updates)
        self.update_checker.found.connect(self.on_update_found)

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(make_icon())
        self.setMinimumSize(480, 460)

        self.pages = QStackedWidget()
        self.main_page = self._build_main_page()
        self.settings_page = self._build_settings_page()
        self.pages.addWidget(self.main_page)
        self.pages.addWidget(self.settings_page)
        self._switch_page(self.main_page)

        background = Background()
        # Колонка не шире CONTENT_WIDTH и не выше, чем нужно содержимому;
        # лишнее место вокруг делится поровну — колонка стоит по центру.
        root = QVBoxLayout(background)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(CenteredColumn(self.pages, CONTENT_WIDTH, WINDOW_MARGINS))
        self.setCentralWidget(background)
        self.apps_overlay = self._build_apps_overlay(background)

        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray_menu = QMenu()
        # Без этого скруглённые углы меню рисуются на прямоугольной подложке.
        self.tray_menu.setWindowFlags(
            self.tray_menu.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.tray_menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.tray_status_action = QAction(self.tray_menu)
        self.tray_status_action.setEnabled(False)
        self.tray_menu.addAction(self.tray_status_action)
        self.tray_menu.addSeparator()
        self.tray_toggle_action = self.tray_menu.addAction("", self.toggle_session)
        self.tray_open = self.tray_menu.addAction(tr('Открыть'), self.show_window)
        self.tray_menu.addSeparator()
        self.tray_quit = self.tray_menu.addAction(tr('Выход'), self.quit_app)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

        app = QApplication.instance()
        # Windows спрашивает программы, можно ли выключаться (WM_QUERYENDSESSION).
        app.commitDataRequest.connect(self.on_system_shutdown)
        # Запасной вариант: программу закрывают не по нашей кнопке «Выход».
        app.aboutToQuit.connect(self.on_about_to_quit)

        self.instance_server = QLocalServer(self)
        self.instance_server.newConnection.connect(self.on_other_instance_started)
        # Мы единственная копия (это гарантирует app.lock), так что канал,
        # оставшийся от аварийно закрытой копии, можно убрать.
        QLocalServer.removeServer(INSTANCE_SERVER)
        if not self.instance_server.listen(INSTANCE_SERVER):
            log.warning("Не удалось открыть канал для второй копии: %s",
                        self.instance_server.errorString())

        # Раз в полминуты обновляем, сколько уже идёт сессия.
        self.clock = QTimer(self)
        self.clock.setInterval(30_000)
        self.clock.timeout.connect(self.refresh)
        self.clock.start()

        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        escape.activated.connect(self.on_escape)

        themes.changed.connect(self.on_theme_changed)
        self.refresh()
        self._fit_to_screen()

    # ---------- Страницы ----------

    def _build_main_page(self) -> QWidget:
        settings_button = _icon_button(GEAR_GLYPH, GEAR_FALLBACK, tr('Настройки'))
        settings_button.clicked.connect(self.show_settings)

        logo = PressableIcon(make_icon(), 40)
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")

        # Появляется, только если на GitHub вышла версия новее.
        self.update_button = QPushButton()
        self.update_button.setObjectName("updateButton")
        self.update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_button.setToolTip(tr('Открыть страницу загрузки новой версии'))
        self.update_button.clicked.connect(self.open_update_page)
        self.update_button.hide()

        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(logo)
        header.addWidget(title, 1)
        header.addWidget(self.update_button)
        header.addWidget(settings_button)

        # Что очищать.
        targets_header = QHBoxLayout()
        heading = QLabel(tr("Закреплённые"))
        heading.setObjectName("homeHeading")
        targets_header.addWidget(heading)
        targets_header.addStretch(1)

        # Найденные на компьютере программы можно включать и выключать.
        # Новая программа появится здесь после перезапуска Session Controller.
        self.target_cards: dict[str, TargetCard] = {}
        self.main_content = QWidget()
        self.home_rows = {}
        self.pin_buttons = {}
        self.pin_list = QVBoxLayout()
        self.pin_list.setSpacing(0)
        for t in self.session.targets:
            installed = t.id in self.installed_ids
            card = self._target_card(t, installed)
            if installed:
                card.switch.setChecked(t.id not in self.settings.disabled_targets)
                card.switch.toggled.connect(self.on_targets_changed)
                self.target_cards[t.id] = card
            self.home_rows[t.id] = RevealRow(self._pin_row(t, card), self.main_content)
        empty_label = QLabel(tr("Закрепите программы из каталога."))
        empty_label.setObjectName("small")
        self.empty_pins = RevealRow(empty_label, self.main_content)
        self._layout_pins()
        all_button = QPushButton(tr("Каталог программ") + f"    {len(self.session.targets)}")
        all_button.setObjectName("moreButton")
        all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        all_button.clicked.connect(self.show_all_programs)

        # Если программ много или экран маленький, главная страница прокручивается.
        layout = QVBoxLayout(self.main_content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addSpacing(26)
        layout.addLayout(targets_header)
        layout.addSpacing(10)
        layout.addLayout(self.pin_list)
        layout.addWidget(self.empty_pins)
        layout.addWidget(all_button)
        layout.addStretch(1)

        self.main_scroll = SmoothScrollArea()
        self.main_scroll.setWidget(self.main_content)

        # Одна кнопка внизу окна — всё о сессии написано прямо на ней.
        self.session_button = SessionButton()
        self.session_button.clicked.connect(self.toggle_session)

        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        page_layout.addWidget(self.main_scroll, 1)
        page_layout.addSpacing(32)
        page_layout.addWidget(self.session_button)
        return page

    def _pin_row(self, target, card):
        row = QWidget(self.main_content)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(card, 1)
        pin = PinButton()
        pin.setObjectName("pin")
        pin.setCheckable(True)
        pin.setChecked(target.id in self.settings.pinned_targets)
        self._label_pin(pin, target)
        pin.clicked.connect(lambda checked: self._toggle_pin(target, checked))
        self.pin_buttons.setdefault(target.id, []).append(pin)
        layout.addWidget(pin)
        return row

    def _label_pin(self, pin, target):
        action = tr("Открепить") if pin.isChecked() else tr("Закрепить")
        pin.setToolTip(f"{action} · {tr(target.name)}")
        pin.setAccessibleName(pin.toolTip())

    def _layout_pins(self):
        while self.pin_list.count():
            self.pin_list.takeAt(0)
        for row in self.home_rows.values():
            row.hide()
        pins = [key for key in self.settings.pinned_targets if key in self.home_rows]
        for key in pins:
            self.pin_list.addWidget(self.home_rows[key])
            self.home_rows[key].set_expanded(True, animate=False)
        self.empty_pins.set_expanded(not pins, animate=False)

    def _toggle_pin(self, target, checked):
        pins = self.settings.pinned_targets
        if checked and target.id not in pins:
            pins.append(target.id)
        elif not checked and target.id in pins:
            pins.remove(target.id)
        self.settings.save(self.settings_path)
        for pin in self.pin_buttons[target.id]:
            pin.setChecked(checked)
            self._label_pin(pin, target)
        row = self.home_rows[target.id]
        if checked:
            self.pin_list.addWidget(row)
        row.set_expanded(checked)
        self.empty_pins.set_expanded(not pins)

    def _fit_to_screen(self) -> None:
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        screen = self.screen()
        width, height = 620, 570
        if screen:
            available = screen.availableGeometry()
            width = min(width, available.width() - 16)
            height = min(height, available.height() - 48)
        self.setFixedSize(width, height)

    def _target_card(self, target: Target, installed: bool) -> TargetCard:
        return TargetCard(target_icon(target), tr(target.name), tr(target.hint),
                          installed=installed)

    def _build_apps_overlay(self, parent: QWidget) -> Overlay:
        """Панель поверх окна со всеми программами, которые умеет очищать Session Controller."""
        overlay = Overlay(parent)

        title = QLabel(tr('Все программы'))
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            tr('Всего: {0}, на этом компьютере найдено: {1}.').format(len(self.session.targets), len(self.target_cards))
        )
        subtitle.setObjectName("small")
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(title)
        texts.addWidget(subtitle)
        close_button = _icon_button(CLOSE_GLYPH, CLOSE_FALLBACK, tr('Закрыть'))
        close_button.clicked.connect(overlay.close_overlay)
        header = QHBoxLayout()
        header.addLayout(texts, 1)
        header.addWidget(close_button, 0, Qt.AlignmentFlag.AlignTop)

        note = QLabel(
            tr('Программы, которых нет на компьютере, тоже под защитой: если их установят и запустят во время сессии, при завершении их данные удалятся. Новая программа станет доступна после перезапуска Session Controller.')
        )
        note.setObjectName("small")
        note.setWordWrap(True)

        # Найденные программы здесь переключаются так же, как в главном окне.
        self.overlay_cards: dict[str, TargetCard] = {}
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 6, 0)
        content_layout.setSpacing(6)
        for group_title, kind in ((tr('Браузеры'), BROWSER), (tr('Приложения'), APP), ("VPN", VPN),
                                  (tr('ИИ'), AI), ("Windows", CREDENTIALS)):
            group = [t for t in self.session.targets if t.kind == kind]
            if not group:
                continue
            # Сначала найденные, потом остальные.
            group.sort(key=lambda t: t.id not in self.target_cards)
            content_layout.addSpacing(10)
            content_layout.addWidget(_section_label(group_title))
            content_layout.addSpacing(2)
            for target in group:
                card = self._target_card(target, installed=target.id in self.target_cards)
                if target.id in self.target_cards:
                    main_card = self.target_cards[target.id]
                    card.switch.setChecked(main_card.switch.isChecked())
                    card.switch.toggled.connect(main_card.switch.setChecked)
                    self.overlay_cards[target.id] = card
                content_layout.addWidget(self._pin_row(target, card))
        content_layout.addStretch(1)

        scroll = SmoothScrollArea()
        scroll.setWidget(content)

        layout = QVBoxLayout(overlay.panel)
        layout.setContentsMargins(20, 18, 14, 16)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addSpacing(10)
        layout.addWidget(note)
        layout.addSpacing(4)
        layout.addWidget(scroll, 1)
        return overlay

    def show_all_programs(self) -> None:
        self.apps_overlay.open()

    def _build_settings_page(self) -> QWidget:
        back_button = _icon_button(BACK_GLYPH, BACK_FALLBACK, tr('Назад'))
        back_button.clicked.connect(self.show_main)
        title = QLabel(tr('Настройки'))
        title.setObjectName("pageTitle")
        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(back_button)
        header.addWidget(title, 1)

        # Оформление.
        theme_title = QLabel(tr('Тема'))
        theme_title.setObjectName("cardTitle")
        theme_texts = QVBoxLayout()
        theme_texts.setSpacing(3)
        theme_texts.addWidget(theme_title)
        self.theme_picker = Segmented({key: tr(label) for key, label in theme.CHOICES.items()}, self.themes.choice)
        self.theme_picker.chosen.connect(self.on_theme_chosen)
        theme_card = QFrame()
        theme_card.setObjectName("panel")
        theme_layout = QVBoxLayout(theme_card)
        theme_layout.setContentsMargins(16, 13, 16, 14)
        theme_layout.setSpacing(12)
        theme_layout.addLayout(theme_texts)
        theme_layout.addWidget(self.theme_picker)
        theme_layout.addWidget(QLabel(tr("Язык интерфейса")))
        self.language_picker = Segmented({"ru": "Русский", "en": "English"}, self.settings.language)
        self.language_picker.chosen.connect(self.change_language)
        theme_layout.addWidget(self.language_picker)

        # Сессия.
        self.shutdown_row = SettingRow(
            tr('Выходить из аккаунтов при выключении компьютера'),
        )
        self.shutdown_row.switch.setChecked(self.settings.logout_on_shutdown)
        self.shutdown_row.switch.toggled.connect(self.on_shutdown_option_changed)

        self.autostart_row = SettingRow(
            tr('Запускать вместе с Windows'),
        )
        if autostart.is_supported():
            self.autostart_row.switch.setChecked(autostart.is_enabled())
        else:
            self.autostart_row.setEnabled(False)
        self.autostart_row.switch.toggled.connect(self.on_autostart_changed)

        self.updates_row = SettingRow(
            tr('Проверять обновления'),
        )
        self.updates_row.switch.setChecked(self.settings.check_updates)
        self.updates_row.switch.toggled.connect(self.on_check_updates_changed)

        self.downloads_row = SettingRow(
            tr('Удалять скачанное за сессию'),
        )
        self.downloads_row.switch.setChecked(self.settings.clean_downloads)
        self.downloads_row.switch.toggled.connect(self.on_clean_downloads_changed)

        # О программе.
        about = QFrame()
        about.setObjectName("panel")
        about_layout = QHBoxLayout(about)
        about_layout.setContentsMargins(16, 13, 16, 13)
        about_icon = QLabel()
        about_icon.setFixedSize(22, 22)
        about_icon.setPixmap(make_icon().pixmap(22, 22))
        version = QLabel(tr('Версия {0}').format(__version__))
        version.setObjectName("cardTitle")
        about_layout.addWidget(about_icon)
        about_layout.addSpacing(6)
        about_layout.addWidget(version, 1)
        for text, handler in (
            ("GitHub ↗", lambda: QDesktopServices.openUrl(QUrl(REPO_URL))),
            (tr('Папка с логом ↗'), self.open_app_folder),
        ):
            link = QPushButton(text)
            link.setObjectName("linkButton")
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.clicked.connect(handler)
            about_layout.addSpacing(12)
            about_layout.addWidget(link)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addSpacing(22)
        layout.addWidget(_section_label(tr('Оформление')))
        layout.addSpacing(10)
        layout.addWidget(theme_card)
        layout.addSpacing(22)
        layout.addWidget(_section_label(tr('Сессия')))
        layout.addSpacing(10)
        layout.addWidget(self.shutdown_row)
        layout.addSpacing(8)
        layout.addWidget(self.autostart_row)
        layout.addSpacing(8)
        layout.addWidget(self.updates_row)
        layout.addSpacing(8)
        layout.addWidget(self.downloads_row)
        layout.addSpacing(22)
        layout.addWidget(_section_label(tr('О программе')))
        layout.addSpacing(10)
        layout.addWidget(about)
        layout.addStretch(1)

        # В маленьком окне настройки прокручиваются, а не обрезаются.
        page = SmoothScrollArea()
        page.setWidget(content)
        return page

    def change_language(self, language):
        if self.settings.language == language or self._busy:
            return
        self.settings.language = language
        self.settings.save(self.settings_path)
        i18n.set_language(language)
        self.apps_overlay.hide()
        self.apps_overlay.deleteLater()
        for page in (self.main_page, self.settings_page):
            self.pages.removeWidget(page)
            page.deleteLater()
        update_visible = not self.update_button.isHidden()
        self.main_page = self._build_main_page()
        self.settings_page = self._build_settings_page()
        self.pages.addWidget(self.main_page)
        self.pages.addWidget(self.settings_page)
        self.apps_overlay = self._build_apps_overlay(self.centralWidget())
        self.tray_open.setText(tr("Открыть"))
        self.tray_quit.setText(tr("Выход"))
        if update_visible:
            self.on_update_found(self._update_version, self._update_url)
        self.show_settings()
        self.refresh()

    def show_settings(self) -> None:
        self._switch_page(self.settings_page)
        self.settings_page.setFocus()

    def show_main(self) -> None:
        self._switch_page(self.main_page)

    def _switch_page(self, page: QWidget) -> None:
        # Высоту колонки задаёт только видимая страница: иначе короткая главная
        # растягивалась бы до высоты настроек, и под списком была бы пустота.
        for other in (self.main_page, self.settings_page):
            policy = (QSizePolicy.Policy.Preferred if other is page
                      else QSizePolicy.Policy.Ignored)
            other.setSizePolicy(policy, policy)
        previous = self.pages.currentWidget()
        if self._page_motion is not None:
            self._page_motion.stop()
            self._page_motion.deleteLater()
            self._page_motion = None
        self.pages.setCurrentWidget(page)
        self.pages.updateGeometry()
        if self.isVisible() and previous is not page:
            motion = QPropertyAnimation(page, b"pos", self)
            motion.setStartValue(QPoint(16 if page is self.settings_page else -12, 0))
            motion.setEndValue(QPoint(0, 0))
            motion.setDuration(180)
            motion.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._page_motion = motion
            motion.start()

    def on_escape(self) -> None:
        """Esc закрывает то, что открыто поверх главной: панель или настройки."""
        if self.apps_overlay.isVisible():
            self.apps_overlay.close_overlay()
        elif self.pages.currentWidget() is self.settings_page:
            self.show_main()

    # ---------- Сессия ----------

    def selected_targets(self) -> list[Target]:
        """Что очищать в новой сессии: всё, кроме снятых галочек.

        Программы, которых на компьютере пока нет, тоже включены: если их
        установят и запустят во время сессии, следы тоже удалятся.
        """
        return [t for t in self.session.targets if t.id not in self.settings.disabled_targets]

    def toggle_session(self) -> None:
        if self._busy:
            return
        if self.session.is_active:
            self.end_session()
        else:
            self.start_session()

    def has_selection(self) -> bool:
        """Включена ли хотя бы одна программа в списке «Что очищать»."""
        return any(card.switch.isChecked() for card in self.target_cards.values())

    def start_session(self) -> None:
        # Кнопка в этом случае неактивна, но начать можно и из меню в трее.
        if not self.has_selection():
            return
        targets = self.selected_targets()
        try:
            self.session.check_can_close(targets)
        except SessionError as error:
            dialogs.inform(self, tr('Не получится начать сессию'), str(error),
                           dialogs.WARNING, dialogs.CAUTION)
            return

        running = self.session.running(targets)
        if running and not dialogs.confirm(
            self,
            tr('Нужно закрыть программы'),
            tr('Чтобы запомнить, как всё было до тебя, эти программы нужно закрыть. Несохранённое в них пропадёт.'),
            tr('Закрыть и начать'),
            dialogs.WARNING,
            dialogs.CAUTION,
            items=self._program_items(running),
            items_title=tr('Будут закрыты'),
        ):
            return

        if self.settings.clean_downloads:
            targets = [*targets, downloads_target(downloads_folder())]
        self.run_task(tr('Сохраняю'), lambda progress: self.session.start(targets, progress))

    def end_session(self, confirm: bool = True,
                    on_done: Callable[[bool], None] | None = None) -> None:
        if confirm:
            text = tr('Всё, что появилось за сессию, — входы в аккаунты, пароли, история — исчезнет.')
            running = self.session.running(self.session.session_targets())
            if running:
                text += tr(' Открытые программы закроются, несохранённое в них пропадёт.')
            downloads = self.session.new_downloads()
            if downloads:
                text += tr(' Скачанное за сессию удалится из «Загрузок» насовсем.')
            if not dialogs.confirm(
                self,
                tr('Завершить сессию?'),
                text,
                tr('Завершить сессию'),
                dialogs.SIGN_OUT,
                items=self._program_items(running),
                items_title=tr('Будут закрыты'),
                more_items=_download_items(downloads),
                more_items_title=tr('Удалится из «Загрузок»: {0}').format(_count_files(len(downloads))),
            ):
                if on_done is not None:
                    on_done(False)
                return

        self.run_task(tr('Очищаю'), lambda progress: self.session.end(progress), on_done)

    def run_task(self, verb: str,
                 task: Callable[[Callable[[int, int, str], None]], None],
                 on_done: Callable[[bool], None] | None = None) -> None:
        """Выполнить долгую операцию в фоне, показывая прогресс на кнопке.

        Окно остаётся отзывчивым: снимок/откут большого профиля идёт в отдельном
        потоке. Когда всё закончится, вызывается on_done(получилось ли).
        """
        if self._busy:
            return
        self._busy = True
        self.language_picker.setEnabled(False)
        self._task_verb = verb
        self.session_button.set_state(SessionButton.BUSY, verb + "…")
        self.session_button.setEnabled(False)
        self.tray_toggle_action.setEnabled(False)
        self._set_targets_enabled(False)

        thread = _SessionThread(task, self)
        thread.progress.connect(self._on_task_progress, Qt.ConnectionType.QueuedConnection)
        thread.finished.connect(self._on_task_finished, Qt.ConnectionType.QueuedConnection)
        self._task_thread = thread
        self._task_done = on_done
        thread.start()

    @Slot(int, int, str)
    def _on_task_progress(self, done: int, total: int, name: str) -> None:
        self.session_button.set_state(SessionButton.BUSY, self._task_verb,
                                      tr('{0} · {1} из {2}').format(tr(name), done, total))

    @Slot()
    def _on_task_finished(self):
        thread = self._task_thread
        error = thread.error
        on_done = self._task_done
        self._task_thread = self._task_done = None
        thread.wait()
        thread.deleteLater()
        ok = error is None
        self._busy = False
        self.language_picker.setEnabled(True)
        self.session_button.setEnabled(True)
        if not ok:
            dialogs.inform(self, tr('Что-то пошло не так'), error, dialogs.ERROR, dialogs.DANGER)
        self.refresh()
        if on_done is not None:
            on_done(ok)

    def recover_after_restart(self) -> None:
        """Вызвать при запуске: компьютер могли выключить посреди сессии."""
        if not self.session.computer_restarted_since_start():
            return

        if not self.settings.logout_on_shutdown:
            log.info("Компьютер перезагружался, галочка выключена — сессия продолжается")
            self.session.adopt_current_boot()
            return

        log.info("Компьютер выключился посреди сессии — выхожу из аккаунтов сейчас")

        def recovered(ok: bool) -> None:
            if ok:
                dialogs.inform(
                    self,
                    tr('Выход из аккаунтов выполнен'),
                    tr('Компьютер выключился во время сессии, и программа не успела выйти из аккаунтов. Сделала это сейчас — всё как было до сессии.'),
                    dialogs.RESTORED,
                )

        self.end_session(confirm=False, on_done=recovered)

    def on_system_shutdown(self, _manager=None) -> None:
        hwnd = int(self.winId())
        if self._busy:
            # Идёт фоновый снимок/откат — дождёмся его, иначе запустили бы
            # очистку второй раз поверх первой.
            block_shutdown(hwnd, tr('Session Controller заканчивает операцию…'))
            while self._busy:
                QApplication.processEvents()
                QThread.msleep(20)
            unblock_shutdown(hwnd)

        if not self.session.is_active:
            return
        if not self.settings.logout_on_shutdown:
            log.info("Windows завершает работу, галочка выключена — сессия сохраняется")
            return

        log.info("Windows завершает работу — выхожу из аккаунтов")
        block_shutdown(hwnd, tr('Session Controller выходит из твоих аккаунтов…'))
        try:
            self.session.end()
        except Exception:
            log.exception("Не удалось завершить сессию при выключении")
        finally:
            unblock_shutdown(hwnd)
        self.refresh()

    def on_about_to_quit(self) -> None:
        if not self._user_quit:
            self.on_system_shutdown()

    # ---------- Настройки ----------

    def on_shutdown_option_changed(self, checked: bool) -> None:
        self.settings.logout_on_shutdown = checked
        self.settings.save(self.settings_path)
        log.info("Выход при выключении: %s", "да" if checked else "нет")
        self.refresh()

    def on_clean_downloads_changed(self, checked: bool) -> None:
        self.settings.clean_downloads = checked
        self.settings.save(self.settings_path)
        log.info("Очистка «Загрузок»: %s", "да" if checked else "нет")

    def on_check_updates_changed(self, checked: bool) -> None:
        self.settings.check_updates = checked
        self.settings.save(self.settings_path)
        log.info("Проверка обновлений: %s", "да" if checked else "нет")
        if checked:
            self.update_checker.check()
        else:
            self.update_button.hide()

    def start_update_checks(self) -> None:
        self.update_checker.start()

    def on_update_found(self, version: str, url: str) -> None:
        if not self.settings.check_updates:
            return
        self._update_version = version
        self._update_url = url
        self.update_button.setText(tr('Новая версия {0}').format(version))
        self.update_button.show()

    def open_update_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self._update_url))

    def on_autostart_changed(self, checked: bool) -> None:
        try:
            autostart.set_enabled(checked)
        except OSError as error:
            log.exception(tr('Не удалось изменить автозапуск'))
            dialogs.inform(self, tr('Не удалось изменить автозапуск'), str(error),
                           dialogs.ERROR, dialogs.DANGER)
            return
        log.info("Автозапуск: %s", "да" if checked else "нет")

    def on_theme_chosen(self, choice: str) -> None:
        self.settings.theme = choice
        self.settings.save(self.settings_path)
        log.info("Тема: %s", choice)
        self.themes.set_choice(choice)

    def on_theme_changed(self) -> None:
        # Стиль Qt обновляет сам, а то, что мы рисуем сами, нужно перерисовать.
        self.refresh()
        for widget in self.findChildren(QWidget):
            widget.update()
        # Заголовок окна рисует Windows, и сам он не обновится до сворачивания.
        # Qt меняет его цвет не мгновенно, поэтому перерисовываем чуть позже.
        if self.isVisible():
            QTimer.singleShot(50, lambda: redraw_title_bar(int(self.winId())))

    def open_app_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.session.home)))

    def on_other_instance_started(self) -> None:
        """Программу запустили ещё раз (например, с ярлыка) — просто показываем окно."""
        log.info("Программу запустили ещё раз — показываю окно")
        connection = self.instance_server.nextPendingConnection()
        if connection:
            connection.disconnected.connect(connection.deleteLater)
            connection.disconnectFromServer()
        self.show_window()

    def on_targets_changed(self) -> None:
        self.settings.disabled_targets = [
            target_id for target_id in self.settings.disabled_targets if target_id not in self.target_cards
        ] + [
            target_id for target_id, card in self.target_cards.items()
            if not card.switch.isChecked()
        ]
        self.settings.save(self.settings_path)
        self.refresh()

    # ---------- Окно и трей ----------

    def refresh(self) -> None:
        """Обновить надписи под текущее состояние сессии."""
        if self._busy:
            return
        active = self.session.is_active
        if active:
            started = _format_time(self.session.started_at)
            self.session_button.set_state(SessionButton.STOP, tr('Завершить сессию'),
                                          tr('С {0}').format(started))
            self.tray_toggle_action.setText(tr('Завершить сессию'))
            tray_status = tr('Сессия идёт с {0}').format(started)
        else:
            hint = "" if self.has_selection() else tr('включи хотя бы одну программу')
            self.session_button.set_state(SessionButton.START, tr('Начать сессию'), hint)
            self.tray_toggle_action.setText(tr('Начать сессию'))
            tray_status = tr('Сессия не активна')

        # Начать нельзя, пока не выбрана ни одна программа.
        can_toggle = active or self.has_selection()
        self.session_button.setEnabled(can_toggle)
        self.session_button.setCursor(Qt.CursorShape.PointingHandCursor if can_toggle
                                      else Qt.CursorShape.ForbiddenCursor)
        self.tray_toggle_action.setEnabled(can_toggle)

        # Во время сессии список не меняется: он был зафиксирован при старте.
        self._set_targets_enabled(not active)
        self.downloads_row.setEnabled(not active)
        for target_id, card in self.overlay_cards.items():
            card.switch.setChecked(self.target_cards[target_id].switch.isChecked())
        self.tray_status_action.setText(tray_status)
        self.tray.setToolTip(f"{APP_NAME}: {tray_status.lower()}")

    def _program_items(self, targets: list[Target]) -> list[tuple[QIcon, str]]:
        """Значки и названия программ — для списка в окне-вопросе."""
        return [(target_icon(t), tr(t.name)) for t in targets]

    def _set_targets_enabled(self, enabled: bool) -> None:
        for card in (*self.target_cards.values(), *self.overlay_cards.values()):
            card.setEnabled(enabled)

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_window()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._user_quit:
            event.accept()
            return

        event.ignore()
        if QSystemTrayIcon.isSystemTrayAvailable():
            # Программа продолжает работать в трее: так она поймает выключение
            # компьютера. Совсем выйти можно через меню значка в трее.
            self.hide()
        else:
            self.quit_app()

    def quit_app(self) -> None:
        if self._busy:
            return  # идёт операция — дождёмся её, потом можно выходить
        if self.session.is_active:
            box = dialogs.Dialog(
                self,
                tr('Сессия ещё идёт'),
                tr('Завершить её перед выходом? Если нет, твои аккаунты останутся на компьютере, а выход при выключении не сработает, пока программа закрыта.'),
                [
                    dialogs.Button("cancel", tr('Отмена')),
                    dialogs.Button("keep", tr('Просто выйти')),
                    dialogs.Button("end", tr('Завершить и выйти'), dialogs.PRIMARY),
                ],
                dialogs.POWER,
                dialogs.CAUTION,
            )
            box.exec()
            if box.choice == "end":
                # Выйдем, когда очистка закончится.
                self.end_session(confirm=False,
                                 on_done=lambda ok: self._finish_quit() if ok else None)
                return
            if box.choice != "keep":
                return

        self._finish_quit()

    def _finish_quit(self) -> None:
        self._user_quit = True
        self.tray.hide()
        QApplication.quit()


def _download_items(paths: list) -> list[tuple[QIcon, str]]:
    """Файлы для окна подтверждения: со значками типа файла, не больше нескольких."""
    provider = QFileIconProvider()
    items = [(provider.icon(QFileInfo(str(p))), p.name) for p in paths[:MAX_LISTED_DOWNLOADS]]
    rest = len(paths) - MAX_LISTED_DOWNLOADS
    if rest > 0:
        items.append((QIcon(), tr('и ещё {0}').format(_count_files(rest))))
    return items


def _count_files(count: int) -> str:
    """«1 файл», «3 файла», «5 файлов» (папки тоже считаем файлами — так проще)."""
    if i18n.is_english():
        return f"{count} file" if count == 1 else f"{count} files"
    if count % 10 == 1 and count % 100 != 11:
        word = tr('файл')
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        word = tr('файла')
    else:
        word = tr('файлов')
    return f"{count} {word}"


def _section_label(text: str) -> QLabel:
    """Подпись раздела: мелкий капс с разрядкой."""
    label = QLabel(tr(text).upper())
    label.setObjectName("caps")
    return label


def _icon_button(glyph: str, fallback: str, tooltip: str) -> QToolButton:
    button = QToolButton()
    button.setObjectName("iconButton")
    button.setText(glyph if theme.fonts().icons else fallback)
    button.setToolTip(tooltip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _format_time(moment: datetime) -> str:
    if moment.date() == datetime.now().date():
        return moment.strftime("%H:%M")
    return moment.strftime("%d.%m %H:%M")


def setup_logging(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(home / "log.txt", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    ]
    if sys.stderr:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    sys.excepthook = lambda *exc_info: log.critical("Необработанная ошибка", exc_info=exc_info)


def main() -> int:
    """Аргументы командной строки:

    --minimized   не показывать окно, сразу спрятаться в трей (для автозапуска);
    --smoke-test  запуститься и через секунду выйти (проверка сборки в CI).
    """
    home = app_home()
    setup_logging(home)
    log.info("Запуск %s %s (%s)", APP_NAME, __version__, sys.executable)

    if "--smoke-test" in sys.argv:
        try:
            return _run(home, minimized=False, smoke_test=True)
        except Exception:
            log.exception("Проверка сборки не прошла")
            return 1
    return _run(home, minimized="--minimized" in sys.argv, smoke_test=False)


def _run(home: Path, minimized: bool, smoke_test: bool) -> int:

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(make_icon())
    # Закрытие окна не должно завершать программу: она живёт в трее.
    app.setQuitOnLastWindowClosed(False)

    settings_path = home / "settings.json"
    settings = Settings.load(settings_path)
    i18n.set_language(settings.language)
    # При первом запуске тема «как в системе», дальше — как выбрал пользователь.
    themes = theme.ThemeManager(app, settings.theme)

    # Две копии программы одновременно будут мешать друг другу.
    lock = QLockFile(str(home / "app.lock"))
    if not lock.tryLock(100):
        if not _show_running_instance():
            dialogs.inform(
                None,
                tr('Session Controller уже запущен'),
                tr('Его значок — в трее, возле часов. Нажми на него, чтобы открыть окно.'),
            )
        return 0
    create_app_mutex(APP_MUTEX)
    if autostart.is_supported():
        autostart.refresh_path()

    session = Session(home, known_targets())
    session.load()

    window = MainWindow(session, settings, settings_path, themes)
    if minimized and QSystemTrayIcon.isSystemTrayAvailable():
        # Окно всё равно создаём: через него Windows сообщает о выключении.
        window.winId()
    else:
        window.show()
    QTimer.singleShot(0, window.recover_after_restart)
    if not smoke_test:
        window.start_update_checks()

    if smoke_test:
        QTimer.singleShot(1000, app.quit)
        window._user_quit = True
    code = app.exec()
    if smoke_test:
        log.info("Проверка сборки прошла")
    return code


def _show_running_instance() -> bool:
    """Попросить уже запущенную копию показать окно."""
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_SERVER)
    if not socket.waitForConnected(1000):
        return False
    socket.disconnectFromServer()
    return True
