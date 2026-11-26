"""Проверки, которые работают только на настоящей Windows.

На других системах пропускаются. На GitHub их запускает автосборка
(.github/workflows/build.yml) на сервере с Windows.
"""

import base64
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from session_controller import credentials, processes, registry, snapshot
from session_controller.session import Session
from session_controller.targets import Target

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="только для Windows")

TEST_KEY = r"Software\SessionControllerTest"


@pytest.fixture
def registry_key():
    yield TEST_KEY
    registry.delete_tree(TEST_KEY)  # с подразделами, если тест их создал


def test_registry_tree_roundtrip(registry_key):
    """Целую ветку можно запомнить и вернуть: новое удаляется, изменённое — назад."""
    import winreg

    def put(key, name, kind, data):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
            winreg.SetValueEx(handle, name, 0, kind, data)

    put(registry_key, "server", winreg.REG_SZ, "before")
    put(registry_key + r"\servers\0", "key", winreg.REG_BINARY, b"\x01\x02")
    put(registry_key + r"\servers\0", "port", winreg.REG_DWORD, 51820)
    before = registry.read_tree(registry_key)

    # «Во время сессии»: меняем, добавляем значения и целые подразделы.
    put(registry_key, "server", winreg.REG_SZ, "student")
    put(registry_key, "token", winreg.REG_SZ, "secret")
    put(registry_key + r"\servers\1", "key", winreg.REG_SZ, "secret")
    assert registry.read_tree(registry_key) != before

    registry.write_tree(registry_key, before)
    assert registry.read_tree(registry_key) == before

    registry.write_tree(registry_key, None)  # ветки до сессии не было
    assert registry.read_tree(registry_key) is None


def test_registry_tree_refuses_dangerous_keys():
    for key in ("Software", "", r"System\CurrentControlSet"):
        with pytest.raises(ValueError):
            registry.delete_tree(key)


def test_registry_roundtrip(registry_key):
    import winreg

    samples = {
        "text": {"type": winreg.REG_SZ, "data": "student"},
        "number": {"type": winreg.REG_DWORD, "data": 1},
        "binary": {"type": winreg.REG_BINARY, "data": b"\x00\x01\xff"},
    }
    for name, value in samples.items():
        if value["type"] == winreg.REG_BINARY:
            value = {**value, "data": base64.b64encode(value["data"]).decode(), "base64": True}
        registry.write(registry_key, name, value)
        assert registry.read(registry_key, name) == value

    registry.write(registry_key, "text", None)
    assert registry.read(registry_key, "text") is None
    registry.write(registry_key, "missing", None)  # удаление несуществующего — не ошибка


def test_credentials_list_and_delete():
    name = f"SessionControllerTest-{uuid.uuid4().hex[:8]}"
    added = subprocess.run(
        ["cmdkey", f"/generic:{name}", "/user:student", "/pass:secret"],
        capture_output=True, text=True,
    )
    if added.returncode != 0:
        pytest.skip(f"cmdkey недоступен: {added.stdout} {added.stderr}")

    try:
        # cmdkey сохраняет запись под именем «LegacyGeneric:target=<имя>».
        found = [item for item in credentials.list_all() if item[0].endswith(name)]
        assert len(found) == 1
        full_name, kind = found[0]

        credentials.delete(full_name, kind)
        assert found[0] not in credentials.list_all()
        credentials.delete(full_name, kind)  # повторное удаление — не ошибка
    finally:
        subprocess.run(["cmdkey", f"/delete:{name}"], capture_output=True)


def test_close_running_program():
    proc = subprocess.Popen(["ping", "-n", "60", "127.0.0.1"], stdout=subprocess.DEVNULL)
    target = Target("ping", "Ping", process_names=("PING.EXE",))
    try:
        time.sleep(0.5)
        assert processes.running([target]) == [target]
        processes.close([target])
        assert proc.wait(timeout=10) is not None
    finally:
        proc.kill()


