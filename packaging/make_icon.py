"""Сохранить значок программы в assets/icon.ico — для exe и установщика.

Значок рисуется кодом (session_controller/app.py, make_icon), а этот скрипт
просто переносит его в файл. Запускать после изменения make_icon:

    python packaging/make_icon.py

Нужен Pillow: pip install pillow
"""

import sys
from io import BytesIO
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from session_controller.app import make_icon  # noqa: E402

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def main() -> None:
    app = QApplication([])  # без него Qt не умеет рисовать

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    make_icon().pixmap(256, 256).save(buffer, "PNG")

    image = Image.open(BytesIO(bytes(buffer.data())))
    target = ROOT / "assets" / "icon.ico"
    image.save(target, sizes=[(size, size) for size in SIZES])
    print(f"Сохранено: {target}")
    app.quit()


if __name__ == "__main__":
    main()
