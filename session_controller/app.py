"""Главное окно Session Controller и значок в трее."""

import getpass
import logging
import sys
from collections.abc import Callable
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPixmap,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from session_controller import __version__, autostart
from session_controller.paths import app_home
from session_controller.session import Session, SessionError
from session_controller.settings import Settings
from session_controller.targets import Target, known_targets
from session_controller.winapi import block_shutdown, create_app_mutex, unblock_shutdown

log = logging.getLogger(__name__)

APP_NAME = "Session Controller"
# По этому имени установщик понимает, что программа запущена (AppMutex в installer.iss).
APP_MUTEX = "SessionControllerMutex"
# Через этот канал вторая копия программы просит первую показать окно.
INSTANCE_SERVER = f"SessionController-{getpass.getuser()}"

BLUE = "#1e88e5"
BLUE_DARK = "#1565c0"
BLUE_LIGHT = "#42a5f5"
GREEN = "#2e9e44"
GRAY = "#9e9e9e"

STYLE = f"""
QLabel#title {{
    color: {BLUE};
    font-size: 16pt;
    font-weight: 700;
}}
QPushButton#primary {{
    background-color: {BLUE};
    color: white;
    border: none;
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 11pt;
    font-weight: 600;
}}
QPushButton#primary:hover {{ background-color: #1976d2; }}
QPushButton#primary:pressed {{ background-color: {BLUE_DARK}; }}
QPushButton#primary:disabled {{ background-color: #90caf9; }}
QGroupBox {{
    border: 1px solid #90caf9;
    border-radius: 8px;
    margin-top: 14px;
    padding: 10px 8px 6px 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    color: {BLUE};
    font-weight: 600;
}}
"""


class MainWindow(QMainWindow):
    def __init__(self, session: Session, settings: Settings, settings_path: Path) -> None:
        super().__init__()
        self.session = session
        self.settings = settings
        self.settings_path = settings_path
        self._user_quit = False
        self._tray_hint_shown = False

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(make_icon())
        self.setMinimumWidth(460)

        title = QLabel(APP_NAME)
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setTextFormat(Qt.TextFormat.RichText)

        self.toggle_button = QPushButton()
        self.toggle_button.setObjectName("primary")
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.clicked.connect(self.toggle_session)

        self.targets_box = QGroupBox("Что очищать")
        targets_layout = QGridLayout(self.targets_box)
        self.target_checkboxes: dict[str, QCheckBox] = {}
        for index, target in enumerate(session.installed_targets()):
            checkbox = QCheckBox(target.name)
            checkbox.setToolTip(target.hint)
            checkbox.setChecked(target.id not in settings.disabled_targets)
            checkbox.toggled.connect(self.on_targets_changed)
            targets_layout.addWidget(checkbox, index // 2, index % 2)
            self.target_checkboxes[target.id] = checkbox
        if not self.target_checkboxes:
            targets_layout.addWidget(QLabel("Не найдено ни одной поддерживаемой программы"))

        self.shutdown_checkbox = QCheckBox("Выходить из аккаунтов при выключении компьютера")
        self.shutdown_checkbox.setToolTip(
            "Если галочка стоит, при выключении, перезагрузке или выходе из Windows\n"
            "сессия завершится автоматически.\n"
            "Если нет — сессия продолжится после включения компьютера."
        )
        self.shutdown_checkbox.setChecked(settings.logout_on_shutdown)
        self.shutdown_checkbox.toggled.connect(self.on_shutdown_option_changed)

        self.autostart_checkbox = QCheckBox("Запускать вместе с Windows")
        if autostart.is_supported():
            self.autostart_checkbox.setChecked(autostart.is_enabled())
            self.autostart_checkbox.setToolTip(
                "Программа будет сама запускаться в трее при входе в Windows.\n"
                "Так она не пропустит выключение компьютера и дочистит сессию после сбоя."
            )
        else:
            self.autostart_checkbox.setEnabled(False)
            self.autostart_checkbox.setToolTip("Доступно в установленной версии программы")
        self.autostart_checkbox.toggled.connect(self.on_autostart_changed)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(self.status_label)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.targets_box)
        layout.addWidget(self.shutdown_checkbox)
        layout.addWidget(self.autostart_checkbox)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray_menu = QMenu()
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

        self.refresh()

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
        self.show_progress(text)
        self.toggle_button.setEnabled(False)
        self.targets_box.setEnabled(False)
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
            self.refresh()

    def show_progress(self, text: str) -> None:
        self.status_label.setText(_status_html(BLUE, text))
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

    def on_shutdown_option_changed(self, checked: bool) -> None:
        self.settings.logout_on_shutdown = checked
        self.settings.save(self.settings_path)
        log.info("Выход при выключении: %s", "да" if checked else "нет")

    def on_autostart_changed(self, checked: bool) -> None:
        try:
            autostart.set_enabled(checked)
        except OSError as error:
            log.exception("Не удалось изменить автозапуск")
            QMessageBox.warning(self, APP_NAME, f"Не удалось изменить автозапуск: {error}")
            return
        log.info("Автозапуск: %s", "да" if checked else "нет")

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
            target_id for target_id, checkbox in self.target_checkboxes.items()
            if not checkbox.isChecked()
        ]
        self.settings.save(self.settings_path)

    # ---------- Окно и трей ----------

    def refresh(self) -> None:
        """Обновить надписи под текущее состояние сессии."""
        if self.session.is_active:
            started = _format_time(self.session.started_at)
            status = f"Сессия активна с {started}"
            self.status_label.setText(_status_html(GREEN, status))
            self.toggle_button.setText("Завершить сессию")
            self.tray_toggle_action.setText("Завершить сессию")
        else:
            status = "Сессия не активна"
            self.status_label.setText(_status_html(GRAY, status))
            self.toggle_button.setText("Начать сессию")
            self.tray_toggle_action.setText("Начать сессию")

        # Во время сессии список не меняется: он был зафиксирован при старте.
        self.targets_box.setEnabled(not self.session.is_active)
        self.tray_status_action.setText(status)
        self.tray.setToolTip(f"{APP_NAME}: {status.lower()}")

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


_icon: QIcon | None = None


def make_icon() -> QIcon:
    """Значок программы: голубой квадрат со скруглёнными углами и буквами SC."""
    global _icon
    if _icon is not None:
        return _icon

    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0, QColor(BLUE_LIGHT))
    gradient.setColorAt(1, QColor(BLUE_DARK))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(QRectF(8, 8, size - 16, size - 16), 56, 56)

    font = QFont("Segoe UI")
    font.setBold(True)
    font.setPixelSize(int(size * 0.42))
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "SC")
    painter.end()

    _icon = QIcon(pixmap)
    return _icon


def _status_html(color: str, text: str) -> str:
    return (
        f'<span style="color:{color}; font-size:15pt;">●</span>'
        f'&nbsp;<span style="font-size:12pt; font-weight:600;">{text}</span>'
    )


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
    app.setStyleSheet(STYLE)
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
    session = Session(home, known_targets())
    session.load()

    window = MainWindow(session, settings, settings_path)
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
