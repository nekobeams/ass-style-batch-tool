"""主題模式(跟隨系統/深色/淺色)決策與 QSS 套用。"""
from __future__ import annotations

from typing import Tuple

THEME_MODES: Tuple[str, ...] = ("system", "dark", "light")

_DARK_QSS = """
QMainWindow, QWidget { background-color: #1e1e1e; color: #e0e0e0; }
QTabWidget::pane { border: 1px solid #3a3a3a; }
QTabBar::tab { background: #2a2a2a; color: #c0c0c0; padding: 6px 14px; }
QTabBar::tab:selected { background: #3a3a3a; color: #ffffff; }
QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit, QTableWidget {
    background-color: #2a2a2a; color: #e0e0e0; border: 1px solid #3a3a3a;
    selection-background-color: #4a6a8a;
}
QPushButton {
    background-color: #333333; color: #e0e0e0; border: 1px solid #4a4a4a;
    padding: 5px 12px;
}
QPushButton:hover { background-color: #3f3f3f; }
QPushButton:disabled { color: #707070; background-color: #2a2a2a; }
QHeaderView::section { background-color: #2a2a2a; color: #c0c0c0; border: 1px solid #3a3a3a; }
"""

_LIGHT_QSS = """
QMainWindow, QWidget { background-color: #f3f3f3; color: #202020; }
QTabWidget::pane { border: 1px solid #c8c8c8; }
QTabBar::tab { background: #e4e4e4; color: #404040; padding: 6px 14px; }
QTabBar::tab:selected { background: #ffffff; color: #000000; }
QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit, QTableWidget {
    background-color: #ffffff; color: #202020; border: 1px solid #c8c8c8;
    selection-background-color: #b0d0f0;
}
QPushButton {
    background-color: #e8e8e8; color: #202020; border: 1px solid #c0c0c0;
    padding: 5px 12px;
}
QPushButton:hover { background-color: #dcdcdc; }
QPushButton:disabled { color: #a0a0a0; background-color: #eeeeee; }
QHeaderView::section { background-color: #e4e4e4; color: #404040; border: 1px solid #c8c8c8; }
"""


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
    return _DARK_QSS if theme == "dark" else _LIGHT_QSS


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
