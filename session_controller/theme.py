"""Монохромные темы интерфейса."""

import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

SYSTEM = "system"
LIGHT = "light"
DARK = "dark"
CHOICES = {SYSTEM: "Как в системе", LIGHT: "Светлая", DARK: "Тёмная"}

# Фирменный градиент: мята → лайм. Одинаковый в обеих темах.
MINT = "#ededed"
LIME = "#ededed"
ON_ACCENT = "#101010"  # текст на градиенте


@dataclass(frozen=True)
class Theme:
    dark: bool
    bg: str
    surface: str        # карточки
    surface_hover: str
    surface_2: str      # плашки, дорожка переключателя, фон вкладок
    border: str
    border_strong: str
    text: str
    muted: str
    dim: str
    accent: str         # мятный для текста и точек (в светлой теме темнее)
    busy: str           # «программа занята», предупреждения
    danger: str         # ошибки
    inverse_bg: str     # контрастная кнопка: светлая в тёмной теме и наоборот
    inverse_text: str
    inverse_hover: str
    selected_bg: str    # карточка включённой программы
    selected_border: str
    glow_1: str         # свечение фона
    glow_2: str
    dots: str           # точечная сетка фона
    scrim: str          # затемнение окна под панелью поверх него


DARK_THEME = Theme(
    dark=True,
    bg="#0e0e0e",
    surface="#171717",
    surface_hover="#1d1d1d",
    surface_2="#222222",
    border="rgba(255, 255, 255, 0.06)",
    border_strong="rgba(255, 255, 255, 0.12)",
    text="#efefef",
    muted="#9f9f9f",
    dim="#6a6a6a",
    accent=MINT,
    busy="#bebebe",
    danger="#969696",
    inverse_bg="#efefef",
    inverse_text="#0e0e0e",
    inverse_hover="#ffffff",
    selected_bg="rgba(153, 153, 153, 0.07)",
    selected_border="rgba(153, 153, 153, 0.32)",
    glow_1="rgba(153, 153, 153, 0.11)",
    glow_2="rgba(177, 177, 177, 0.05)",
    dots="rgba(255, 255, 255, 0.07)",
    scrim="rgba(6, 6, 6, 0.74)",
)

LIGHT_THEME = Theme(
    dark=False,
    bg="#f3f3f3",
    surface="#ffffff",
    surface_hover="#f9f9f9",
    surface_2="#ebebeb",
    border="rgba(22, 22, 22, 0.08)",
    border_strong="rgba(22, 22, 22, 0.16)",
    text="#141414",
    muted="#606060",
    dim="#959595",
    accent="#797979",
    busy="#8f8f8f",
    danger="#676767",
    inverse_bg="#141414",
    inverse_text="#f3f3f3",
    inverse_hover="#2e2e2e",
    selected_bg="rgba(91, 91, 91, 0.05)",
    selected_border="rgba(91, 91, 91, 0.35)",
    glow_1="rgba(153, 153, 153, 0.28)",
    glow_2="rgba(177, 177, 177, 0.22)",
    dots="rgba(22, 22, 22, 0.09)",
    scrim="rgba(18, 18, 18, 0.34)",
)


@dataclass(frozen=True)
class Fonts:
    display: str  # заголовки, таймер, подписи разделов
    body: str     # основной текст
    icons: str    # значки Windows: шестерёнка, стрелка назад ("" — шрифта нет)


_current = DARK_THEME
_fonts = Fonts("Segoe UI", "Segoe UI", "")


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
    global _fonts
    available = set(QFontDatabase.families())

    def pick(*names: str) -> str:
        return next((name for name in names if name in available), names[-1])

    _fonts = Fonts(
        display=pick("Bahnschrift", "Segoe UI"),
        body=pick("Segoe UI Variable Text", "Segoe UI"),
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
        QPalette.ColorRole.Base: t.surface,
        QPalette.ColorRole.AlternateBase: t.surface_2,
        QPalette.ColorRole.ToolTipBase: t.surface,
        QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.PlaceholderText: t.dim,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.surface,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.BrightText: t.text,
        QPalette.ColorRole.Highlight: MINT,
        QPalette.ColorRole.HighlightedText: ON_ACCENT,
        QPalette.ColorRole.Link: t.accent,
        QPalette.ColorRole.LinkVisited: t.accent,
    }
    for role, value in roles.items():
        palette.setColor(role, qcolor(value))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, qcolor(t.dim))
    return palette


