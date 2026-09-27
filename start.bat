@echo off
rem Run Session Controller without a console window.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Virtual environment not found. Run first: py -m venv .venv
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m session_controller