def test_session_automatically_releases_codex_profile(tmp_path, monkeypatch):
    # Два одноимённых настоящих процесса Windows. Только первый из пакета ChatGPT.
    package = tmp_path / "WindowsApps/OpenAI.Codex_1.0_x64__2p2nqsd0c76g0/app/resources"
    external = tmp_path / "other"
    profile = tmp_path / ".codex"
    for folder in (package, external, profile):
        folder.mkdir(parents=True)
    for folder in (package, external):
        shutil.copyfile(Path(os.environ["SystemRoot"]) / "System32/ping.exe", folder / "node_repl.exe")
    marker = profile / "example.txt"
    marker.write_text("before")
    target = Target("chatgpt_codex", "ChatGPT", paths=(profile,), process_names=("ChatGPT.exe", "Codex.exe"))
    session = Session(tmp_path / "state", [target])
    children = []
    real_iter = processes.psutil.process_iter

    def test_processes(attrs):
        pids = {child.pid for child in children}
        return (proc for proc in real_iter(attrs) if proc.pid in pids)

    monkeypatch.setattr(processes.psutil, "process_iter", test_processes)
    session.start([target])
    marker.write_text("during")
    try:
        for folder, cwd in ((package, profile), (external, external)):
            children.append(subprocess.Popen(
                [str(folder / "node_repl.exe"), "-t", "127.0.0.1"], cwd=cwd,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ))
        with pytest.raises(OSError) as exc:
            profile.rename(tmp_path / "would-move")
        assert exc.value.winerror == 32
        # Журнал мог быть создан старой версией, знающей только два имени процессов.
        resumed = Session(session.home, [target])
        resumed.load()
        resumed.end()
        assert children[0].wait(timeout=2) is not None
        assert children[1].poll() is None
        assert marker.read_text() == "before" and not resumed.is_active
    finally:
        for child in children:
            child.kill()
            child.wait(timeout=5)


@pytest.mark.parametrize("existing", [True, False])
def test_codex_cleanup_with_persistently_locked_directory(tmp_path, existing):
    profile = tmp_path / ".codex"
    store = tmp_path / "package" / "LocalCache"
    target = Target("chatgpt_codex", "ChatGPT", paths=(profile, store))
    if existing:
        (profile / "settings").mkdir(parents=True)
        (profile / "settings" / "example").write_bytes(b"before")
    session = Session(tmp_path / "state", [target])
    session.start([target])
    profile.mkdir(exist_ok=True)
    (profile / "auth.json").write_text("test-login")
    (profile / "sessions").mkdir()
    (profile / "sessions" / "test").write_text("during")
    if existing:
        # Изменённое содержимое той же длины.
        (profile / "settings" / "example").write_bytes(b"change")
    store.mkdir(parents=True)
    (store / "login").write_text("desktop test login")

    # Дескриптор остаётся открытым до конца проверки; FILE_SHARE_DELETE отсутствует.
    import _winapi
    share_read_write = 3
    backup_semantics = 0x02000000  # позволяет открыть дескриптор каталога
    holder = _winapi.CreateFile(str(profile), _winapi.GENERIC_READ, share_read_write, 0,
                                _winapi.OPEN_EXISTING, backup_semantics, 0)
    try:
        with pytest.raises(OSError) as exc:
            profile.rename(tmp_path / "busy")
        assert exc.value.winerror == 32
        resumed = Session(session.home, [target])
        resumed.load()
        resumed.end()
        assert not resumed.is_active and not resumed.journal_path.exists()
        assert not (profile / "auth.json").exists() and not (profile / "sessions").exists()
        assert not store.exists()
        if existing:
            assert (profile / "settings" / "example").read_bytes() == b"before"
        else:
            assert list(profile.iterdir()) == []
    finally:
        _winapi.CloseHandle(holder)


