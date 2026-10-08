"""Тесты движка сессии на ненастоящих программах во временной папке.

Запуск: python -m pytest
"""

from pathlib import Path

import pytest

from session_controller import credentials, processes, registry, snapshot
from session_controller import session as session_mod
from session_controller import targets as targets_mod
from session_controller.session import Session, SessionError
from session_controller.settings import Settings
from session_controller.targets import BROWSER, CREDENTIALS, Target, known_targets

NO_PROCESS = ("sc-test-no-such-process.exe",)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "app"


@pytest.fixture
def browser(tmp_path: Path) -> Target:
    data = tmp_path / "Chrome" / "User Data"
    write(data / "Local State", "state before")
    write(data / "Default" / "Network" / "Cookies", "cookies before")
    write(data / "Default" / "Cache" / "data_0", "cache")
    return Target("chrome", "Chrome", kind=BROWSER, paths=(data,), process_names=NO_PROCESS)


def test_end_returns_browser_to_state_before_session(home, browser):
    session = Session(home, [browser])
    session.start([browser])
    assert session.is_active

    # Во время сессии человек вошёл в аккаунты и создал новый профиль.
    data = browser.paths[0]
    write(data / "Default" / "Network" / "Cookies", "logged in")
    write(data / "Default" / "Login Data", "saved password")
    write(data / "Profile 1" / "Preferences", "new profile")

    session.end()

    assert read(data / "Default" / "Network" / "Cookies") == "cookies before"
    assert read(data / "Local State") == "state before"
    assert not (data / "Default" / "Login Data").exists()
    assert not (data / "Profile 1").exists()
    assert not (data / "Default" / "Cache").exists()  # кэш не копируется
    assert not session.is_active
    assert not session.journal_path.exists()
    assert not session.backup_root.exists()
    assert not list(data.parent.glob(snapshot.TRASH_PREFIX + "*"))


def test_files_and_folders_created_during_session_are_removed(home, tmp_path):
    folder = tmp_path / "Telegram Desktop" / "tdata"
    file = tmp_path / "user" / ".git-credentials"
    target = Target("app", "App", paths=(folder, file), process_names=NO_PROCESS)

    session = Session(home, [target])
    session.start([target])
    write(folder / "key_datas", "telegram login")
    write(file, "https://token@github.com")
    session.end()

    assert not folder.exists()
    assert not file.exists()


def test_existing_file_is_restored(home, tmp_path):
    gitconfig = tmp_path / "user" / ".gitconfig"
    write(gitconfig, "[user]\nname = before")
    target = Target("git", "Git", paths=(gitconfig,), process_names=NO_PROCESS)

    session = Session(home, [target])
    session.start([target])
    write(gitconfig, "[user]\nname = student")
    session.end()

    assert read(gitconfig) == "[user]\nname = before"


def test_skip_patterns_are_not_copied(home, tmp_path):
    tdata = tmp_path / "tdata"
    write(tdata / "key_datas", "keys")
    write(tdata / "user_data" / "media_cache" / "photo", "big photo")
    write(tdata / "user_data#2" / "cache", "big photo")
    target = Target("telegram", "Telegram", paths=(tdata,), process_names=NO_PROCESS,
                    skip=("user_data*",))

    session = Session(home, [target])
    session.start([target])
    backup = session.backup_root / "telegram" / "0"
    assert (backup / "key_datas").exists()
    assert not (backup / "user_data").exists()
    assert not (backup / "user_data#2").exists()

    session.end()
    assert read(tdata / "key_datas") == "keys"
    assert not (tdata / "user_data").exists()


def test_only_selected_targets_are_touched(home, browser, tmp_path):
    other = tmp_path / "Discord"
    write(other / "token", "before")
    discord = Target("discord", "Discord", paths=(other,), process_names=NO_PROCESS)

    session = Session(home, [browser, discord])
    session.start([browser])
    write(other / "token", "changed during session")
    session.end()

    assert read(other / "token") == "changed during session"


