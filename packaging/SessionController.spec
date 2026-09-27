# Рецепт сборки SessionController.exe для PyInstaller.
#
# Запуск из корня репозитория:
#     python -m PyInstaller --noconfirm --clean packaging/SessionController.spec
#
# Результат: папка dist/SessionController с SessionController.exe и всем нужным
# рядом. Режим «папка», а не «один файл»: так программа быстрее запускается и
# реже вызывает ложные срабатывания антивирусов.

import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = re.search(
    r'__version__ = "([^"]+)"',
    (ROOT / "session_controller" / "__init__.py").read_text(encoding="utf-8"),
).group(1)


def version_info():
    """Свойства exe (видны в «Свойства → Подробно» и в диспетчере задач)."""
    if sys.platform != "win32":
        return None
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct,
        VSVersionInfo,
    )

    numbers = tuple(int(part) for part in VERSION.split(".")) + (0,) * (4 - len(VERSION.split(".")))
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo([StringTable("041904B0", [
                StringStruct("CompanyName", "maybenextimeee"),
                StringStruct("FileDescription", "Session Controller"),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", "SessionController"),
                StringStruct("OriginalFilename", "SessionController.exe"),
                StringStruct("ProductName", "Session Controller"),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0419, 1200])]),
        ],
    )


a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SessionController",
    icon=str(ROOT / "assets" / "icon.ico"),
    version=version_info(),
    console=False,  # без чёрного окна консоли
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="SessionController",
    upx=False,
)
