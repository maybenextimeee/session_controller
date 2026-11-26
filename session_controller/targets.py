"""Что Session Controller умеет очищать: браузеры, приложения, VPN- и ИИ-клиенты,
хранилище паролей Windows.

Для браузеров и приложений работает одна схема: перед сессией запоминаем
папки и файлы, где программа хранит входы в аккаунты, а в конце возвращаем
их как было. Чтобы добавить новую программу, достаточно описать её здесь.
"""

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from session_controller import registry, winapi

BROWSER = "browser"
APP = "app"
VPN = "vpn"
AI = "ai"
CREDENTIALS = "credentials"
# Папка «Загрузки»: не копируем её, а запоминаем список того, что в ней лежит,
# и в конце удаляем появившееся за сессию. Включается галочкой в настройках.
DOWNLOADS = "downloads"

# Настройки прокси Windows. VPN-клиент в режиме «системный прокси» включает их,
# и если закрыть его силой, прокси останется включённым на несуществующий адрес —
# пропадёт интернет. Поэтому вместе с VPN-клиентами откатываем и их.
INTERNET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
SYSTEM_PROXY = tuple(
    (INTERNET_SETTINGS, name)
    for name in ("ProxyEnable", "ProxyServer", "ProxyOverride", "AutoConfigURL")
)

# Где Windows записывает, куда установлены приложения из Microsoft Store.
STORE_PACKAGES = (r"Software\Classes\Local Settings\Software\Microsoft\Windows"
                  r"\CurrentVersion\AppModel\Repository\Packages")
CLAUDE_PACKAGE = "Claude_pzs8sxrjxfjjc"
CHATGPT_PACKAGE = "OpenAI.ChatGPT-Desktop_2p2nqsd0c76g0"
CODEX_PACKAGE = "OpenAI.Codex_2p2nqsd0c76g0"


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
    # Несколько вариантов — через «|» (см. matches_exe).
    exe_hint: str = ""
    # Что не копировать (кэш): шаблоны имён файлов и папок, например "user_data*".
    skip: tuple[str, ...] = ()
    # Значения реестра HKEY_CURRENT_USER: (раздел, имя значения).
    registry_values: tuple[tuple[str, str], ...] = ()
    # Целые ветки реестра HKEY_CURRENT_USER — для программ, которые хранят там все
    # настройки (так делают программы на Qt). Только вида Software\\<программа>.
    registry_keys: tuple[str, ...] = ()
    # Известные пути к exe для обнаружения установленной программы.
    exe_paths: tuple[Path, ...] = ()
    # Признаки установки, которые не входят в снимок сессии.
    install_paths: tuple[Path, ...] = ()
    package_families: tuple[str, ...] = ()

    def is_installed(self) -> bool:
        if self.kind == CREDENTIALS:
            return sys.platform == "win32"
        return (any(path.exists() for path in (*self.paths, *self.install_paths))
                or any(_is_executable(path) for path in self.exe_paths)
                or any(winapi.is_package_installed(family) for family in self.package_families)
                or any(registry.read_tree(key) is not None for key in self.registry_keys))

    def matches_exe(self, exe_path: str) -> bool:
        """Подходит ли путь к exe под exe_hint (без учёта регистра)."""
        if not self.exe_hint:
            return True
        exe_path = exe_path.lower()
        return any(hint in exe_path for hint in self.exe_hint.lower().split("|"))


WINDOWS_CREDENTIALS = Target(
    "windows_credentials",
    "Диспетчер учётных данных Windows",
    kind=CREDENTIALS,
    hint="Пароли и токены, которые программы (Git, GitHub Desktop и др.)\n"
         "сохранили в Windows за время сессии",
)


def downloads_target(folder: Path) -> Target:
    return Target(
        "downloads", "Загрузки", kind=DOWNLOADS, paths=(folder,),
        hint="Файлы и папки, которые появились в «Загрузках» за сессию",
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
    if local and roaming:
        targets += _vpn(local, roaming, home)
        targets += _ai(local, roaming, home)
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
    git_commands = tuple(Path(path) for name in ("git.exe", "gh.exe") if (path := shutil.which(name)))
    install_roots = (local / "Programs", *_program_files()) if local else _program_files()
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
        exe_paths=(
            *desktop, *(d / "Git" / "git-bash.exe" for d in install_roots), *git_commands,
        ),
    )