def test_registry_values_are_restored(home, tmp_path, monkeypatch):
    values = {("Software\\Valve\\Steam", "AutoLoginUser"): {"type": 1, "data": "before"}}
    monkeypatch.setattr(registry, "read", lambda key, name: values.get((key, name)))

    def fake_write(key, name, value):
        if value is None:
            values.pop((key, name), None)
        else:
            values[(key, name)] = value

    monkeypatch.setattr(registry, "write", fake_write)

    target = Target(
        "steam", "Steam", process_names=NO_PROCESS,
        registry_values=(("Software\\Valve\\Steam", "AutoLoginUser"),
                         ("Software\\Valve\\Steam", "RememberPassword")),
    )
    session = Session(home, [target])
    session.start([target])
    values[("Software\\Valve\\Steam", "AutoLoginUser")] = {"type": 1, "data": "student"}
    values[("Software\\Valve\\Steam", "RememberPassword")] = {"type": 4, "data": 1}
    session.end()

    assert values == {("Software\\Valve\\Steam", "AutoLoginUser"): {"type": 1, "data": "before"}}


def test_new_windows_credentials_are_deleted(home, monkeypatch):
    stored = {("git:https://old.example", 1), ("virtualapp/didlogical", 1)}
    monkeypatch.setattr(credentials, "list_all", lambda: sorted(stored))
    monkeypatch.setattr(credentials, "delete", lambda name, kind: stored.discard((name, kind)))

    target = Target("windows_credentials", "Credentials", kind=CREDENTIALS)
    session = Session(home, [target])
    session.start([target])
    stored.add(("git:https://github.com", 1))
    stored.add(("MicrosoftAccount:target=SSO_POP_Device", 1))  # служебная — не трогаем
    session.end()

    assert stored == {
        ("git:https://old.example", 1),
        ("virtualapp/didlogical", 1),
        ("MicrosoftAccount:target=SSO_POP_Device", 1),
    }


def test_refuses_to_close_program_it_was_launched_from(home, browser, monkeypatch):
    monkeypatch.setattr(processes, "launched_from", lambda targets: browser)
    session = Session(home, [browser])
    with pytest.raises(SessionError, match="запущен изнутри"):
        session.start([browser])
    assert not session.is_active


def test_session_survives_program_restart(home, browser):
    Session(home, [browser]).start([browser])
    cookies = browser.paths[0] / "Default" / "Network" / "Cookies"
    write(cookies, "logged in")

    restarted = Session(home, [browser])
    restarted.load()
    assert restarted.is_active
    assert [t.id for t in restarted.session_targets()] == ["chrome"]

    restarted.end()
    assert read(cookies) == "cookies before"


def test_failed_end_keeps_session_and_can_be_retried(home, browser, monkeypatch):
    session = Session(home, [browser])
    session.start([browser])
    cookies = browser.paths[0] / "Default" / "Network" / "Cookies"
    write(cookies, "logged in")

    def broken_restore(*_args):
        raise PermissionError("файл занят")

    with monkeypatch.context() as patch:
        patch.setattr(snapshot, "restore", broken_restore)
        with pytest.raises(SessionError):
            session.end()

    assert session.is_active
    assert session.journal_path.exists()

    session.end()
    assert read(cookies) == "cookies before"


def test_start_twice_is_an_error(home, browser):
    session = Session(home, [browser])
    session.start([browser])
    with pytest.raises(SessionError):
        session.start([browser])


def test_restart_detection(home, browser, monkeypatch):
    session = Session(home, [browser])
    session.start([browser])
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
    data = browser.paths[0]
    write(home / "backup" / "chrome" / "0" / "Cookies", "old")
    write(data.parent / (snapshot.TRASH_PREFIX + "abc") / "Cookies", "old")

    session = Session(home, [browser])
    session.load()

    assert not session.is_active
    assert not (home / "backup").exists()
    assert not list(data.parent.glob(snapshot.TRASH_PREFIX + "*"))


def test_settings_roundtrip_and_broken_file(tmp_path):
    path = tmp_path / "settings.json"
    assert Settings.load(path) == Settings(logout_on_shutdown=True, disabled_targets=[])

    Settings(logout_on_shutdown=False, disabled_targets=["vscode"]).save(path)
    assert Settings.load(path) == Settings(logout_on_shutdown=False, disabled_targets=["vscode"])

    path.write_text("{ сломанный json", encoding="utf-8")
    assert Settings.load(path).logout_on_shutdown is True


