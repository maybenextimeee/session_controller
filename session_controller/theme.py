"""Светлая и тёмная тема интерфейса.

Цвета взяты с сайта maybenextime.ru: почти чёрный фон, голубой и фиолетовый
акценты, тонкие полупрозрачные рамки. Светлая тема — те же акценты на светлом фоне.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

SYSTEM = "system"
LIGHT = "light"
DARK = "dark"
CHOICES = {SYSTEM: "Как в системе", LIGHT: "Светлая", DARK: "Тёмная"}

# Необязательные шрифты сайта (Unbounded, Onest, JetBrains Mono): если положить
# их .ttf сюда, программа возьмёт их. Без них — системные шрифты Windows.
FONTS_DIR = Path(__file__).resolve().parent / "resources" / "fonts"


@dataclass(frozen=True)
class Theme:
    dark: bool
    bg: str
    bg_elev: str
    card: str
    card_hover: str
    border: str
    border_strong: str
    text: str
    muted: str
    dim: str
    accent: str
    accent_2: str
    green: str
    yellow: str
    # Кнопка «наоборот»: светлая в тёмной теме и тёмная в светлой.
    inverse_bg: str
    inverse_text: str
    # Карточка с включённой галочкой.
    selected_bg: str
    selected_border: str
    # Свечение и сетка на фоне.
    glow_1: str
    glow_2: str
    grid: str


DARK_THEME = Theme(
    dark=True,
    bg="#07080c",
    bg_elev="#0d0f15",
    card="rgba(255, 255, 255, 0.025)",
    card_hover="rgba(255, 255, 255, 0.05)",
    border="rgba(255, 255, 255, 0.08)",
    border_strong="rgba(255, 255, 255, 0.16)",
    text="#eef1f6",
    muted="#8f98ab",
    dim="#5d6579",
    accent="#5ee1ff",
    accent_2="#a78bfa",
    green="#4ade80",
    yellow="#fbbf24",
    inverse_bg="#eef1f6",
    inverse_text="#07080c",
    selected_bg="rgba(94, 225, 255, 0.05)",
    selected_border="rgba(94, 225, 255, 0.30)",
    glow_1="rgba(94, 225, 255, 0.10)",
    glow_2="rgba(167, 139, 250, 0.09)",
    grid="rgba(255, 255, 255, 0.035)",
)

LIGHT_THEME = Theme(
    dark=False,
    bg="#f5f7fb",
    bg_elev="#ffffff",
    card="rgba(255, 255, 255, 0.75)",
    card_hover="rgba(10, 14, 30, 0.04)",
    border="rgba(10, 14, 30, 0.09)",
    border_strong="rgba(10, 14, 30, 0.18)",
    text="#0b0d14",
    muted="#596175",
    dim="#8a91a3",
    accent="#0aa5c8",
    accent_2="#7c5cf0",
    green="#16a34a",
    yellow="#d97706",
    inverse_bg="#0b0d14",
    inverse_text="#f5f7fb",
    selected_bg="rgba(10, 165, 200, 0.06)",
    selected_border="rgba(10, 165, 200, 0.40)",
    glow_1="rgba(94, 225, 255, 0.22)",
    glow_2="rgba(167, 139, 250, 0.18)",
    grid="rgba(10, 14, 30, 0.04)",
)

# Градиент главной кнопки одинаковый в обеих темах, как на сайте.
GRADIENT_FROM = "#5ee1ff"
GRADIENT_TO = "#a78bfa"
ON_GRADIENT = "#07080c"


@dataclass(frozen=True)
class Fonts:
    display: str  # заголовки (на сайте Unbounded)
    body: str     # основной текст (Onest)
    mono: str     # подписи «как в коде» (JetBrains Mono)
    icons: str    # значки Windows: шестерёнка, стрелка назад


_current = DARK_THEME
_fonts = Fonts("Segoe UI", "Segoe UI", "Consolas", "")


def current() -> Theme:
    return _current


def fonts() -> Fonts:
    return _fonts


def qcolor(value: str) -> QColor:
    """QColor из "#rrggbb" или "rgba(r, g, b, a)" (a от 0 до 1)."""
    if value.startswith("rgba("):
        r, g, b, a = (part.strip() for part in value[5:-1].split(","))
        color = QColor(int(r), int(g), int(b))
        color.setAlphaF(float(a))
        return color
    return QColor(value)


def load_fonts() -> None:
    """Выбрать шрифты: шрифты сайта, если они есть, иначе системные."""
    global _fonts
    if FONTS_DIR.is_dir():
        for file in sorted(FONTS_DIR.glob("*.[ot]tf")):
            if QFontDatabase.addApplicationFont(str(file)) < 0:
                log.warning("Не удалось загрузить шрифт %s", file.name)

    available = set(QFontDatabase.families())

    def pick(*names: str) -> str:
        return next((name for name in names if name in available), names[-1])

    _fonts = Fonts(
        display=pick("Unbounded", "Segoe UI Variable Display", "Segoe UI"),
        body=pick("Onest", "Segoe UI Variable Text", "Segoe UI"),
        mono=pick("JetBrains Mono", "Cascadia Mono", "Consolas"),
        icons=pick("Segoe Fluent Icons", "Segoe MDL2 Assets", ""),
    )


def system_is_dark() -> bool:
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


class ThemeManager(QObject):
    """Применяет тему ко всей программе и следит за темой Windows."""

    changed = Signal()

    def __init__(self, app: QApplication, choice: str) -> None:
        super().__init__(app)
        self.app = app
        self.choice = choice if choice in CHOICES else SYSTEM
        self._applying = False
        app.setStyle("Fusion")
        load_fonts()
        app.styleHints().colorSchemeChanged.connect(self._on_system_changed)
        self.apply()

    def set_choice(self, choice: str) -> None:
        self.choice = choice
        self.apply()

    def apply(self) -> None:
        global _current
        hints = self.app.styleHints()
        self._applying = True
        try:
            # Тема Qt влияет и на рамку окон Windows: тёмный заголовок в тёмной теме.
            if self.choice == SYSTEM:
                hints.unsetColorScheme()
                dark = system_is_dark()
            else:
                dark = self.choice == DARK
                hints.setColorScheme(Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light)
        finally:
            self._applying = False

        _current = DARK_THEME if dark else LIGHT_THEME
        font = QFont(_fonts.body)
        font.setPointSizeF(10)
        self.app.setFont(font)
        self.app.setPalette(_palette(_current))
        self.app.setStyleSheet(stylesheet(_current, _fonts))
        self.changed.emit()

    def _on_system_changed(self) -> None:
        if not self._applying and self.choice == SYSTEM:
            log.info("В Windows сменилась тема")
            self.apply()


def _palette(t: Theme) -> QPalette:
    """Палитра нужна для того, что не покрывает стиль: диалоги, выделение, ссылки."""
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.bg,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.bg_elev,
        QPalette.ColorRole.AlternateBase: t.bg,
        QPalette.ColorRole.ToolTipBase: t.bg_elev,
        QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.PlaceholderText: t.dim,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.bg_elev,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.BrightText: t.text,
        QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: ON_GRADIENT,
        QPalette.ColorRole.Link: t.accent,
        QPalette.ColorRole.LinkVisited: t.accent_2,
    }
    for role, value in roles.items():
        palette.setColor(role, qcolor(value))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, qcolor(t.dim))
    return palette


def stylesheet(t: Theme, f: Fonts) -> str:
    return f"""