def stylesheet(t: Theme, f: Fonts) -> str:
    gradient = f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {MINT}, stop:1 {LIME})"
    return f"""
QWidget {{
    color: {t.text};
    font-family: "{f.body}";
}}
QMainWindow, QDialog, QMessageBox {{
    background: {t.bg};
}}
QLabel:disabled {{ color: {t.dim}; }}

QLabel#homeHeading {{ font-size: 26pt; font-weight: 650; color: {t.text}; }}
QToolButton#pin {{ background: {t.surface}; color: {t.muted}; border: 1px solid {t.border}; border-radius: 6px; min-width: 35px; min-height: 39px; font-size: 12pt; }}
QToolButton#pin:checked, QToolButton#pin:hover {{ color: {t.text}; border-color: {t.border_strong}; }}
QLabel#appTitle {{
    font-family: "{f.display}";
    font-size: 13pt;
    font-weight: 600;
}}
QLabel#pageTitle {{
    font-family: "{f.display}";
    font-size: 22pt;
    font-weight: 600;
}}
QLabel#caps {{
    font-family: "{f.display}";
    font-size: 8.5pt;
    font-weight: 600;
    color: {t.dim};
    letter-spacing: 1.2px;
}}
QLabel#counter {{
    font-family: "{f.display}";
    font-size: 8.5pt;
    font-weight: 600;
    color: {t.muted};
    background: {t.surface_2};
    border-radius: 9px;
    padding: 2px 8px;
}}
QLabel#muted {{ color: {t.muted}; }}
QLabel#small {{ color: {t.muted}; font-size: 9pt; }}
QLabel#cardTitle {{ font-weight: 600; }}

QFrame#panel {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: 8px;
}}
QFrame#card {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: 6px;
}}
QFrame#card:hover {{
    background: {t.surface_hover};
    border-color: {t.border_strong};
}}
QFrame#card[checked="true"] {{
    background: {t.selected_bg};
    border-color: {t.selected_border};
}}
QFrame#card:disabled {{
    background: {t.surface};
    border-color: {t.border};
}}
QFrame#card QLabel:disabled {{ color: {t.muted}; }}
QFrame#segmented {{
    background: {t.surface_2};
    border: none;
    border-radius: 6px;
}}

QPushButton {{
    background: {t.surface};
    border: 1px solid {t.border_strong};
    border-radius: 9px;
    padding: 6px 16px;
    min-width: 64px;
}}
QPushButton:hover {{ background: {t.surface_hover}; border-color: {t.dim}; }}
QPushButton:pressed {{ background: {t.surface_2}; }}
QPushButton:disabled {{ color: {t.dim}; border-color: {t.border}; }}


QPushButton#segment {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 7px 14px;
    min-width: 0;
    color: {t.muted};
}}
QPushButton#segment:hover {{ color: {t.text}; }}
QPushButton#segment:checked {{
    background: {t.surface};
    color: {t.text};
    font-weight: 600;
}}

QLabel#dialogTitle {{
    font-family: "{f.display}";
    font-size: 13pt;
    font-weight: 600;
}}
QFrame#itemsPanel {{
    background: {t.surface_2};
    border: none;
    border-radius: 12px;
}}
QPushButton#dialogPrimary, QPushButton#dialogSecondary {{
    border-radius: 10px;
    padding: 9px 18px;
    min-width: 0;
    font-family: "{f.display}";
    font-size: 10.5pt;
    font-weight: 600;
}}
QPushButton#dialogPrimary {{
    border: none;
    color: {ON_ACCENT};
    background: {gradient};
}}
QPushButton#dialogPrimary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #cccccc, stop:1 #e6e6e6);
}}
QPushButton#dialogSecondary {{
    background: {t.surface};
    border: 1px solid {t.border_strong};
    color: {t.text};
}}
QPushButton#dialogSecondary:hover {{
    background: {t.surface_hover};
    border-color: {t.dim};
}}

QLabel#tag {{
    font-family: "{f.display}";
    font-size: 8pt;
    font-weight: 600;
    color: {t.dim};
    background: {t.surface_2};
    border-radius: 8px;
    padding: 2px 7px;
}}
QPushButton#moreButton {{
    background: {t.surface};
    border: 1px solid {t.border_strong};
    border-radius: 8px;
    padding: 8px 12px;
    min-width: 0;
    color: {t.text};
}}
QPushButton#moreButton:hover {{
    color: {t.text};
    background: {t.surface};
}}
QFrame#sheet {{
    background: {t.bg};
    border: 1px solid {t.border_strong};
    border-radius: 18px;
}}
QScrollArea, QScrollArea > QWidget > QWidget {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {t.border_strong};
    border-radius: 2px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {t.dim}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QPushButton#updateButton {{
    background: {t.selected_bg};
    border: 1px solid {t.selected_border};
    border-radius: 15px;
    padding: 6px 13px;
    min-width: 0;
    color: {t.accent};
    font-weight: 600;
}}
QPushButton#updateButton:hover {{ border-color: {t.accent}; }}

QPushButton#linkButton {{
    background: transparent;
    border: none;
    padding: 2px 0;
    min-width: 0;
    color: {t.muted};
}}
QPushButton#linkButton:hover {{ color: {t.accent}; }}

QToolButton#iconButton {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: 10px;
    min-width: 34px;
    min-height: 34px;
    font-family: "{f.icons or f.body}";
    font-size: 11pt;
    color: {t.muted};
}}
QToolButton#iconButton:hover {{
    color: {t.text};
    background: {t.surface_hover};
    border-color: {t.border_strong};
}}

QToolTip {{
    background: {t.surface};
    color: {t.text};
    border: 1px solid {t.border_strong};
    padding: 6px 8px;
}}

QMenu {{
    background: {t.surface};
    border: 1px solid {t.border_strong};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 6px 22px 6px 12px;
    border-radius: 6px;
}}
QMenu::item:selected {{ background: {t.surface_2}; }}
QMenu::item:disabled {{ color: {t.dim}; }}
QMenu::separator {{
    height: 1px;
    background: {t.border};
    margin: 5px 6px;
}}
"""
