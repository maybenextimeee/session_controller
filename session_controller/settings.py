"""Настройки пользователя (settings.json)."""

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Settings:
    # Галочка «Выходить из аккаунтов при выключении компьютера»
    logout_on_shutdown: bool = True
    # Программы, с которых пользователь снял галочку в списке «Что очищать».
    # Храним именно выключенные, чтобы новые программы по умолчанию были включены.
    disabled_targets: list[str] = field(default_factory=list)
    # Тема окна: "system" (как в Windows), "light" или "dark".
    theme: str = "system"
    # Раз в сутки спрашивать GitHub, нет ли новой версии.
    check_updates: bool = True
    # Удалять в конце сессии то, что появилось за неё в «Загрузках».
    clean_downloads: bool = False
    language: str = "ru"
    pinned_targets: list[str] | None = None

    @classmethod
    def load(cls, path: Path) -> "Settings":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError):
            log.exception("Не удалось прочитать настройки, беру настройки по умолчанию")
            return cls()
        if not isinstance(data, dict):
            return cls()
        if data.get("language") not in ("en", "ru"):
            data["language"] = "ru"
        pins = data.get("pinned_targets")
        if isinstance(pins, list):
            data["pinned_targets"] = list(dict.fromkeys(key for key in pins if isinstance(key, str)))
        else:
            data["pinned_targets"] = None
        disabled = data.get("disabled_targets")
        if isinstance(disabled, list) and ("chatgpt" in disabled or "codex" in disabled):
            # Один переключатель не должен заново включать отключённую очистку.
            data["disabled_targets"] = [
                target for target in disabled if target not in ("chatgpt", "codex", "chatgpt_codex")
            ] + ["chatgpt_codex"]
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
