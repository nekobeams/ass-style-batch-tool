"""v2 Qt 主視窗外殼:分頁籤、主題切換、log、QSettings 持久化。"""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow,
                               QMenu, QPlainTextEdit, QPushButton, QSplitter,
                               QTabWidget, QVBoxLayout, QWidget)

from .theme import THEME_MODES, apply_theme, apply_titlebar_theme
from .preview_panel import PreviewPanel
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

        # 頂列:主題切換圖示按鈕(靠右;點開選單選 跟隨系統/深色/淺色)
        self._theme_mode = "system"
        top = QHBoxLayout()
        top.setContentsMargins(8, 8, 12, 4)
        top.addStretch(1)
        self.theme_button = QPushButton("☀ / 🌙")
        self.theme_button.setStyleSheet(
            "QPushButton { font-size: 13px; padding: 0px 8px 2px 12px; "
            "min-height: 26px; max-height: 26px; text-align: center; }")
        self._theme_menu = QMenu(self)
        self._theme_group = QActionGroup(self._theme_menu)
        self._theme_group.setExclusive(True)
        self._theme_actions = {}
        for mode in THEME_MODES:
            action = QAction(_MODE_LABELS[mode], self._theme_menu, checkable=True)
            action.setData(mode)
            self._theme_group.addAction(action)
            self._theme_menu.addAction(action)
            self._theme_actions[mode] = action
        self._theme_actions["system"].setChecked(True)
        self._theme_menu.triggered.connect(self._on_theme_menu)
        # 用 QPushButton + 手動彈出選單,避免 QToolButton.setMenu() 的下拉箭頭
        # 在 Fusion 樣式下保留版面空間、把內容擠偏的問題。
        self.theme_button.clicked.connect(self._show_theme_menu)
        top.addWidget(self.theme_button)
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

        self.preview_panel = PreviewPanel(self.style_editor.current_profile)
        self._preview_split = QSplitter()
        self._preview_split.addWidget(self.style_editor)
        self._preview_split.addWidget(self.preview_panel)
        self._preview_split.setStretchFactor(1, 1)
        self.tabs.addTab(self._preview_split, "樣式與預覽")
        self.style_editor.values_changed.connect(
            self.preview_panel.on_style_changed)
        self.subtitle_tab.preview_requested.connect(self._open_in_preview)
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
        return self._theme_mode

    def _apply_current_theme(self) -> None:
        resolved = apply_theme(QApplication.instance(), self.current_mode())
        apply_titlebar_theme(self, resolved == "dark")
        # 目前狀態放 tooltip 與選單勾選;按鈕維持 ☀ / 🌙 靜態圖示
        mode_label = _MODE_LABELS.get(self.current_mode(), self.current_mode())
        resolved_label = "深色" if resolved == "dark" else "淺色"
        self.theme_button.setToolTip(
            f"切換主題(目前:{mode_label},套用:{resolved_label})")

    def _show_theme_menu(self) -> None:
        pos = self.theme_button.mapToGlobal(self.theme_button.rect().bottomLeft())
        self._theme_menu.exec(pos)

    def _on_theme_menu(self, action) -> None:
        mode = action.data()
        if mode == self._theme_mode:
            return
        self._theme_mode = mode
        self.settings.setValue("theme_mode", mode)
        self._apply_current_theme()
        self.append_log(f"主題切換為:{_MODE_LABELS.get(mode, mode)}")

    def _on_system_scheme_changed(self, _scheme) -> None:
        if self.current_mode() == "system":
            self._apply_current_theme()

    def _open_in_preview(self, sub_path, video_path) -> None:
        self.preview_panel.set_media(sub_path, video_path)
        self.tabs.setCurrentWidget(self._preview_split)
        if video_path is None:
            self.append_log("該列未配對到影片,預覽僅載入字幕行清單;"
                            "可在預覽分頁手動開啟影片")

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
        if mode in self._theme_actions:
            self._theme_mode = mode
            self._theme_actions[mode].setChecked(True)
        self._apply_current_theme()

    def closeEvent(self, event) -> None:
        self.subtitle_tab.shutdown()
        self.preview_panel.shutdown()
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("theme_mode", self.current_mode())
        super().closeEvent(event)


def main() -> None:
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec()
