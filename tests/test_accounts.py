"""Проверка настоящих HTTP-запросов из окна и изоляции двух аккаунтов."""

import json
import socket
import sys
from threading import Thread
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Сохранённый вход защищает Windows DPAPI")
def test_account_client_and_account_isolation(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    uvicorn = pytest.importorskip("uvicorn")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from server.accounts import create_app
    from session_controller import app, theme
    from session_controller.account_storage import SavedAccount
    from session_controller.account_page import AccountPage, EntryEditor
    from session_controller.session import Session
    from session_controller.settings import Settings
    from session_controller.targets import ACCOUNT_TARGET

    db = tmp_path / "accounts.sqlite3"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        address = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(create_app(db), log_level="warning"))
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()

        def wait_until(check):
            deadline = monotonic() + 8
            while not check() and monotonic() < deadline:
                qt.processEvents()
                sleep(0.01)
            assert check()

        def api(method, path, body=None, token=None):
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            data = json.dumps(body).encode() if body is not None else None
            with urlopen(Request(address + path, data=data, headers=headers, method=method), timeout=5) as reply:
                raw = reply.read()
                return json.loads(raw) if raw else None

        qt = QApplication.instance() or QApplication([])
        storage = SavedAccount(tmp_path)
        window = AccountPage(None, address, storage)
        window.show()
        main_window = None
        try:
            wait_until(lambda: server.started)
            window.activate()
            wait_until(lambda: window.reply is None)
            assert window.status.text() == ""
            password = "test-pass-123"
            window.login.setText("student")
            window.password.setText(password)
            window.register()
            wait_until(lambda: bool(window.identity.text()))
            assert storage.load(address) == window.token
            assert storage.load("https://another-server.example") == ""
            assert window.token.encode() not in storage.path.read_bytes()
            monkeypatch.setattr(app.dialogs, "confirm", lambda *_args, **_kw: False)
            window.confirm_sign_out()
            assert window.token == storage.load(address)
            window.edit_profile()
            window.name.setText("Черновик")
            window.cancel_edit()
            window.edit_profile()
            assert window.name.text() == window.identity.text() == "student"
            window.name.setText("Учебный профиль")
            window.save_profile()
            wait_until(lambda: window.identity.text() == "Учебный профиль")
            assert window.profile_stack.currentIndex() == 0
            assert api("GET", "/profile", token=window.token)["name"] == "Учебный профиль"

            editor = EntryEditor(window)
            assert editor.minimumSize() == editor.maximumSize()
            editor.service.setText("Учебный GitHub")
            editor.add_field("Почта", "student@example.test")
            editor.save()
            window.tab_changed("entries")
            wait_until(lambda: window.controls.isEnabled())
            window.request("POST", "/entries", lambda _: window.load_entries(), editor.result_data)
            wait_until(lambda: window.entries.count() == 1)
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            viewport = window.entries.viewport()
            hit = window.entries.visualItemRect(window.entries.item(0)).center()
            QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=hit)
            assert window.entries.selectedItems()
            QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=viewport.rect().bottomRight())
            assert not window.entries.selectedItems()
            QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=hit)
            QTest.mouseClick(window.picker.buttons["profile"], Qt.MouseButton.LeftButton)
            assert window.entries.currentRow() == -1
            editor.deleteLater()

            entry = api("GET", "/entries", token=window.token)[0]
            assert entry["service"] == "Учебный GitHub"
            path = "/entries/" + entry["id"]
            original = api("GET", path, token=window.token)
            assert original["fields"][2]["label"] == "Почта"
            api("PUT", path, {**original, "service": "Обновлённая запись"}, window.token)
            assert api("GET", path, token=window.token)["service"] == "Обновлённая запись"

            second = {"login": "student2", "password": password}
            api("POST", "/register", second)
            with pytest.raises(HTTPError, match="409"):
                api("POST", "/register", second)
            other_token = api("POST", "/login", second)["token"]
            assert api("GET", "/entries", token=other_token) == []
            with pytest.raises(HTTPError, match="404"):
                api("GET", path, token=other_token)

            token = window.token
            api("DELETE", path, token=token)
            window.hide()
            monkeypatch.setattr(app, "INSTANCE_SERVER", str(uuid4()))
            session = Session(tmp_path / "session", [ACCOUNT_TARGET])
            main_window = app.MainWindow(
                session, Settings(account_server_url=address), tmp_path / "settings.json",
                theme.ThemeManager(qt, "dark"),
            )
            main_window.show()
            account = main_window.account
            assert account.token == token
            wait_until(lambda: bool(account.identity.text()))
            main_window.account_button.click()
            assert main_window.pages.currentWidget() is main_window.account_page
            main_window.show_main()
            assert account.token == token
            assert ACCOUNT_TARGET.id in main_window.overlay_cards
            session.start([ACCOUNT_TARGET])
            main_window.end_session(confirm=False)
            wait_until(lambda: not main_window._busy)
            assert not session.is_active and not account.token and not storage.path.exists()

            def token_revoked():
                try:
                    api("GET", "/entries", token=token)
                except HTTPError as error:
                    assert error.code == 401
                    return True
                return False

            wait_until(token_revoked)
        finally:
            if main_window is not None:
                main_window.instance_server.close()
                main_window.tray.hide()
                main_window.hide()
                main_window.deleteLater()
            window.close()
            server.should_exit = True
            thread.join(timeout=5)


def test_existing_data_and_default_server_address(tmp_path, monkeypatch):
    from session_controller.account_storage import ACCOUNT_SERVER, server_address
    from session_controller.paths import app_home

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("SESSION_CONTROLLER_HOME", raising=False)
    home = app_home()
    assert home == tmp_path / "SessionController"
    assert server_address(home) == ACCOUNT_SERVER
    assert not (home / "server.txt").exists()
    previous = tmp_path / "SessionControllerCollege"
    previous.mkdir()
    (previous / "account.dat").touch()
    (previous / "server.txt").write_text("http://127.0.0.1:8000", encoding="utf-8")
    assert app_home() == previous
    assert server_address(previous) == "http://127.0.0.1:8000"


def test_existing_server_database_is_reused(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from server.accounts import database_path

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("SC_ACCOUNT_DB", raising=False)
    monkeypatch.delenv("SC_DEMO_DB", raising=False)
    assert database_path() == tmp_path / "SessionControllerAccounts/accounts.sqlite3"
    previous = tmp_path / "SessionControllerDemo/demo.sqlite3"
    previous.parent.mkdir()
    previous.touch()
    assert database_path() == previous
