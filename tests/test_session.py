"""Тесты движка сессии на ненастоящем «браузере» во временной папке.

Запуск: python -m pytest
"""

from pathlib import Path

import pytest

from session_controller import session as session_mod
from session_controller import snapshot
from session_controller.browsers import Browser
from session_controller.session import Session, SessionError
from session_controller.settings import Settings


def make_browser(root: Path, name: str = "fake") -> Browser:
    return Browser(
        id=name,
        name=name.title(),
        data_dir=root / name / "User Data",
        process_names=("sc-test-no-such-process.exe",),
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "app"


@pytest.fixture
def browser(tmp_path: Path) -> Browser:
    browser = make_browser(tmp_path / "browsers")
    write(browser.data_dir / "Local State", "state before")
    write(browser.data_dir / "Default" / "Network" / "Cookies", "cookies before")
    write(browser.data_dir / "Default" / "Cache" / "data_0", "cache")
    return browser


def test_end_returns_browser_to_state_before_session(home, browser):
    session = Session(home, [browser])
    session.start()
    assert session.is_active

    # Во время сессии человек вошёл в аккаунты и создал новый профиль.
    write(browser.data_dir / "Default" / "Network" / "Cookies", "logged in")
    write(browser.data_dir / "Default" / "Login Data", "saved password")
    write(browser.data_dir / "Profile 1" / "Preferences", "new profile")

    session.end()

    data = browser.data_dir
    assert (data / "Default" / "Network" / "Cookies").read_text(encoding="utf-8") == "cookies before"
    assert (data / "Local State").read_text(encoding="utf-8") == "state before"
    assert not (data / "Default" / "Login Data").exists()
    assert not (data / "Profile 1").exists()
    assert not (data / "Default" / "Cache").exists()  # кэш не копируется
    assert not session.is_active
    assert not session.journal_path.exists()
    assert not session.backup_root.exists()
    assert not list(data.parent.glob(snapshot.TRASH_PREFIX + "*"))


def test_browser_first_opened_during_session_is_removed(home, tmp_path):
    browser = make_browser(tmp_path / "browsers")
    session = Session(home, [browser])
    session.start()

    write(browser.data_dir / "Default" / "Network" / "Cookies", "logged in")
    session.end()

    assert not browser.data_dir.exists()


def test_session_survives_program_restart(home, browser):
    Session(home, [browser]).start()
    write(browser.data_dir / "Default" / "Network" / "Cookies", "logged in")

    restarted = Session(home, [browser])
    restarted.load()
    assert restarted.is_active

    restarted.end()
    cookies = browser.data_dir / "Default" / "Network" / "Cookies"
    assert cookies.read_text(encoding="utf-8") == "cookies before"


def test_failed_end_keeps_session_and_can_be_retried(home, browser, monkeypatch):
    session = Session(home, [browser])
    session.start()
    write(browser.data_dir / "Default" / "Network" / "Cookies", "logged in")

    def broken_restore(*_args):
        raise PermissionError("файл занят")

    with monkeypatch.context() as patch:
        patch.setattr(snapshot, "restore", broken_restore)
        with pytest.raises(SessionError):
            session.end()

    assert session.is_active
    assert session.journal_path.exists()

    session.end()
    cookies = browser.data_dir / "Default" / "Network" / "Cookies"
    assert cookies.read_text(encoding="utf-8") == "cookies before"


def test_start_twice_is_an_error(home, browser):
    session = Session(home, [browser])
    session.start()
    with pytest.raises(SessionError):
        session.start()


def test_restart_detection(home, browser, monkeypatch):
    session = Session(home, [browser])
    session.start()
    assert not session.computer_restarted_since_start()

    later_boot = session_mod.psutil.boot_time() + 3600
    monkeypatch.setattr(session_mod.psutil, "boot_time", lambda: later_boot)
    assert session.computer_restarted_since_start()

    session.adopt_current_boot()
    assert not session.computer_restarted_since_start()

    reloaded = Session(home, [browser])
    reloaded.load()
    assert not reloaded.computer_restarted_since_start()


def test_load_cleans_leftovers(home, browser):
    # Снимок от неудачного старта (журнала нет) и недоудалённая корзина.
    write(home / "backup" / "fake" / "Cookies", "old")
    write(browser.data_dir.parent / (snapshot.TRASH_PREFIX + "abc") / "Cookies", "old")

    session = Session(home, [browser])
    session.load()

    assert not session.is_active
    assert not (home / "backup").exists()
    assert not list(browser.data_dir.parent.glob(snapshot.TRASH_PREFIX + "*"))


def test_settings_roundtrip_and_broken_file(tmp_path):
    path = tmp_path / "settings.json"
    assert Settings.load(path).logout_on_shutdown is True

    Settings(logout_on_shutdown=False).save(path)
    assert Settings.load(path).logout_on_shutdown is False

    path.write_text("{ сломанный json", encoding="utf-8")
    assert Settings.load(path).logout_on_shutdown is True
