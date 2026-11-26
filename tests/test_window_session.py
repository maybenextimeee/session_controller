"""Регрессии главного окна. Сессия затрагивает только временный профиль."""
from uuid import uuid4

import pytest

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QPushButton

from session_controller import app as ui, theme
from session_controller.session import Session
from session_controller.settings import Settings
from session_controller.targets import Target
from session_controller.widgets import SessionButton


def test_window_survives_start_and_end(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "INSTANCE_SERVER", str(uuid4()))
    profile = tmp_path / "demo"
    profile.mkdir()
    target = Target("demo", "Demo", paths=(profile,))
    missing = Target("clash_verge", "Clash Verge", paths=(tmp_path / "absent",))
    unchecked_profile = tmp_path / "unchecked"
    unchecked_profile.mkdir()
    unchecked = Target("unchecked", "Unchecked", paths=(unchecked_profile,))
    settings = Settings(disabled_targets=[unchecked.id], pinned_targets=[])
    window = ui.MainWindow(Session(tmp_path / "state", [target, missing, unchecked]), settings,
                           tmp_path / "settings.json", theme.ThemeManager(app, "dark"))
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.show()

    def wait_for_session():
        loop = QEventLoop()
        timer = QTimer(loop)
        timer.timeout.connect(lambda: None if window._busy else loop.quit())
        timer.start(10)
        QTimer.singleShot(5000, loop, loop.quit)
        loop.exec()
        assert not window._busy and window.isVisible()

    try:
        assert window.minimumSize() == window.maximumSize()
        monkeypatch.setattr(ui, "__version__", "0.8.0")
        for version in ("0.8.1", "0.7.1", "0.8"):
            window.on_update_found(version, "https://example.test/release")
            assert window.update_button.isHidden() == (version == "0.8")
            if version != "0.8":
                assert version in window.update_button.text()
        window.show_all_programs()
        QTest.qWait(340)
        pin = window.pin_buttons["demo"][1]
        pin.click()
        row = window.home_rows["demo"]
        row.motion.setCurrentTime(row.motion.duration() // 2)
        assert 0 < row.height() < row.content.height()
        mid_height = row.height()
        pin.click()
        assert row.height() == mid_height
        pin.click()
        assert row.height() == mid_height
        assert QSignalSpy(row.motion.finished).wait(1500)
        assert row.progress == 1
        assert not row.isHidden()
        window.apps_overlay.close_overlay()
        QTest.qWait(220)
        window.pin_buttons["demo"][0].click()
        assert QSignalSpy(row.motion.finished).wait(1500)
        assert row.isHidden()
        assert window.empty_pins.isVisible()
        window.show_settings()
        QTest.qWait(200)
        window.show_main()
        QTest.qWait(200)

        window.session_button.click()
        wait_for_session()
        assert window.session.is_active
        assert [t.id for t in window.session.session_targets()] == [target.id]
        missing.paths[0].mkdir()
        for folder in (missing.paths[0], unchecked_profile):
            (folder / "keep").touch()
        assert window.session_button._subtitle.startswith("С ")
        new_file = profile / "session-only"
        new_file.touch()

        def confirm():
            button = app.activeModalWidget().findChild(QPushButton, "dialogPrimary")
            button.click()

        QTimer.singleShot(20, confirm)
        window.session_button.click()
        wait_for_session()
        assert not window.session.is_active and not new_file.exists()
        assert all((folder / "keep").exists() for folder in (missing.paths[0], unchecked_profile))
    finally:
        window.instance_server.close()
        window.tray.hide()
        window.hide()
        window.deleteLater()
        app.processEvents()


def test_end_session_context_menu_keeps_apps_and_logins(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "INSTANCE_SERVER", str(uuid4()))
    profile = tmp_path / "profile"
    profile.write_text("before")
    target = Target("example", "Example", paths=(profile,))
    session = Session(tmp_path / "state", [target])
    window = ui.MainWindow(session, Settings(), tmp_path / "settings.json",
                           theme.ThemeManager(app, "dark"))
    session.start([target])
    profile.write_text("during")
    window.refresh()
    def choose_keep():
        button.customContextMenuRequested.emit(button.rect().center())
        menu = app.activePopupWidget()
        assert isinstance(menu, ui.QMenu)
        assert [action.text() for action in menu.actions()] == [
            ui.tr("Завершить сессию"), ui.tr("Завершить без выхода из аккаунтов")]
        menu.setActiveAction(menu.actions()[1])
        QTest.keyClick(menu, Qt.Key.Key_Return)

    monkeypatch.setattr(window, "sign_out_session_account", lambda: pytest.fail("unexpected logout"))
    monkeypatch.setattr(ui.Session, "end", lambda *_: pytest.fail("unexpected cleanup"))
    button = window.session_button
    try:
        monkeypatch.setattr(ui.dialogs, "confirm", lambda *_: False)
        choose_keep()
        assert session.is_active and not window._busy
        monkeypatch.setattr(ui.dialogs, "confirm", lambda *_: True)
        choose_keep()
        for _ in range(250):
            if not window._busy:
                break
            QTest.qWait(20)
        assert not window._busy and not session.is_active
        assert profile.read_text() == "during"
        assert not session.journal_path.exists() and not session.backup_root.exists()
        reloaded = Session(session.home, [target])
        reloaded.load()
        assert not reloaded.is_active
        assert button.text() == ui.tr("Начать сессию")
    finally:
        window.instance_server.close()
        window.tray.hide()
        window.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("palette", [theme.DARK_THEME, theme.LIGHT_THEME])
def test_session_button_paints_start_transition(monkeypatch, palette):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(theme, "_current", palette)
    button = SessionButton()
    button.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    button.resize(320, button.HEIGHT)
    button.show()
    app.processEvents()

    def colors():
        image = button.grab().toImage()
        return [image.pixelColor(x, 12).name() for x in (20, image.width() - 20)]

    try:
        idle = colors()
        button.set_state(button.BUSY, "Starting")
        button.set_state(button.STOP, "End", "Since 12:00")
        motion = button._color_change
        assert motion.duration() == 120
        motion.setCurrentTime(motion.duration() // 2)
        left, right = colors()
        assert left == right
        assert left not in (idle[0], palette.bg)
        button.set_state(button.STOP, "End", "Since 12:00")
        assert motion.currentTime() == motion.duration() // 2
        motion.setCurrentTime(motion.duration())
        assert colors() == [palette.bg, palette.bg]
        image = button.grab().toImage()
        assert image.pixelColor(image.width() // 2, 1).name() == "#ffffff"
        assert any(image.pixelColor(x, y).name() == palette.text
                   for x in range(image.width() // 2 - 25, image.width() // 2 + 25)
                   for y in range(10, 34))
        button.set_state(button.BUSY, "Ending")
        button.set_state(button.START, "Start")
        motion.setCurrentTime(motion.duration())
        assert colors() == idle
        button.set_state(button.STOP, "Restored")
        assert colors() == [palette.bg, palette.bg]
    finally:
        button.close()


def test_only_pinned_rows_scroll(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "INSTANCE_SERVER", str(uuid4()))
    targets = [Target(str(i), str(i), paths=(tmp_path,)) for i in range(18)]
    window = ui.MainWindow(Session(tmp_path / "state", targets),
                           Settings(pinned_targets=[t.id for t in targets]),
                           tmp_path / "settings.json", theme.ThemeManager(app, "dark"))
    window.show()
    try:
        app.processEvents()
        heading = window.main_page.findChild(ui.QLabel, "homeHeading")
        catalog = window.main_page.findChild(QPushButton, "moreButton")
        fixed = [window.account_button, heading, catalog, window.session_button]
        def y(widget):
            return widget.mapToGlobal(widget.rect().topLeft()).y()

        before = [y(widget) for widget in fixed]
        first = window.home_rows["0"]
        top = y(first)
        bar = window.main_scroll.verticalScrollBar()
        assert bar.maximum() > 0
        bar.setValue(bar.maximum())
        app.processEvents()
        assert y(first) < top
        assert [y(widget) for widget in fixed] == before
    finally:
        window.instance_server.close()
        window.tray.hide()
        window.hide()
        window.deleteLater()
        app.processEvents()


def test_drag_pin_persists_order_without_unpinning(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "INSTANCE_SERVER", str(uuid4()))
    targets = [Target(key, key.upper(), paths=(tmp_path,)) for key in ("a", "b", "c")]
    settings = Settings(pinned_targets=["a", "b", "c"])
    settings_path = tmp_path / "settings.json"
    window = ui.MainWindow(Session(tmp_path / "state", targets), settings, settings_path,
                           theme.ThemeManager(app, "dark"))
    window.show()
    try:
        QTest.qWait(40)
        handle = window.pin_buttons["a"][0]
        start = handle.rect().center()
        last = window.home_rows["c"]
        end = handle.mapFromGlobal(last.mapToGlobal(last.rect().bottomRight()))
        QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=start)
        layer = window.pin_drag_layer
        assert handle.cursor().shape() == Qt.CursorShape.ArrowCursor
        assert layer is not None
        layer.motion.setCurrentTime(75)
        assert .96 < layer.scale() < 1.
        QTest.mouseMove(handle, end)
        assert layer.start["b"] != layer.dest["b"]
        QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=start)
        assert handle.isChecked()
        assert settings.pinned_targets == ["b", "c", "a"]
        assert Settings.load(settings_path).pinned_targets == ["b", "c", "a"]
        QTest.mouseClick(handle, Qt.MouseButton.LeftButton)
        assert settings.pinned_targets == ["b", "c"]
        QTest.qWait(310)
        card = window.target_cards["b"]
        destination = window.home_rows["c"]
        end = card.mapFromGlobal(destination.mapToGlobal(destination.rect().bottomRight()))
        QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=card.rect().center())
        QTest.mouseMove(card, end)
        QTest.mouseRelease(card, Qt.MouseButton.LeftButton)
        assert settings.pinned_targets == ["c", "b"]
        popup = ui.dialogs.Dialog(window, "Выйти?", "Для входа нужен пароль.",
                                  [ui.dialogs.Button("ok", "Выйти")])
        assert popup.minimumSize() == popup.maximumSize()
        popup.deleteLater()
    finally:
        window.instance_server.close()
        window.tray.hide()
        window.hide()
        window.deleteLater()
        app.processEvents()