@pytest.mark.parametrize("old_snapshot", [False, True])
def test_codex_runtime_guard_and_vpn_finish(tmp_path, old_snapshot):
    import _winapi
    from session_controller.targets import VPN

    profile = tmp_path / ".codex"
    store = tmp_path / "LocalCache"
    vpn_folder = tmp_path / "happ"
    codex = Target("chatgpt_codex", "ChatGPT", paths=(profile, store))
    vpn = Target("happ", "Happ", kind=VPN, paths=(vpn_folder,))
    session = Session(tmp_path / "state", [vpn, codex])
    guard = profile / ".codex-provisioning-abc123.guard"
    cache = profile / ".tmp/plugins-clone-test/engine"
    component = store / "Roaming/Codex/web/Codex/WidevineCdm/example.dll"
    for file in (guard, cache, component):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("before")
    history = profile / "sessions/example"
    history.parent.mkdir()
    history.write_text("before")
    session.start([vpn, codex])
    backup = session.backup_root / codex.id / "0"
    assert not (backup / guard.name).exists()
    assert not (backup / cache.relative_to(profile)).exists()
    assert not (session.backup_root / codex.id / "1" / component.relative_to(store)).exists()
    if old_snapshot:
        # Старый журнал с копией того же защищённого файла.
        (backup / guard.name).write_text("stale")
    guard.write_text("locked")
    cache.write_text("updated")
    component.write_text("updated")
    history.write_text("edited")
    (profile / "auth.json").write_text("new login")
    vpn_folder.mkdir()
    (vpn_folder / "profile").write_text("new vpn")
    handle = _winapi.CreateFile(str(guard), _winapi.GENERIC_READ, 0, 0,
                                _winapi.OPEN_EXISTING, 0, 0)
    try:
        reloaded = Session(session.home, [vpn, codex])
        reloaded.load()
        progress = []
        reloaded.end(lambda i, n, name: progress.append(name))
        assert progress == ["ChatGPT", "Happ"]
        assert not reloaded.is_active and not vpn_folder.exists()
        assert history.read_text() == "before" and not (profile / "auth.json").exists()
        assert cache.read_text() == component.read_text() == "updated"
    finally:
        _winapi.CloseHandle(handle)
    assert guard.read_text() == "locked"


def test_first_run_keeps_only_runtime_containers(tmp_path):
    profile = tmp_path / ".codex"
    clone = profile / ".tmp/plugins/example"
    clone.mkdir(parents=True)
    (profile / ".tmp/private.txt").write_text("during")
    (profile / "auth.json").write_text("during")
    snapshot.sync_profile(None, profile)
    assert clone.exists()
    assert not (profile / ".tmp/private.txt").exists()
    assert not (profile / "auth.json").exists()


def test_codex_cleanup_keeps_journal_for_busy_file_and_retries(tmp_path, monkeypatch):
    profile = tmp_path / ".codex"
    profile.mkdir()
    store = tmp_path / "LocalState"
    target = Target("chatgpt_codex", "ChatGPT", paths=(profile, store))
    session = Session(tmp_path / "state", [target])
    session.start([target])
    busy = profile / "a-busy-file"
    busy.write_text("test")
    (profile / "auth.json").write_text("test-login")
    store.mkdir()
    (store / "login").write_text("test-login")
    monkeypatch.setattr(snapshot, "_retry", lambda action: action())

    from session_controller.session import SessionError
    with busy.open("rb"):
        with pytest.raises(SessionError, match="a-busy-file"):
            session.end()
    assert session.is_active and session.journal_path.exists()
    assert not (profile / "auth.json").exists() and not store.exists()
    session.end()
    assert not session.is_active and list(profile.iterdir()) == []


def test_codex_cleanup_does_not_follow_session_junction(tmp_path):
    import _winapi

    source = tmp_path / "snapshot"
    source.mkdir()
    profile = tmp_path / ".codex"
    profile.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    external = outside / "keep"
    external.write_text("external")
    _winapi.CreateJunction(str(outside), str(profile / "link"))
    snapshot.sync_profile(source, profile)
    assert list(profile.iterdir()) == [] and external.read_text() == "external"


def test_snapshot_long_paths_and_read_only_files(tmp_path):
    # Путь длиннее 260 символов — обычный код Windows с таким не справляется.
    deep = tmp_path / "User Data"
    for index in range(12):
        deep = deep / f"very-long-folder-name-{index:02d}"
    long_file = deep / "Cookies"
    os.makedirs(snapshot._fs(deep), exist_ok=True)
    with open(snapshot._fs(long_file), "w", encoding="utf-8") as f:
        f.write("before")
    assert len(str(long_file)) > 260

    read_only = tmp_path / "User Data" / "Local State"
    read_only.write_text("state", encoding="utf-8")
    read_only.chmod(0o444)

    data = tmp_path / "User Data"
    backup = tmp_path / "backup"
    snapshot.backup(data, backup)

    with open(snapshot._fs(long_file), "w", encoding="utf-8") as f:
        f.write("logged in")
    (data / "new-profile").mkdir()

    snapshot.restore(backup, data)

    with open(snapshot._fs(long_file), encoding="utf-8") as f:
        assert f.read() == "before"
    assert (data / "Local State").read_text(encoding="utf-8") == "state"
    assert not (data / "new-profile").exists()
    assert not list(Path(tmp_path).glob(snapshot.TRASH_PREFIX + "*"))
