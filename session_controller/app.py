"""Главное окно Session Controller и значок в трее."""

import getpass
import logging
import sys
from collections.abc import Callable
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from session_controller import __version__, autostart, theme
from session_controller.icons import make_icon, target_icon
from session_controller.paths import app_home
from session_controller.session import Session, SessionError
from session_controller.settings import Settings
from session_controller.targets import Target, known_targets
from session_controller.widgets import Background, SettingRow, StatusPill, TargetCard
from session_controller.winapi import block_shutdown, create_app_mutex, unblock_shutdown

log = logging.getLogger(__name__)

APP_NAME = "Session Controller"
REPO_URL = "https://github.com/maybenextimeee/session_controller"
# По этому имени установщик понимает, что программа запущена (AppMutex в installer.iss).
APP_MUTEX = "SessionControllerMutex"
# Через этот канал вторая копия программы просит первую показать окно.
INSTANCE_SERVER = f"SessionController-{getpass.getuser()}"

# Значки из шрифта Windows (Segoe MDL2 Assets / Segoe Fluent Icons) и запасные символы.
GEAR_GLYPH, GEAR_FALLBACK = "", "⚙"
BACK_GLYPH, BACK_FALLBACK = "", "←"


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
        self.settings_path = settings_path
        self.themes = themes
        self._user_quit = False
        self._tray_hint_shown = False
        self._busy = False

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(make_icon())
        self.setMinimumWidth(540)

        self.pages = QStackedWidget()
        self.main_page = self._build_main_page()
        self.settings_page = self._build_settings_page()
        self.pages.addWidget(self.main_page)
        self.pages.addWidget(self.settings_page)

        background = Background()
        root = QVBoxLayout(background)
        root.setContentsMargins(22, 18, 22, 22)
        root.addWidget(self.pages)
        self.setCentralWidget(background)

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
        self.tray_menu.addAction("Открыть", self.show_window)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("Выход", self.quit_app)
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

        themes.changed.connect(self.on_theme_changed)
        self.refresh()

    # ---------- Страницы ----------

    def _build_main_page(self) -> QWidget:
        settings_button = _icon_button(GEAR_GLYPH, GEAR_FALLBACK, "Настройки")
        settings_button.clicked.connect(self.show_settings)

        logo = QLabel()
        logo.setFixedSize(40, 40)
        logo.setPixmap(make_icon().pixmap(40, 40))
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        subtitle = QLabel(f"v{__version__}  ·  выход из всех аккаунтов")
        subtitle.setObjectName("mono")
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(logo)
        header.addLayout(title_box, 1)
        header.addWidget(settings_button)

        # Карточка сессии: статус, пояснение, главная кнопка.
        self.status_pill = StatusPill()
        self.hero_text = QLabel()
        self.hero_text.setObjectName("muted")
        self.hero_text.setWordWrap(True)
        self.toggle_button = QPushButton()
        self.toggle_button.setObjectName("primary")
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.clicked.connect(self.toggle_session)

        hero = QFrame()
        hero.setObjectName("hero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(18, 16, 18, 18)
        hero_layout.setSpacing(12)
        hero_layout.addWidget(self.status_pill, 0, Qt.AlignmentFlag.AlignLeft)
        hero_layout.addWidget(self.hero_text)
        hero_layout.addSpacing(2)
        hero_layout.addWidget(self.toggle_button)

        # Что очищать.
        self.targets_counter = QLabel()
        self.targets_counter.setObjectName("mono")
        targets_header = QHBoxLayout()
        targets_header.addWidget(_section_label("Что очищать"))
        targets_header.addStretch(1)
        targets_header.addWidget(self.targets_counter)

        targets_grid = QGridLayout()
        targets_grid.setHorizontalSpacing(8)
        targets_grid.setVerticalSpacing(8)
        self.target_cards: dict[str, TargetCard] = {}
        icon_font = theme.fonts().icons
        installed = self.session.installed_targets()
        for index, target in enumerate(installed):
            card = TargetCard(target_icon(target, icon_font), target.name, target.hint)
            card.switch.setChecked(target.id not in self.settings.disabled_targets)
            card.switch.toggled.connect(self.on_targets_changed)
            # Последняя карточка без пары растягивается на всю ширину.
            span = 2 if index == len(installed) - 1 and index % 2 == 0 else 1
            targets_grid.addWidget(card, index // 2, index % 2, 1, span)
            self.target_cards[target.id] = card
        targets_grid.setColumnStretch(0, 1)
        targets_grid.setColumnStretch(1, 1)
        if not self.target_cards:
            empty = QLabel("Не найдено ни одной поддерживаемой программы")
            empty.setObjectName("muted")
            targets_grid.addWidget(empty, 0, 0)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addSpacing(20)
        layout.addWidget(hero)
        layout.addSpacing(24)
        layout.addLayout(targets_header)
        layout.addSpacing(10)
        layout.addLayout(targets_grid)
        layout.addStretch(1)
        return page

    def _build_settings_page(self) -> QWidget:
        back_button = _icon_button(BACK_GLYPH, BACK_FALLBACK, "Назад")
        back_button.clicked.connect(self.show_main)
        title = QLabel("Настройки")
        title.setObjectName("pageTitle")
        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(back_button)
        header.addWidget(title, 1)

        # Оформление.
        self.theme_buttons = QButtonGroup(self)
        theme_row = QHBoxLayout()
        theme_row.setSpacing(6)
        for choice, label in theme.CHOICES.items():
            button = QPushButton(label)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(choice == self.themes.choice)
            button.clicked.connect(lambda _checked, c=choice: self.on_theme_chosen(c))
            self.theme_buttons.addButton(button)
            theme_row.addWidget(button)
        theme_row.addStretch(1)
        theme_title = QLabel("Тема")
        theme_title.setObjectName("cardTitle")
        theme_card = QFrame()
        theme_card.setObjectName("hero")
        theme_layout = QVBoxLayout(theme_card)
        theme_layout.setContentsMargins(16, 12, 16, 14)
        theme_layout.setSpacing(10)
        theme_layout.addWidget(theme_title)
        theme_layout.addLayout(theme_row)

        # Сессия.
        self.shutdown_row = SettingRow(
            "Выходить из аккаунтов при выключении компьютера",
            "При выключении, перезагрузке или выходе из Windows сессия завершится сама. "
            "Если выключить — сессия продолжится после включения компьютера.",
        )
        self.shutdown_row.switch.setChecked(self.settings.logout_on_shutdown)
        self.shutdown_row.switch.toggled.connect(self.on_shutdown_option_changed)

        self.autostart_row = SettingRow(
            "Запускать вместе с Windows",
            "Программа сама появится в трее при входе в Windows: так она не пропустит "
            "выключение компьютера и дочистит сессию после сбоя.",
        )
        if autostart.is_supported():
            self.autostart_row.switch.setChecked(autostart.is_enabled())
        else:
            self.autostart_row.description_label.setText(
                "Доступно в установленной версии программы."
            )
            self.autostart_row.setEnabled(False)
        self.autostart_row.switch.toggled.connect(self.on_autostart_changed)

        # О программе.
        about = QFrame()
        about.setObjectName("hero")
        about_layout = QHBoxLayout(about)
        about_layout.setContentsMargins(16, 12, 16, 12)
        version = QLabel(f"{APP_NAME} {__version__}")
        version.setObjectName("cardTitle")
        about_layout.addWidget(version, 1)
        for text, handler in (
            ("GitHub ↗", lambda: QDesktopServices.openUrl(QUrl(REPO_URL))),
            ("Папка с логом ↗", self.open_app_folder),
        ):
            link = QPushButton(text)
            link.setObjectName("linkButton")
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.clicked.connect(handler)
            about_layout.addSpacing(12)
            about_layout.addWidget(link)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addSpacing(22)
        layout.addWidget(_section_label("Оформление"))
        layout.addSpacing(10)
        layout.addWidget(theme_card)
        layout.addSpacing(22)
        layout.addWidget(_section_label("Сессия"))
        layout.addSpacing(10)
        layout.addWidget(self.shutdown_row)
        layout.addSpacing(8)
        layout.addWidget(self.autostart_row)
        layout.addSpacing(22)
        layout.addWidget(_section_label("О программе"))
        layout.addSpacing(10)
        layout.addWidget(about)
        layout.addStretch(1)
        return page

    def show_settings(self) -> None:
        self.pages.setCurrentWidget(self.settings_page)

    def show_main(self) -> None:
        self.pages.setCurrentWidget(self.main_page)

    # ---------- Сессия ----------

    def selected_targets(self) -> list[Target]:
        """Что очищать в новой сессии: всё, кроме снятых галочек.

        Программы, которых на компьютере пока нет, тоже включены: если их
        установят и запустят во время сессии, следы тоже удалятся.
        """
        return [t for t in self.session.targets if t.id not in self.settings.disabled_targets]

    def toggle_session(self) -> None:
        if self.session.is_active:
            self.end_session()
        else:
            self.start_session()

    def start_session(self) -> None:
        targets = self.selected_targets()
        try:
            self.session.check_can_close(targets)
        except SessionError as error:
            QMessageBox.warning(self, APP_NAME, str(error))
            return

        running = self.session.running(targets)
        if running:
            names = ", ".join(t.name for t in running)
            answer = QMessageBox.question(
                self,
                "Нужно закрыть программы",
                f"Чтобы начать сессию, нужно закрыть: {names}.\n"
                "Несохранённое в них пропадёт.\n\n"
                "Закрыть и начать сессию?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.run_task("Сохраняю состояние…", lambda: self.session.start(targets, self.show_progress))

    def end_session(self, confirm: bool = True) -> bool:
        if confirm:
            text = (
                "Всё, что появилось за сессию (входы в аккаунты, пароли, история), "
                "будет удалено."
            )
            running = self.session.running(self.session.session_targets())
            if running:
                names = ", ".join(t.name for t in running)
                text += f"\n\nБудут закрыты: {names}. Несохранённое в них пропадёт."
            answer = QMessageBox.question(
                self,
                "Завершить сессию?",
                text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False

        return self.run_task("Выхожу из аккаунтов…", lambda: self.session.end(self.show_progress))

    def run_task(self, text: str, task: Callable[[], None]) -> bool:
        """Выполнить долгую операцию, показывая, что программа занята."""
        self._busy = True
        self.show_progress(text)
        self.toggle_button.setEnabled(False)
        self._set_targets_enabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            task()
            return True
        except Exception as error:
            log.exception("Ошибка при выполнении: %s", text)
            QMessageBox.critical(self, APP_NAME, str(error))
            return False
        finally:
            QApplication.restoreOverrideCursor()
            self.toggle_button.setEnabled(True)
            self._busy = False
            self.refresh()

    def show_progress(self, text: str) -> None:
        self.status_pill.set_status(theme.current().accent, text)
        QApplication.processEvents()

    def recover_after_restart(self) -> None:
        """Вызвать при запуске: компьютер могли выключить посреди сессии."""
        if not self.session.computer_restarted_since_start():
            return

        if not self.settings.logout_on_shutdown:
            log.info("Компьютер перезагружался, галочка выключена — сессия продолжается")
            self.session.adopt_current_boot()
            return

        log.info("Компьютер выключился посреди сессии — выхожу из аккаунтов сейчас")
        if self.end_session(confirm=False):
            QMessageBox.information(
                self,
                APP_NAME,
                "Компьютер выключился во время сессии, и программа не успела выйти "
                "из аккаунтов. Выход выполнен сейчас.",
            )

    def on_system_shutdown(self, _manager=None) -> None:
        if not self.session.is_active:
            return
        if not self.settings.logout_on_shutdown:
            log.info("Windows завершает работу, галочка выключена — сессия сохраняется")
            return

        log.info("Windows завершает работу — выхожу из аккаунтов")
        hwnd = int(self.winId())
        block_shutdown(hwnd, "Session Controller выходит из твоих аккаунтов…")
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

    def on_autostart_changed(self, checked: bool) -> None:
        try:
            autostart.set_enabled(checked)
        except OSError as error:
            log.exception("Не удалось изменить автозапуск")
            QMessageBox.warning(self, APP_NAME, f"Не удалось изменить автозапуск: {error}")
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
        t = theme.current()
        active = self.session.is_active
        if active:
            started = _format_time(self.session.started_at)
            duration = _format_duration(datetime.now() - self.session.started_at)
            status = f"Сессия идёт · {duration}"
            self.status_pill.set_status(t.green, status)
            text = f"Все входы в аккаунты с {started} удалятся, когда ты завершишь сессию"
            if self.settings.logout_on_shutdown:
                text += " или выключишь компьютер"
            self.hero_text.setText(text + ".")
            self.toggle_button.setText("Завершить сессию")
            self.tray_toggle_action.setText("Завершить сессию")
            tray_status = f"Сессия идёт с {started}"
        else:
            status = "Сессия не активна"
            self.status_pill.set_status(t.dim, status)
            self.hero_text.setText(
                "Начни сессию и работай как обычно: входи в аккаунты, закрывай и открывай "
                "программы. В конце одна кнопка — и на компьютере не останется твоих входов."
            )
            self.toggle_button.setText("Начать сессию")
            self.tray_toggle_action.setText("Начать сессию")
            tray_status = status

        # Главная кнопка: градиент — начать, контрастная — завершить.
        self.toggle_button.setProperty("inverse", active)
        self.toggle_button.style().unpolish(self.toggle_button)
        self.toggle_button.style().polish(self.toggle_button)

        # Во время сессии список не меняется: он был зафиксирован при старте.
        self._set_targets_enabled(not active)
        enabled = sum(card.switch.isChecked() for card in self.target_cards.values())
        if active:
            self.targets_counter.setText("зафиксировано на время сессии")
        else:
            self.targets_counter.setText(f"{enabled} из {len(self.target_cards)}")

        self.tray_status_action.setText(tray_status)
        self.tray.setToolTip(f"{APP_NAME}: {tray_status.lower()}")

    def _set_targets_enabled(self, enabled: bool) -> None:
        for card in self.target_cards.values():
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
            if not self._tray_hint_shown:
                text = "Программа работает здесь, в трее."
                if self.session.is_active:
                    text = "Сессия продолжается. " + text
                self.tray.showMessage(APP_NAME, text, make_icon())
                self._tray_hint_shown = True
        else:
            self.quit_app()

    def quit_app(self) -> None:
        if self.session.is_active:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("Сессия ещё идёт")
            box.setText("Завершить сессию перед выходом?")
            box.setInformativeText(
                "Если не завершать, твои аккаунты останутся на компьютере, а выход "
                "при выключении не сработает, пока Session Controller закрыт."
            )
            end_button = box.addButton("Завершить и выйти", QMessageBox.ButtonRole.YesRole)
            keep_button = box.addButton("Выйти без завершения", QMessageBox.ButtonRole.NoRole)
            box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
            box.exec()

            clicked = box.clickedButton()
            if clicked == end_button:
                if not self.end_session(confirm=False):
                    return
            elif clicked != keep_button:
                return

        self._user_quit = True
        self.tray.hide()
        QApplication.quit()


def _section_label(text: str) -> QLabel:
    """Подпись раздела, как «BACKEND» на сайте: моноширинный шрифт, капс."""
    label = QLabel(text.upper())
    label.setObjectName("section")
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


def _format_duration(elapsed) -> str:
    minutes = int(elapsed.total_seconds() // 60)
    if minutes < 1:
        return "меньше минуты"
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч"
    return f"{minutes} мин"


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

    # Две копии программы одновременно будут мешать друг другу.
    lock = QLockFile(str(home / "app.lock"))
    if not lock.tryLock(100):
        if not _show_running_instance():
            QMessageBox.information(
                None, APP_NAME, "Session Controller уже запущен — его значок в трее, возле часов."
            )
        return 0
    create_app_mutex(APP_MUTEX)
    if autostart.is_supported():
        autostart.refresh_path()

    settings_path = home / "settings.json"
    settings = Settings.load(settings_path)
    # При первом запуске тема «как в системе», дальше — как выбрал пользователь.
    themes = theme.ThemeManager(app, settings.theme)
    session = Session(home, known_targets())
    session.load()

    window = MainWindow(session, settings, settings_path, themes)
    if minimized and QSystemTrayIcon.isSystemTrayAvailable():
        # Окно всё равно создаём: через него Windows сообщает о выключении.
        window.winId()
    else:
        window.show()
    QTimer.singleShot(0, window.recover_after_restart)

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
