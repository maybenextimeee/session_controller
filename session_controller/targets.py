"""Что Session Controller умеет очищать: браузеры, приложения, хранилище паролей Windows.

Для браузеров и приложений работает одна схема: перед сессией запоминаем
папки и файлы, где программа хранит входы в аккаунты, а в конце возвращаем
их как было. Чтобы добавить новую программу, достаточно описать её здесь.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from session_controller import registry

BROWSER = "browser"
APP = "app"
CREDENTIALS = "credentials"


@dataclass(frozen=True)
class Target:
    id: str
    name: str
    kind: str = APP
    # Подсказка в интерфейсе: что именно удалится.
    hint: str = ""
    # Папки и файлы, которые возвращаем к состоянию до сессии.
    paths: tuple[Path, ...] = ()
    # Процессы программы: их нужно закрыть, пока работаем с её файлами.
    process_names: tuple[str, ...] = ()
    # Если имя процесса слишком общее (у Яндекса это browser.exe),
    # дополнительно проверяем, что этот кусок есть в пути к exe.
    exe_hint: str = ""
    # Что не копировать (кэш): шаблоны имён файлов и папок, например "user_data*".
    skip: tuple[str, ...] = ()
    # Значения реестра HKEY_CURRENT_USER: (раздел, имя значения).
    registry_values: tuple[tuple[str, str], ...] = ()
    # Где обычно лежит exe программы — из него берём значок для окна.
    # Не обязательно: значок ищется и по имени процесса (раздел реестра App Paths).
    exe_paths: tuple[Path, ...] = ()

    def is_installed(self) -> bool:
        if self.kind == CREDENTIALS:
            return sys.platform == "win32"
        return any(path.exists() for path in self.paths)


WINDOWS_CREDENTIALS = Target(
    "windows_credentials",
    "Диспетчер учётных данных Windows",
    kind=CREDENTIALS,
    hint="Пароли и токены, которые программы (Git, GitHub Desktop и др.)\n"
         "сохранили в Windows за время сессии",
)


def known_targets() -> list[Target]:
    local = _env_dir("LOCALAPPDATA")
    roaming = _env_dir("APPDATA")
    home = _env_dir("USERPROFILE")

    targets: list[Target] = []
    if local and roaming:
        targets += _browsers(local, roaming)
        targets += _apps(local, roaming, home)
    if home and roaming:
        targets.append(_git(home, roaming, local))
    if sys.platform == "win32":
        targets.append(WINDOWS_CREDENTIALS)
    return targets


def _browsers(local: Path, roaming: Path) -> list[Target]:
    hint = "Входы на сайты, сохранённые пароли, история, закладки, расширения"
    programs = _program_files()

    def browser(id_, name, data_dir, process, exe_hint="", exe_paths=()):
        return Target(id_, name, kind=BROWSER, hint=hint, paths=(data_dir,),
                      process_names=(process,), exe_hint=exe_hint, exe_paths=tuple(exe_paths))

    return [
        browser("chrome", "Google Chrome", local / "Google" / "Chrome" / "User Data", "chrome.exe",
                exe_paths=[d / "Google" / "Chrome" / "Application" / "chrome.exe"
                           for d in (local, *programs)]),
        browser("edge", "Microsoft Edge", local / "Microsoft" / "Edge" / "User Data", "msedge.exe",
                exe_paths=[d / "Microsoft" / "Edge" / "Application" / "msedge.exe"
                           for d in programs]),
        browser("yandex", "Яндекс Браузер", local / "Yandex" / "YandexBrowser" / "User Data",
                "browser.exe", exe_hint="yandex",
                exe_paths=[d / "Yandex" / "YandexBrowser" / "Application" / "browser.exe"
                           for d in (local, *programs)]),
        browser("brave", "Brave", local / "BraveSoftware" / "Brave-Browser" / "User Data",
                "brave.exe",
                exe_paths=[d / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"
                           for d in (local, *programs)]),
        browser("vivaldi", "Vivaldi", local / "Vivaldi" / "User Data", "vivaldi.exe",
                exe_paths=[d / "Vivaldi" / "Application" / "vivaldi.exe"
                           for d in (local, *programs)]),
        browser("opera", "Opera", roaming / "Opera Software" / "Opera Stable", "opera.exe",
                exe_paths=[local / "Programs" / "Opera" / "opera.exe"]),
        browser("opera_gx", "Opera GX", roaming / "Opera Software" / "Opera GX Stable",
                "opera.exe", exe_paths=[local / "Programs" / "Opera GX" / "opera.exe"]),
        browser("firefox", "Mozilla Firefox", roaming / "Mozilla" / "Firefox", "firefox.exe",
                exe_paths=[d / "Mozilla Firefox" / "firefox.exe" for d in programs]),
    ]


def _apps(local: Path, roaming: Path, home: Path | None) -> list[Target]:
    programs = _program_files()
    # С версии 1.118 VS Code хранит общие данные, в том числе входы в аккаунты
    # (GitHub, Microsoft), не в %APPDATA%\Code, а в ~\.vscode-shared.
    vscode_shared = (home / ".vscode-shared",) if home else ()
    apps = [
        Target(
            "telegram", "Telegram",
            hint="Вход в Telegram Desktop и кэш переписки",
            paths=(
                roaming / "Telegram Desktop" / "tdata",
                # Версия из Microsoft Store
                local / "Packages" / "TelegramMessengerLLP.TelegramDesktop_t4vkhr7zbq3ty"
                / "LocalCache" / "Roaming" / "Telegram Desktop UWP" / "tdata",
            ),
            process_names=("Telegram.exe",),
            exe_paths=(roaming / "Telegram Desktop" / "Telegram.exe",),
            # user_data — кэш картинок и файлов из чатов, emoji — наборы эмодзи
            skip=("user_data*", "emoji", "dumps"),
        ),
        Target(
            "discord", "Discord",
            hint="Вход в Discord",
            paths=(roaming / "discord", roaming / "discordptb", roaming / "discordcanary"),
            process_names=("Discord.exe", "DiscordPTB.exe", "DiscordCanary.exe"),
            exe_paths=_newest(local / "Discord", "app-*/Discord.exe"),
        ),
        Target(
            "vscode", "VS Code",
            hint="Вход в GitHub / Microsoft в VS Code, настройки, история.\n"
                 "Несохранённые файлы в VS Code пропадут.",
            paths=(roaming / "Code", *vscode_shared),
            process_names=("Code.exe",),
            exe_paths=tuple(d / "Microsoft VS Code" / "Code.exe"
                            for d in (local / "Programs", *programs)),
            skip=("CachedData", "CachedExtensionVSIXs", "CachedProfilesData", "logs"),
        ),
    ]

    steam_dir = _steam_dir()
    if steam_dir:
        apps.append(Target(
            "steam", "Steam",
            hint="Вход в Steam, запомненные аккаунты, вход в магазин внутри Steam",
            paths=(
                steam_dir / "config" / "loginusers.vdf",
                steam_dir / "config" / "config.vdf",
                local / "Steam",  # токены входа (local.vdf) и встроенный браузер Steam
            ),
            process_names=("steam.exe", "steamwebhelper.exe"),
            exe_paths=(steam_dir / "steam.exe",),
            registry_values=(
                (r"Software\Valve\Steam", "AutoLoginUser"),
                (r"Software\Valve\Steam", "RememberPassword"),
            ),
        ))

    return apps


def _git(home: Path, roaming: Path, local: Path | None) -> Target:
    desktop = (local / "GitHubDesktop" / "GitHubDesktop.exe",) if local else ()
    return Target(
        "git", "Git и GitHub",
        hint="Настройки Git (имя, почта), SSH-ключи,\n"
             "вход в GitHub CLI и GitHub Desktop",
        paths=(
            home / ".gitconfig",
            home / ".git-credentials",
            home / ".ssh",
            roaming / "GitHub CLI",
            roaming / "GitHub Desktop",
        ),
        process_names=("GitHubDesktop.exe",),
        exe_paths=(*desktop, *(d / "Git" / "git-bash.exe" for d in _program_files())),
    )


def _steam_dir() -> Path | None:
    path = registry.read_string(r"Software\Valve\Steam", "SteamPath")
    if path:
        return Path(path)
    program_files = os.environ.get("ProgramFiles(x86)")
    if program_files and (Path(program_files) / "Steam").is_dir():
        return Path(program_files) / "Steam"
    return None


def _program_files() -> tuple[Path, ...]:
    """Program Files и Program Files (x86) — там, где они есть."""
    names = ("ProgramFiles", "ProgramFiles(x86)")
    return tuple(dict.fromkeys(d for d in map(_env_dir, names) if d))


def _newest(folder: Path, pattern: str) -> tuple[Path, ...]:
    """Самый новый exe из папок с версиями, например Discord\\app-1.0.9258."""
    found = sorted(folder.glob(pattern)) if folder.is_dir() else []
    return tuple(found[-1:])


def _env_dir(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None
