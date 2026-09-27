"""Главное окно Session Controller и значок в трее."""

import logging
import sys
from collections.abc import Callable
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from session_controller import __version__
from session_controller.browsers import known_browsers
from session_controller.paths import app_home
from session_controller.session import Session
from session_controller.settings import Settings
from session_controller.winapi import block_shutdown, unblock_shutdown

log = logging.getLogger(__name__)

APP_NAME = "Session Controller"


class MainWindow(QMainWindow):
    def __init__(self, session: Session, settings: Settings, settings_path: Path) -> None:
        super().__init__()
        self.session = session
        self.settings = settings
        self.settings_path = settings_path
        self._user_quit = False
        self._tray_hint_shown = False

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setMinimumSize(420, 240)

        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_font = self.status_label.font()
        status_font.setPointSize(status_font.pointSize() + 4)
        status_font.setBold(True)
        self.status_label.setFont(status_font)

        self.browsers_label = QLabel()
        self.browsers_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.browsers_label.setWordWrap(True)
        self.browsers_label.setStyleSheet("color: gray;")

        self.toggle_button = QPushButton()
        self.toggle_button.setMinimumHeight(48)
        self.toggle_button.clicked.connect(self.toggle_session)

        self.shutdown_checkbox = QCheckBox("Выходить из аккаунтов при выключении компьютера")
        self.shutdown_checkbox.setToolTip(
            "Если галочка стоит, при выключении, перезагрузке или выходе из Windows\n"
            "сессия завершится автоматически.\n"
            "Если нет — сессия продолжится после включения компьютера."
        )
        self.shutdown_checkbox.setChecked(settings.logout_on_shutdown)
        self.shutdown_checkbox.toggled.connect(self.on_shutdown_option_changed)

        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        layout.addWidget(self.browsers_label)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.shutdown_checkbox)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.tray = QSystemTrayIcon(self)
        self.tray_menu = QMenu()
        self.tray_menu.addAction("Открыть", self.show_window)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("Выход", self.quit_app)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self.on_tray_activated)

        app = QApplication.instance()
        # Windows спрашивает программы, можно ли выключаться (WM_QUERYENDSESSION).
        app.commitDataRequest.connect(self.on_system_shutdown)
        # Запасной вариант: программу закрывают не по нашей кнопке «Выход».
        app.aboutToQuit.connect(self.on_about_to_quit)

        self.refresh()
        self.tray.show()

    # ---------- Сессия ----------

    def toggle_session(self) -> None:
        if self.session.is_active:
            self.end_session()
        else:
            self.start_session()

    def start_session(self) -> None:
        running = self.session.running_browsers()
        if running:
            names = ", ".join(b.name for b in running)
            answer = QMessageBox.question(
                self,
                "Нужно закрыть браузеры",
                f"Чтобы начать сессию, нужно закрыть: {names}.\n"
                "Несохранённое на открытых вкладках пропадёт.\n\n"
                "Закрыть и начать сессию?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.run_task("Сохраняю состояние браузеров…", self.session.start)

    def end_session(self, confirm: bool = True) -> bool:
        if confirm:
            answer = QMessageBox.question(
                self,
                "Завершить сессию?",
                "Браузеры будут закрыты, а всё, что появилось в них за сессию "
                "(входы в аккаунты, пароли, история), будет удалено.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False

        return self.run_task("Выхожу из аккаунтов…", self.session.end)

    def run_task(self, text: str, task: Callable[[], None]) -> bool:
        """Выполнить долгую операцию, показывая, что программа занята."""
        self.status_label.setText(text)
        self.toggle_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
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

    def recover_after_restart(self) -> None:
        """Вызвать при запуске: компьютер могли выключить посреди сессии."""
        if not self.session.computer_restarted_since_start():
            return

        if not self.settings.logout_on_shutdown:
            log.info("Компьютер перезагружался, галочка выключена — сессия продолжается")
            self.session.adopt_current_boot()
            return

        log.info("Компьютер выключился посреди сессии — выхожу из аккаунтов сейчас")
        if self.run_task("Выхожу из аккаунтов…", self.session.end):
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

    # ---------- Окно и трей ----------

    def refresh(self) -> None:
        """Обновить надписи и значок под текущее состояние сессии."""
        if self.session.is_active:
            started = _format_time(self.session.started_at)
            self.status_label.setText(f"Сессия активна с {started}")
            self.toggle_button.setText("Завершить сессию")
            self.tray.setToolTip(f"{APP_NAME}: сессия активна с {started}")
        else:
            self.status_label.setText("Сессия не активна")
            self.toggle_button.setText("Начать сессию")
            self.tray.setToolTip(f"{APP_NAME}: сессия не активна")

        installed = self.session.installed_browsers()
        if installed:
            names = ", ".join(b.name for b in installed)
            self.browsers_label.setText(f"Браузеры на этом компьютере: {names}")
        else:
            self.browsers_label.setText("Браузеры не найдены")

        icon = make_icon(self.session.is_active)
        self.setWindowIcon(icon)
        self.tray.setIcon(icon)

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
        if self.session.is_active and QSystemTrayIcon.isSystemTrayAvailable():
            # Пока идёт сессия, программа должна работать, чтобы поймать выключение.
            self.hide()
            if not self._tray_hint_shown:
                self.tray.showMessage(
                    APP_NAME,
                    "Сессия продолжается. Программа работает здесь, в трее.",
                    QSystemTrayIcon.MessageIcon.Information,
                )
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


def make_icon(active: bool) -> QIcon:
    """Значок: зелёный кружок — сессия идёт, серый — нет."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#2e7d32" if active else "#8a8a8a"))
    painter.drawEllipse(2, 2, 60, 60)
    painter.setPen(QColor("white"))
    painter.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "SC")
    painter.end()

    return QIcon(pixmap)


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
    home = app_home()
    setup_logging(home)
    log.info("Запуск %s %s", APP_NAME, __version__)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # Закрытие окна не должно завершать программу: она живёт в трее.
    app.setQuitOnLastWindowClosed(False)

    # Две копии программы одновременно будут мешать друг другу.
    lock = QLockFile(str(home / "app.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(
            None, APP_NAME, "Session Controller уже запущен — его значок в трее, возле часов."
        )
        return 0

    settings_path = home / "settings.json"
    settings = Settings.load(settings_path)
    session = Session(home, known_browsers())
    session.load()

    window = MainWindow(session, settings, settings_path)
    window.show()
    QTimer.singleShot(0, window.recover_after_restart)

    return app.exec()
