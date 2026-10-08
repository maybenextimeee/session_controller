# Сборка Session Controller на своём компьютере: exe и установщик.
#
# Запуск из корня репозитория:
#     powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Нужно: виртуальная среда .venv с requirements-dev.txt (там есть PyInstaller)
# и, для установщика, Inno Setup 6: https://jrsoftware.org/isdl.php

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Не найдена виртуальная среда .venv — см. docs\DEVELOPMENT.md"
}

& $python -m PyInstaller --noconfirm --clean packaging\SessionController.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller завершился с ошибкой" }
Write-Host "Готово: dist\SessionController\SessionController.exe"

$version = & $python -c "import session_controller; print(session_controller.__version__)"
$iscc = Get-ChildItem "${env:ProgramFiles(x86)}\Inno Setup*\ISCC.exe", "$env:ProgramFiles\Inno Setup*\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup*\ISCC.exe" -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $iscc) {
    Write-Host "Inno Setup не найден — установщик не собран. Скачать: https://jrsoftware.org/isdl.php"
    exit 0
}

& $iscc.FullName "/DAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup завершился с ошибкой" }
Write-Host "Готово: dist\SessionController-Setup-$version.exe"
