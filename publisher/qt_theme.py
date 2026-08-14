import json
from pathlib import Path

from PySide6.QtWidgets import QApplication


DEFAULT_THEME = "Codex 浅色"
THEMES: dict[str, dict[str, str]] = {
    "Codex 浅色": {
        "canvas": "#F6F6F7",
        "surface": "#FFFFFF",
        "sidebar": "#EFEFF0",
        "header": "#FFFFFF",
        "text": "#1F1F1F",
        "muted": "#737373",
        "border": "#E2E2E3",
        "primary": "#1F1F1F",
        "primary_text": "#FFFFFF",
        "primary_hover": "#000000",
        "focus": "#3A3A3A",
        "secondary": "#F3F3F3",
        "secondary_hover": "#E8E8E8",
        "selection": "#E8E8E8",
        "status": "#F0F0F0",
    },
    "Codex 柔白": {
        "canvas": "#FBFBFC",
        "surface": "#FFFFFF",
        "sidebar": "#F6F6F7",
        "header": "#FFFFFF",
        "text": "#1A1A1A",
        "muted": "#777777",
        "border": "#E7E7E8",
        "primary": "#2A2A2A",
        "primary_text": "#FFFFFF",
        "primary_hover": "#000000",
        "focus": "#353535",
        "secondary": "#F5F5F6",
        "secondary_hover": "#E9E9EA",
        "selection": "#ECECED",
        "status": "#F3F3F4",
    },
    "Codex 深色": {
        "canvas": "#212121",
        "surface": "#2B2B2B",
        "sidebar": "#171717",
        "header": "#202020",
        "text": "#ECECEC",
        "muted": "#B1B1B1",
        "border": "#474747",
        "primary": "#F1F1F1",
        "primary_text": "#202020",
        "primary_hover": "#DCDCDC",
        "focus": "#BEBEBE",
        "secondary": "#393939",
        "secondary_hover": "#484848",
        "selection": "#454545",
        "status": "#343434",
    },
    "Codex 黑曜": {
        "canvas": "#0D0D0D",
        "surface": "#171717",
        "sidebar": "#111111",
        "header": "#0D0D0D",
        "text": "#F0F0F0",
        "muted": "#AAAAAA",
        "border": "#383838",
        "primary": "#FFFFFF",
        "primary_text": "#111111",
        "primary_hover": "#DEDEDE",
        "focus": "#D0D0D0",
        "secondary": "#252525",
        "secondary_hover": "#313131",
        "selection": "#363636",
        "status": "#242424",
    },
    "Codex 石墨": {
        "canvas": "#242424",
        "surface": "#2E2E2E",
        "sidebar": "#1D1D1D",
        "header": "#242424",
        "text": "#ECECEC",
        "muted": "#B4B4B4",
        "border": "#4B4B4B",
        "primary": "#D46A4C",
        "primary_text": "#FFFFFF",
        "primary_hover": "#BC563D",
        "focus": "#E09A86",
        "secondary": "#383838",
        "secondary_hover": "#494949",
        "selection": "#3B3B3B",
        "status": "#383838",
    },
    "Codex 暖灰": {
        "canvas": "#F5F4F2",
        "surface": "#FFFFFF",
        "sidebar": "#EEEDEB",
        "header": "#FFFFFF",
        "text": "#2C2B29",
        "muted": "#777570",
        "border": "#E1DFDB",
        "primary": "#403D39",
        "primary_text": "#FFFFFF",
        "primary_hover": "#242220",
        "focus": "#4D4A45",
        "secondary": "#F0EFED",
        "secondary_hover": "#E5E3E0",
        "selection": "#EAE8E4",
        "status": "#EDECE9",
    },
}


class QtThemeStore:
    def __init__(self, settings_path: Path | None) -> None:
        self._settings_path = settings_path

    def load(self) -> str:
        if self._settings_path is None or not self._settings_path.exists():
            return DEFAULT_THEME
        try:
            payload = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DEFAULT_THEME
        theme_name = payload.get("theme") if isinstance(payload, dict) else None
        return theme_name if theme_name in THEMES else DEFAULT_THEME

    def save(self, theme_name: str) -> None:
        if self._settings_path is None or theme_name not in THEMES:
            return
        try:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self._settings_path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps({"version": 4, "theme": theme_name}, ensure_ascii=False),
                encoding="utf-8",
            )
            temporary_path.replace(self._settings_path)
        except OSError:
            return