def _vpn(local: Path, roaming: Path, home: Path | None) -> list[Target]:
    hint = ("Подписки, ключи и серверы VPN-клиента.\n"
            "Настройки прокси Windows тоже вернутся как были до сессии.")
    programs = _program_files()
    temp = Path(os.environ.get("SystemDrive", "C:") + "\\") / "Temp"
    clash_id = "io.github.clash-verge-rev.clash-verge-rev"
    return [
        Target(
            "happ", "Happ", kind=VPN, hint=hint,
            paths=(roaming / "Happ", local / "Happ"),
            process_names=("Happ.exe", "xray.exe", "sing-box.exe", "antifilter.exe"),
            # xray.exe и sing-box.exe бывают и у других клиентов — закрываем только свои.
            exe_hint="\\happ\\",
            registry_values=SYSTEM_PROXY,
            exe_paths=(
                *(d / "FlyFrogLLC" / "Happ" / "Happ.exe"
                  for d in (local / "Programs", *programs)),
                *(d / "Happ" / "Happ.exe" for d in (roaming, local / "Programs", *programs)),
            ),
        ),
        Target(
            "v2raytun", "v2RayTun", kind=VPN, hint=hint,
            paths=(
                roaming / "v2RayTun.net",
                # Текущее подключение (адрес сервера и ключ) v2RayTun кладёт сюда.
                temp / "v2RayTun" / "connection.json",
                temp / "v2RayTun" / "tunnel.json",
            ),
            process_names=("v2RayTun.exe", "xraycore.exe"),
            exe_hint="v2raytun",
            registry_values=SYSTEM_PROXY,
            exe_paths=(home / "v2RayTun" / "v2RayTun.exe",) if home else (),
        ),
        Target(
            "hiddify", "Hiddify", kind=VPN, hint=hint,
            paths=(roaming / "Hiddify",),
            process_names=("Hiddify.exe", "HiddifyCli.exe"),
            exe_hint="hiddify",
            registry_values=SYSTEM_PROXY,
            exe_paths=tuple(d / "Hiddify" / "Hiddify.exe" for d in (local / "Programs", *programs)),
        ),
        Target(
            "amnezia", "AmneziaVPN", kind=VPN, hint=hint,
            # Настройки (серверы и ключи, зашифрованные) — в реестре: так их хранит
            # Qt по умолчанию. Ключ шифрования лежит в диспетчере учётных данных
            # Windows («AmneziaVPN-Keychain») — его чистит карточка диспетчера.
            registry_keys=(r"Software\AmneziaVPN.ORG",),
            # Здесь Qt хранит прочие файлы программы (например, логи с адресами серверов).
            paths=(roaming / "AmneziaVPN.ORG", local / "AmneziaVPN.ORG"),
            # Служба AmneziaVPN-service работает от имени системы, её не трогаем.
            process_names=("AmneziaVPN.exe",),
            registry_values=SYSTEM_PROXY,
            exe_paths=tuple(d / "AmneziaVPN" / "AmneziaVPN.exe" for d in programs),
        ),
        Target(
            "clash_verge", "Clash Verge", kind=VPN, hint=hint,
            paths=(roaming / clash_id, local / clash_id),
            process_names=("clash-verge.exe", "verge-mihomo.exe", "verge-mihomo-alpha.exe"),
            registry_values=SYSTEM_PROXY,
            exe_paths=tuple(d / "Clash Verge" / "clash-verge.exe" for d in programs),
        ),
    ]


