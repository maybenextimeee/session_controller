"""Проверки, которые работают только на настоящей Windows.

На других системах пропускаются. На GitHub их запускает автосборка
(.github/workflows/build.yml) на сервере с Windows.
"""

import base64
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from session_controller import credentials, processes, registry, snapshot
from session_controller.targets import Target

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="только для Windows")

TEST_KEY = r"Software\SessionControllerTest"


@pytest.fixture
def registry_key():
    yield TEST_KEY
    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_KEY)
    except FileNotFoundError:
        pass


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