def test_launched_from_detects_parent_process():
    parent = processes.psutil.Process().parent()
    target = Target("parent", "Parent", process_names=(parent.name(),))
    unrelated = Target("other", "Other", process_names=NO_PROCESS)

    assert processes.launched_from([unrelated, target]) == target
    assert processes.launched_from([unrelated]) is None
    assert processes.running([unrelated, target]) == [target]


def test_vscode_target_includes_shared_storage(tmp_path, monkeypatch):
    """VS Code 1.118+ хранит входы в аккаунты в ~/.vscode-shared — его тоже нужно откатывать."""
    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE"):
        monkeypatch.setenv(name, str(tmp_path / name))
    vscode = next(t for t in known_targets() if t.id == "vscode")
    assert tmp_path / "APPDATA" / "Code" in vscode.paths
    assert tmp_path / "USERPROFILE" / ".vscode-shared" in vscode.paths


def test_steam_is_protected_even_if_not_installed(tmp_path, monkeypatch):
    """Steam ещё нет — следим за папкой, куда его ставят по умолчанию."""
    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "ProgramFiles", "ProgramFiles(x86)"):
        monkeypatch.setenv(name, str(tmp_path / name))
    monkeypatch.setattr(registry, "read_string", lambda _key, _name: None)
    steam = next(t for t in known_targets() if t.id == "steam")
    assert tmp_path / "ProgramFiles(x86)" / "Steam" / "config" / "loginusers.vdf" in steam.paths
    assert not steam.is_installed()


def test_system_proxy_is_restored_and_announced(home, monkeypatch):
    """VPN, закрытый силой, оставляет включённый прокси — в конце сессии его нужно вернуть."""
    key = targets_mod.INTERNET_SETTINGS
    values = {(key, "ProxyEnable"): {"type": 4, "data": 0}}
    monkeypatch.setattr(registry, "read", lambda k, n: values.get((k, n)))

    def fake_write(k, n, value):
        if value is None:
            values.pop((k, n), None)
        else:
            values[(k, n)] = value

    monkeypatch.setattr(registry, "write", fake_write)
    announced = []
    monkeypatch.setattr(session_mod.winapi, "notify_proxy_changed", lambda: announced.append(1))

    target = Target("vpn", "VPN", kind=targets_mod.VPN, process_names=NO_PROCESS,
                    registry_values=targets_mod.SYSTEM_PROXY)
    session = Session(home, [target])
    session.start([target])
    values[(key, "ProxyEnable")] = {"type": 4, "data": 1}
    values[(key, "ProxyServer")] = {"type": 1, "data": "127.0.0.1:10808"}
    session.end()

    assert values == {(key, "ProxyEnable"): {"type": 4, "data": 0}}
    assert announced == [1]


def test_vpn_and_ai_targets(tmp_path, monkeypatch):
    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "ProgramFiles", "ProgramFiles(x86)"):
        monkeypatch.setenv(name, str(tmp_path / name))
    # Claude из Microsoft Store: папку пакета находим по началу имени.
    package = tmp_path / "LOCALAPPDATA" / "Packages" / "Claude_test123"
    package.mkdir(parents=True)
    targets = {t.id: t for t in known_targets()}

    for vpn_id in ("happ", "v2raytun", "hiddify", "clash_verge"):
        assert targets[vpn_id].kind == targets_mod.VPN
        assert targets_mod.SYSTEM_PROXY == targets[vpn_id].registry_values
    assert package / "LocalCache" / "Roaming" / "Claude" in targets["claude"].paths
    assert tmp_path / "USERPROFILE" / ".claude" in targets["claude"].paths
    # ChatGPT ещё не установлен — под защитой его известная папка пакета.
    assert any("OpenAI.ChatGPT-Desktop_" in str(p) for p in targets["chatgpt"].paths)
    assert tmp_path / "USERPROFILE" / ".codex" in targets["chatgpt"].paths
