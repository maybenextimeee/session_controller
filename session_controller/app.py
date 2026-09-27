"""Главное окно Session Controller."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from session_controller import __version__
from session_controller.session import Session


class MainWindow(QMainWindow):
    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session

        self.setWindowTitle(f"Session Controller {__version__}")
        self.setMinimumSize(360, 200)

        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.toggle_button = QPushButton()
        self.toggle_button.setMinimumHeight(48)
        self.toggle_button.clicked.connect(self.toggle_session)

        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        layout.addWidget(self.toggle_button)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.refresh()

    def toggle_session(self) -> None:
        if self.session.is_active:
            self.session.end()
        else:
            self.session.start()
        self.refresh()

    def refresh(self) -> None:
        """Обновить надписи под текущее состояние сессии."""
        if self.session.is_active:
            started = self.session.started_at.strftime("%H:%M")
            self.status_label.setText(f"Сессия активна с {started}")
            self.toggle_button.setText("Завершить сессию")
        else:
            self.status_label.setText("Сессия не активна")
            self.toggle_button.setText("Начать сессию")

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self.session.is_active:
            event.accept()
            return

        answer = QMessageBox.question(
            self,
            "Сессия ещё идёт",
            "Завершить сессию и выйти из всех аккаунтов перед закрытием?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.session.end()
            event.accept()
        else:
            event.ignore()


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow(Session())
    window.show()
    return app.exec()
