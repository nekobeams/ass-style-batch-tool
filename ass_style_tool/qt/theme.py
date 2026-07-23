"""主題模式(跟隨系統/深色/淺色)決策與 QSS 套用。

深淺兩個主題共用同一份 QSS 樣板,只有配色不同——兩份平行的樣式字串很容易
在日後只改一邊而悄悄分岔。用 string.Template 而非 str.format,因為 QSS 本身
充滿大括號;用 substitute 而非 safe_substitute,配色漏欄位時要直接拋出。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from string import Template
from typing import Tuple

THEME_MODES: Tuple[str, ...] = ("system", "dark", "light")


@dataclass(frozen=True)
class _Palette:
    window_bg: str        # 視窗底色
    text: str             # 主要文字
    text_dim: str         # 次要文字(表頭、未選分頁)
    field_bg: str         # 輸入框/清單底色
    row_alt: str          # 交錯列底色
    row_hover: str        # hover 列底色
    border: str           # 一般邊框
    border_light: str     # 列分隔線(比一般邊框更淡)
    surface: str          # 按鈕/分頁/表頭底色
    surface_hover: str    # 按鈕 hover
    accent: str           # 強調色(主要按鈕、分頁上緣線、進度條)
    accent_hover: str
    accent_text: str      # 強調色底上的文字
    selection_bg: str     # 選取列底色
    selection_text: str   # 選取列文字(深淺主題不同,故獨立欄位)
    disabled_text: str


_DARK = _Palette(
    window_bg="#1e1e1e", text="#e6e6e6", text_dim="#b8b8b8",
    field_bg="#252525", row_alt="#232323", row_hover="#2f2f2f",
    border="#3d3d3d", border_light="#333333",
    surface="#2d2d2d", surface_hover="#3a3a3a",
    accent="#0e639c", accent_hover="#1177bb", accent_text="#ffffff",
    selection_bg="#264f78", selection_text="#ffffff",
    disabled_text="#707070",
)

_LIGHT = _Palette(
    window_bg="#f3f3f3", text="#202020", text_dim="#505050",
    field_bg="#ffffff", row_alt="#f7f7f7", row_hover="#eaeaea",
    border="#c8c8c8", border_light="#e0e0e0",
    surface="#e8e8e8", surface_hover="#dcdcdc",
    accent="#0a6ebd", accent_hover="#0d82db", accent_text="#ffffff",
    selection_bg="#cce4f7", selection_text="#202020",
    disabled_text="#a0a0a0",
)

_QSS_TEMPLATE = Template("""
QMainWindow, QWidget { background-color: $window_bg; color: $text; }

QTabWidget::pane { border: 1px solid $border; }
QTabBar::tab {
    background: $surface; color: $text_dim; padding: 6px 14px;
    border-top: 2px solid transparent;
}
QTabBar::tab:selected {
    background: $window_bg; color: $text; border-top: 2px solid $accent;
}

QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit {
    background-color: $field_bg; color: $text; border: 1px solid $border;
    selection-background-color: $selection_bg; selection-color: $selection_text;
}

QTreeWidget, QTableWidget {
    background-color: $field_bg; color: $text; border: 1px solid $border;
    alternate-background-color: $row_alt;
    gridline-color: $border_light;
    selection-background-color: $selection_bg;
    selection-color: $selection_text;
}
QTreeWidget::item, QTableWidget::item {
    border-bottom: 1px solid $border_light;
}
QTreeWidget::item:hover, QTableWidget::item:hover {
    background-color: $row_hover;
}
QTreeWidget::item:selected, QTableWidget::item:selected {
    background-color: $selection_bg; color: $selection_text;
}

QHeaderView::section {
    background-color: $surface; color: $text_dim;
    border: 1px solid $border; padding: 4px;
}

QPushButton {
    background-color: $surface; color: $text; border: 1px solid $border;
    padding: 5px 12px; border-radius: 3px;
}
QPushButton:hover { background-color: $surface_hover; }
QPushButton:disabled { color: $disabled_text; background-color: $field_bg; }
QPushButton[accent="true"] {
    background-color: $accent; color: $accent_text;
    border: 1px solid $accent_hover;
}
QPushButton[accent="true"]:hover { background-color: $accent_hover; }
QPushButton[accent="true"]:disabled {
    background-color: $field_bg; color: $disabled_text;
    border: 1px solid $border;
}

QScrollBar:vertical { background: $surface; width: 12px; margin: 0; }
QScrollBar::handle:vertical {
    background: $border; min-height: 24px; border-radius: 3px;
}
QScrollBar::handle:vertical:hover { background: $surface_hover; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: $surface; height: 12px; margin: 0; }
QScrollBar::handle:horizontal {
    background: $border; min-width: 24px; border-radius: 3px;
}
QScrollBar::handle:horizontal:hover { background: $surface_hover; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QGroupBox {
    border: 1px solid $border; border-radius: 3px;
    margin-top: 8px; padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 8px; padding: 0 4px; color: $text_dim;
}

QProgressBar {
    background-color: $field_bg; border: 1px solid $border;
    border-radius: 3px; text-align: center; color: $text;
}
QProgressBar::chunk { background-color: $accent; }
""")


def resolve_theme(mode: str, system_is_dark: bool) -> str:
    """把 mode + 系統狀態解析成實際主題 'dark' 或 'light'。"""
    if mode == "dark":
        return "dark"
    if mode == "light":
        return "light"
    if mode == "system":
        return "dark" if system_is_dark else "light"
    return "light"  # 未知 mode 保底淺色


def qss_for(theme: str) -> str:
    palette = _DARK if theme == "dark" else _LIGHT
    return _QSS_TEMPLATE.substitute(asdict(palette))


def system_is_dark(app) -> bool:
    """用 Qt 6.5+ 的 colorScheme 判斷系統是否深色;取不到則視為淺色。"""
    from PySide6.QtCore import Qt
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except (AttributeError, TypeError):
        return False


def apply_theme(app, mode: str) -> str:
    theme = resolve_theme(mode, system_is_dark(app))
    # Windows 原生樣式(windowsvista/windows11)不會完整套用 QWidget 的
    # background-color 泛用規則,只有明確選取的控件(QPushButton 等)才會生效,
    # 導致視窗空白背景維持系統原色不隨主題切換。Fusion 樣式完整遵守 QSS。
    if app.style().objectName().lower() != "fusion":
        app.setStyle("Fusion")
    app.setStyleSheet(qss_for(theme))
    return theme


def apply_titlebar_theme(window, dark: bool) -> None:
    """讓 Windows 原生標題列跟隨 app 深/淺主題。

    QSS 無法觸及作業系統繪製的標題列;標題列的深/淺由 DWM 的
    DWMWA_USE_IMMERSIVE_DARK_MODE 屬性控制。非 Windows 平台為 no-op。
    """
    import sys
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = int(window.winId())
        value = ctypes.c_int(1 if dark else 0)
        dwm = ctypes.windll.dwmapi
        # 20 = Windows 10 20H1+/Windows 11;19 = 較舊的 Windows 10 建置
        for attr in (20, 19):
            if dwm.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), ctypes.c_int(attr),
                ctypes.byref(value), ctypes.sizeof(value),
            ) == 0:
                break
    except Exception:
        pass  # 標題列著色失敗不影響功能
