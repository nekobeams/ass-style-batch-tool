"""v2 Qt 主視窗外殼:分頁籤、主題切換、log、QSettings 持久化。"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel,
                               QMainWindow, QPlainTextEdit, QTabWidget,
                               QVBoxLayout, QWidget)

from .theme import (THEME_MODES, apply_theme, apply_titlebar_theme,
                    system_is_dark)
from .style_editor import StyleEditor
from .subtitle_tab import SubtitleFileTab

_MODE_LABELS = {"system": "跟隨系統", "dark": "深色", "light": "淺色"}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ASS 字幕樣式批次工具")
        self.settings = QSettings("ass-style-tool", "ass-style-tool")

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # 頂列:主題切換(靠右,留邊距避免文字貼齊視窗邊緣)
        top = QHBoxLayout()
        top.setContentsMargins(8, 8, 12, 4)
        top.addStretch(1)
        top.addWidget(QLabel("主題:"))
        self.theme_combo = QComboBox()
        for mode in THEME_MODES:
            self.theme_combo.addItem(_MODE_LABELS[mode], mode)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        top.addWidget(self.theme_combo)
        layout.addLayout(top)

        # 分頁籤
        self.tabs = QTabWidget()
        self.style_editor = StyleEditor()
        self.subtitle_tab = SubtitleFileTab(self.style_editor.current_profile)
        self.subtitle_tab.log.connect(self.append_log)

        self.tabs.addTab(self.subtitle_tab, "字幕檔")

        mkv_page = QWidget()
        mkv_layout = QVBoxLayout(mkv_page)
        mkv_layout.addWidget(QLabel("（MKV 功能於後續計畫實作）"))
        mkv_layout.addStretch(1)
        self.tabs.addTab(mkv_page, "MKV")

        self.tabs.addTab(self.style_editor, "樣式與預覽")
        layout.addWidget(self.tabs, 1)

        # log 區
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        layout.addWidget(self.log_view, 1)

        self._restore_settings()
        # 跟隨系統模式下,監聽系統主題變更即時重套
        QApplication.instance().styleHints().colorSchemeChanged.connect(
            self._on_system_scheme_changed)

    # ---------- 主題 ----------
    def current_mode(self) -> str:
        return self.theme_combo.currentData()

    def _apply_current_theme(self) -> None:
        resolved = apply_theme(QApplication.instance(), self.current_mode())
        apply_titlebar_theme(self, resolved == "dark")

    def _on_theme_changed(self) -> None:
        mode = self.current_mode()
        self.settings.setValue("theme_mode", mode)
        self._apply_current_theme()
        self.append_log(f"主題切換為:{_MODE_LABELS.get(mode, mode)}")

    def _on_system_scheme_changed(self, _scheme) -> None:
        if self.current_mode() == "system":
            self._apply_current_theme()

    # ---------- log ----------
    def append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    # ---------- 設定持久化 ----------
    def _restore_settings(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1000, 700)
        mode = self.settings.value("theme_mode", "system")
        index = self.theme_combo.findData(mode)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        self._apply_current_theme()

    def closeEvent(self, event) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("theme_mode", self.current_mode())
        super().closeEvent(event)


def main() -> None:
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec()
