"""Начальная подборка карточек для текущего пользователя Windows."""

from session_controller import registry
from session_controller.targets import AI, BROWSER, Target


def initial_pins(targets: list[Target], installed: set[str]) -> list[str]:
    key = (r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations"
           r"\https\UserChoice")
    prog_id = (registry.read_string(key, "ProgId") or "").lower()
    prefixes = (("chrome", "chrome"), ("msedge", "edge"), ("firefox", "firefox"),
                ("yandex", "yandex"), ("brave", "brave"), ("vivaldi", "vivaldi"),
                ("operagx", "opera_gx"), ("operastable", "opera"))
    browsers = [t.id for t in targets if t.kind == BROWSER]
    browser = next((name for prefix, name in prefixes if prog_id.startswith(prefix)
                    and name in browsers), None)
    if browser is None:
        browser = next((name for name in browsers if name in installed), "edge")
    ai = [t.id for t in targets if t.kind == AI]
    preferred = ["chatgpt_codex", *ai]
    assistant = next((name for name in preferred if name in installed), "chatgpt_codex")
    available = {t.id for t in targets}
    return [name for name in (browser, assistant, "windows_credentials", "telegram")
            if name in available]
