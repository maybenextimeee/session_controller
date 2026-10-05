"""Сохранить значок программы в assets/icon.ico — для exe и установщика.

Значок рисуется кодом (session_controller/icons.py, make_icon), а этот скрипт
просто переносит его в файл. Запускать после изменения make_icon:

    python packaging/make_icon.py

Внутри .ico лежат обычные PNG разных размеров — Windows это понимает
начиная с Vista, так что сторонние библиотеки не нужны.
"""

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from session_controller.icons import make_icon  # noqa: E402

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def png_bytes(size: int) -> bytes:
    pixmap = make_icon().pixmap(256, 256)
    if size != 256:
        pixmap = pixmap.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(buffer.data())


def main() -> None:
    app = QApplication([])  # без него Qt не умеет рисовать

    images = [png_bytes(size) for size in SIZES]
    # Формат .ico: заголовок, таблица картинок, затем сами картинки.
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    table = b""
    for size, data in zip(SIZES, images):
        side = 0 if size == 256 else size  # 0 означает 256
        table += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        offset += len(data)

    target = ROOT / "assets" / "icon.ico"
    target.write_bytes(header + table + b"".join(images))
    print(f"Сохранено: {target}")
    app.quit()


if __name__ == "__main__":
    main()