def _ai(local: Path, roaming: Path, home: Path | None) -> list[Target]:
    vscode_cache = ("CachedData", "CachedExtensionVSIXs", "CachedProfilesData", "logs")
    antigravity_home = (home / ".gemini" / "antigravity",) if home else ()
    antigravity_variants = ("Antigravity", "Antigravity IDE")
    claude_code_home = (home / ".claude", home / ".claude.json") if home else ()
    codex_home = (home / ".codex",) if home else ()
    claude_roots = _store_install_dirs("Claude_")
    openai_roots = (*_store_install_dirs("OpenAI.ChatGPT-Desktop_"),
                    *_store_install_dirs("OpenAI.Codex_"))
    openai_data = (*_store_data(local, "OpenAI.ChatGPT-Desktop", CHATGPT_PACKAGE),
                   *_store_data(local, "OpenAI.Codex", CODEX_PACKAGE))
    return [
        Target(
            "claude", "Claude for Desktop", kind=AI,
            hint="Вход в приложение Claude, чаты, настройки.\n"
                 "Папка Claude-Data (включая задачи и файлы Cowork) не очищается.",
            paths=(
                # Версия из Microsoft Store хранит данные внутри своего пакета.
                *(d / "LocalCache" / "Roaming" / "Claude"
                  for d in _store_data(local, "Claude", CLAUDE_PACKAGE)),
                roaming / "Claude",
            ),
            install_paths=(local / "Claude-Data" / CLAUDE_PACKAGE.lower(),),
            package_families=(CLAUDE_PACKAGE,),
            process_names=("claude.exe", "claude-desktop.exe"),
            # claude.exe — и у приложения, и у Claude Code; приложение узнаём по
            # пакету из Microsoft Store или по папке старой версии.
            exe_hint="pzs8sxrjxfjjc|anthropicclaude",
            # Встроенная копия Claude Code весит сотни мегабайт, входов в ней нет.
            skip=("claude-code", "vm_bundles", "logs"),
            exe_paths=(
                *(d / app / name for d in claude_roots for app in ("", "app")
                  for name in ("Claude.exe", "claude-desktop.exe")),
                local / "AnthropicClaude" / "claude.exe",
                *_newest(local / "AnthropicClaude", "app-*/claude.exe"),
            ),
        ),
        Target(
            "claude_code", "Claude Code", kind=AI,
            hint="Вход в Claude Code, история чатов, настройки и память.\n"
                 "Закрывает и Claude Code внутри приложения Claude.",
            paths=claude_code_home,
            process_names=("claude.exe",),
            # Отдельно установленный Claude Code и копия внутри приложения Claude.
            exe_hint="\\.local\\bin\\|\\claude-code\\",
            exe_paths=(home / ".local" / "bin" / "claude.exe",) if home else (),
        ),
        Target(
            "chatgpt_codex", "ChatGPT и Codex", kind=AI,
            hint="Входы, история и настройки ChatGPT и Codex, включая Codex CLI",
            paths=(
                *codex_home,
                *(d / part for d in openai_data for part in ("LocalCache", "LocalState")),
            ),
            package_families=(CHATGPT_PACKAGE, CODEX_PACKAGE),
            process_names=("ChatGPT.exe", "Codex.exe"),
            exe_paths=tuple(
                d / app / name for d in openai_roots for app in ("", "app")
                for name in ("ChatGPT.exe", "Codex.exe")
            ),
        ),
        Target(
            "cursor", "Cursor", kind=AI,
            hint="Вход в Cursor, настройки, история.\n"
                 "Несохранённые файлы в Cursor пропадут.",
            paths=(roaming / "Cursor",),
            process_names=("Cursor.exe",),
            skip=vscode_cache,
            exe_paths=(local / "Programs" / "cursor" / "Cursor.exe",),
        ),
        Target(
            "antigravity", "Google Antigravity", kind=AI,
            hint="Вход, история и настройки Antigravity и Antigravity IDE.\n"
                 "Несохранённые изменения в редакторе могут пропасть.",
            paths=(*(roaming / name for name in antigravity_variants), *antigravity_home),
            process_names=("Antigravity.exe", "Antigravity IDE.exe", "language_server.exe",
                           "language_server_windows_x64.exe", "language_server_windows_arm64.exe",
                           "webm_encoder.exe"),
            # Имена вспомогательных процессов встречаются и у других приложений.
            exe_hint="\\antigravity\\|\\antigravity ide\\|\\google antigravity\\",
            skip=(*vscode_cache, "GPUPersistentCache"),
            exe_paths=tuple(
                root / folder / f"{name}.exe"
                for root in (local / "Programs", *_program_files())
                for name in antigravity_variants
                for folder in dict.fromkeys((name, "Antigravity"))
            ),
        ),
    ]


def _store_data(local: Path, prefix: str, known: str = "") -> tuple[Path, ...]:
    """Папки данных приложения из Microsoft Store: %LOCALAPPDATA%\\Packages\\<имя>_<код>.

    Если папка ещё не создана, получаем ожидаемый путь по известному имени пакета.
    """
    packages = local / "Packages"
    found = sorted(packages.glob(f"{prefix}_*")) if packages.is_dir() else []
    if found:
        return tuple(found)
    return (packages / known,) if known else ()


def _store_install_dirs(prefix: str) -> tuple[Path, ...]:
    """Куда установлены приложения из Microsoft Store (для значков).

    Сама папка WindowsApps закрыта для просмотра, поэтому путь берём из реестра.
    """
    dirs = []
    for package in registry.subkeys(STORE_PACKAGES):
        if package.lower().startswith(prefix.lower()):
            root = registry.read_string(rf"{STORE_PACKAGES}\{package}", "PackageRootFolder")
            if root:
                dirs.append(Path(root))
    return tuple(dirs)


def _is_executable(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        # WindowsApps может запрещать проверку файла внутри пакета.
        return False


def _steam_dir() -> Path | None:
    """Папка Steam: из реестра, а если Steam ещё нет — куда его ставят по умолчанию.

    """
    path = registry.read_string(r"Software\Valve\Steam", "SteamPath")
    if path:
        return Path(path)
    programs = _program_files()
    return programs[-1] / "Steam" if programs else None


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