QWidget {{
    color: {t.text};
    font-family: "{f.body}";
}}
QMainWindow, QDialog, QMessageBox {{
    background: {t.bg};
}}
QLabel:disabled {{ color: {t.dim}; }}

QLabel#appTitle {{
    font-family: "{f.display}";
    font-size: 14pt;
    font-weight: 700;
}}
QLabel#pageTitle {{
    font-family: "{f.display}";
    font-size: 13pt;
    font-weight: 700;
}}
QLabel#mono {{
    font-family: "{f.mono}";
    font-size: 8.5pt;
    color: {t.dim};
}}
QLabel#section {{
    font-family: "{f.mono}";
    font-size: 8pt;
    color: {t.dim};
    letter-spacing: 1.5px;
}}
QLabel#muted {{ color: {t.muted}; }}
QLabel#cardTitle {{ font-weight: 600; }}
QLabel#statusText {{
    font-family: "{f.mono}";
    font-size: 9pt;
    color: {t.muted};
}}
QLabel#link {{ color: {t.muted}; }}

QFrame#hero {{
    background: {t.card};
    border: 1px solid {t.border};
    border-radius: 16px;
}}
QFrame#pill {{
    background: {t.card};
    border: 1px solid {t.border};
    border-radius: 13px;
}}
QFrame#card {{
    background: {t.card};
    border: 1px solid {t.border};
    border-radius: 12px;
}}
QFrame#card:hover {{
    background: {t.card_hover};
    border-color: {t.border_strong};
}}
QFrame#card[checked="true"] {{
    background: {t.selected_bg};
    border-color: {t.selected_border};
}}
QFrame#card:disabled {{
    background: {t.card};
    border-color: {t.border};
}}
QFrame#card QLabel, QFrame#hero QLabel, QFrame#pill QLabel {{
    background: transparent;
    border: none;
}}
QFrame#card QLabel:disabled {{ color: {t.muted}; }}