def apply_theme(theme_name: str) -> None:
    palette = THEMES.get(theme_name, THEMES[DEFAULT_THEME])
    application = QApplication.instance()
    if application is None:
        return
    application.setStyleSheet(
        f"""
        * {{
            color: {palette['text']};
            font-family: 'Microsoft YaHei UI', 'Segoe UI Variable Text', 'Segoe UI';
            font-size: 10pt;
        }}
        QMainWindow, QDialog, QWidget#workspace {{ background: {palette['canvas']}; }}
        QWidget#contentPane {{ background: {palette['canvas']}; }}
        QScrollArea {{ background: {palette['canvas']}; border: 0; }}
        QFrame#header {{ background: {palette['header']}; border-bottom: 1px solid {palette['border']}; }}
        QFrame#sidebar {{ background: {palette['sidebar']}; border-right: 1px solid {palette['border']}; }}
        QLabel#brand {{ font-size: 16pt; font-weight: 600; }}
        QLabel#pageTitle {{ font-size: 12pt; font-weight: 600; }}
        QLabel#taskStatus {{ background: {palette['status']}; border-radius: 4px; padding: 7px 10px; }}
        QLabel#muted {{ color: {palette['muted']}; }}
        QToolButton, QPushButton {{
            background: {palette['secondary']};
            border: 1px solid {palette['border']};
            border-radius: 4px;
            padding: 7px 11px;
        }}
        QToolButton:hover, QPushButton:hover {{ background: {palette['secondary_hover']}; }}
        QToolButton:disabled, QPushButton:disabled {{ color: {palette['muted']}; }}
        QPushButton[primary='true'] {{
            background: {palette['primary']}; color: {palette['primary_text']};
            border-color: {palette['primary']}; font-weight: 600;
        }}
        QPushButton[primary='true']:hover {{ background: {palette['primary_hover']}; }}
        QListWidget {{ background: transparent; border: 0; outline: 0; padding: 8px; }}
        QListWidget::item {{ border-radius: 4px; padding: 9px 10px; margin: 2px 0; }}
        QListWidget::item:selected {{ background: {palette['selection']}; font-weight: 600; }}
        QLineEdit, QPlainTextEdit, QComboBox, QDateEdit, QSpinBox {{
            background: {palette['surface']}; border: 1px solid {palette['border']};
            border-radius: 4px; padding: 7px 9px; selection-background-color: {palette['selection']};
        }}
        QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus {{
            border: 1px solid {palette['focus']};
        }}
        QComboBox::drop-down {{ border: 0; width: 24px; }}
        QComboBox QAbstractItemView {{
            background: {palette['surface']}; border: 1px solid {palette['border']};
            selection-background-color: {palette['selection']};
        }}
        QCheckBox {{ spacing: 8px; }}
        QCheckBox::indicator {{
            width: 16px; height: 16px; background: {palette['surface']};
            border: 1px solid {palette['border']}; border-radius: 3px;
        }}
        QCheckBox::indicator:checked {{ background: {palette['primary']}; border-color: {palette['primary']}; }}
        QMenu {{ background: {palette['surface']}; border: 1px solid {palette['border']}; padding: 5px; }}
        QMenu::item {{ padding: 7px 24px 7px 10px; border-radius: 3px; }}
        QMenu::item:selected {{ background: {palette['selection']}; }}
        QProgressBar {{ background: {palette['status']}; border: 0; border-radius: 3px; }}
        QProgressBar::chunk {{ background: {palette['primary']}; border-radius: 3px; }}
        QTableWidget {{
            background: {palette['surface']}; border: 1px solid {palette['border']};
            gridline-color: {palette['border']}; selection-background-color: {palette['selection']};
        }}
        QHeaderView::section {{
            background: {palette['secondary']}; border: 0; border-bottom: 1px solid {palette['border']};
            padding: 7px; font-weight: 600;
        }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
        QScrollBar::handle:vertical {{ background: {palette['border']}; border-radius: 4px; min-height: 24px; }}
        QScrollBar::handle:vertical:hover {{ background: {palette['muted']}; }}
        """
    )
