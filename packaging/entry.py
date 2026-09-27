"""Точка входа для PyInstaller: он собирает exe из обычного скрипта, а не из пакета."""

from session_controller.app import main

if __name__ == "__main__":
    raise SystemExit(main())