QPushButton {{
    background: {t.card};
    border: 1px solid {t.border_strong};
    border-radius: 15px;
    padding: 6px 18px;
    min-width: 64px;
}}
QPushButton:hover {{ background: {t.card_hover}; border-color: {t.muted}; }}
QPushButton:pressed {{ background: {t.border}; }}
QPushButton:disabled {{ color: {t.dim}; border-color: {t.border}; }}

QPushButton#primary {{
    border: none;
    border-radius: 23px;
    padding: 13px 22px;
    font-size: 11pt;
    font-weight: 600;
    color: {ON_GRADIENT};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 {GRADIENT_FROM}, stop:1 {GRADIENT_TO});
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #7ae8ff, stop:1 #b9a2fb);
}}
QPushButton#primary:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #45cbe8, stop:1 #9378f0);
}}
QPushButton#primary[inverse="true"] {{
    background: {t.inverse_bg};
    color: {t.inverse_text};
}}
QPushButton#primary[inverse="true"]:hover {{ background: {t.muted}; }}
QPushButton#primary:disabled {{
    background: {t.border_strong};
    color: {t.muted};
}}

QPushButton#segment {{
    background: transparent;
    border: 1px solid {t.border};
    border-radius: 15px;
    padding: 6px 14px;
    min-width: 0;
    color: {t.muted};
}}
QPushButton#segment:hover {{ color: {t.text}; border-color: {t.border_strong}; }}
QPushButton#segment:checked {{
    background: {t.inverse_bg};
    border-color: {t.inverse_bg};
    color: {t.inverse_text};
    font-weight: 600;
}}

QPushButton#linkButton {{
    background: transparent;
    border: none;
    padding: 2px 0;
    min-width: 0;
    color: {t.muted};
    text-align: left;
}}
QPushButton#linkButton:hover {{ color: {t.accent}; }}

QToolButton#iconButton {{
    background: {t.card};
    border: 1px solid {t.border};
    border-radius: 17px;
    min-width: 32px;
    min-height: 32px;
    font-family: "{f.icons or f.body}";
    font-size: 11pt;
    color: {t.muted};
}}
QToolButton#iconButton:hover {{
    color: {t.text};
    background: {t.card_hover};
    border-color: {t.border_strong};
}}

QToolTip {{
    background: {t.bg_elev};
    color: {t.text};
    border: 1px solid {t.border_strong};
    padding: 6px 8px;
}}

QMenu {{
    background: {t.bg_elev};
    border: 1px solid {t.border_strong};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 6px 22px 6px 12px;
    border-radius: 6px;
}}
QMenu::item:selected {{ background: {t.card_hover}; }}
QMenu::item:disabled {{ color: {t.dim}; }}
QMenu::separator {{
    height: 1px;
    background: {t.border};
    margin: 5px 6px;
}}
"""
