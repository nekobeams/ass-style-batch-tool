"""v2 Qt 主視窗外殼:分頁籤、主題切換、log、QSettings 持久化。"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (QApplication, QLabel, QMainWindow, QMenu,
                               QPlainTextEdit, QPushButton, QSplitter,
                               QTabWidget, QVBoxLayout, QWidget)

from .theme import (THEME_MODES, apply_theme, apply_titlebar_theme,
                    resolve_theme, system_is_dark)
from .mkv_tab import MkvTab
from .mux_tab import MuxTab
from .preview_panel import PreviewPanel
from .style_editor import StyleEditor
from .subtitle_tab import SubtitleFileTab

_MODE_LABELS = {"system": "跟隨系統", "dark": "深色", "light": "淺色"}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Subtitle Style Batch Tool")
        self.settings = QSettings("ass-style-tool", "ass-style-tool")
        # I4(最終審查 Finding):StyleEditor 本身不認識任何分頁(存/讀
        # profile 的邏輯全部封在它自己裡面),只有這裡——同時組裝
        # StyleEditor 與三個工作分頁的地方——同時拿得到兩邊,所以「存檔
        # 該用哪個分頁的勾選」「載入後該把名字塞回哪個分頁」這兩個問題
        # 只能在這裡回答。追蹤的是「最後一個工作分頁」而不是「目前分頁」:
        # 「另存」/「載入」按鈕長在「樣式與預覽」分頁上,使用者的實際流程
        # 通常是先在字幕檔/封裝/MKV 分頁勾好樣式,再切到「樣式與預覽」
        # 按下按鈕,這時 tabs.currentWidget() 已經是沒有 style_picker 的
        # 分頁了,若不記住最後一個工作分頁,存檔時完全抓不到使用者剛才
        # 勾了什麼。
        self._last_work_tab = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # 主題切換圖示按鈕(點開選單選 跟隨系統/深色/淺色)。
        # 用 QTabWidget 的角落控件放到分頁籤同一列的右端,而不是自成一列——
        # 自成一列會佔掉一整條垂直空間,分頁內容還得再往下擠。
        self._theme_mode = "system"
        self.theme_button = QPushButton("☀ / 🌙")
        # 左右對稱的內距(原本是 0/8/2/12,看起來偏一邊)
        self.theme_button.setStyleSheet(
            "QPushButton { font-size: 13px; padding: 2px 10px; "
            "min-height: 24px; max-height: 24px; text-align: center; }")
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
        # 左鍵直接翻深/淺;右鍵才開選單(裡面才有「跟隨系統」)
        self.theme_button.clicked.connect(self._toggle_theme)
        self.theme_button.setContextMenuPolicy(Qt.CustomContextMenu)
        self.theme_button.customContextMenuRequested.connect(
            self._show_theme_menu)

        # 分頁籤
        self.tabs = QTabWidget()
        self.tabs.setCornerWidget(self.theme_button, Qt.TopRightCorner)
        self.style_editor = StyleEditor(
            get_target_style_names=self._active_tab_selected_styles)
        self.style_editor.profile_loaded.connect(
            self._apply_target_style_names_to_active_tab)
        self.subtitle_tab = SubtitleFileTab(self.style_editor.current_profile)
        self.subtitle_tab.log.connect(self.append_log)

        self.tabs.addTab(self.subtitle_tab, "字幕檔")

        self.mkv_tab = MkvTab(self.style_editor.current_profile)
        self.mkv_tab.log.connect(self.append_log)
        self.mkv_tab.preview_requested.connect(self._open_in_preview)
        self.tabs.addTab(self.mkv_tab, "MKV")

        self.mux_tab = MuxTab(self.style_editor.current_profile)
        self.mux_tab.log.connect(self.append_log)
        self.tabs.addTab(self.mux_tab, "封裝")

        self.preview_panel = PreviewPanel(self.style_editor.current_profile)
        self.preview_panel.readout_changed.connect(
            self.style_editor.readout_view.update_from)
        self._preview_split = QSplitter()
        self._preview_split.addWidget(self.style_editor)
        self._preview_split.addWidget(self.preview_panel)
        self._preview_split.setStretchFactor(1, 1)
        self.tabs.addTab(self._preview_split, "樣式與預覽")
        self.style_editor.values_changed.connect(
            self.preview_panel.on_style_changed)
        self.subtitle_tab.preview_requested.connect(self._open_in_preview)
        layout.addWidget(self.tabs, 1)

        # log 區(狀態訊息用,固定較矮的高度,不與分頁爭奪垂直空間)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setMaximumHeight(150)
        layout.addWidget(self.log_view)

        self._restore_settings()
        # 跟隨系統模式下,監聽系統主題變更即時重套
        QApplication.instance().styleHints().colorSchemeChanged.connect(
            self._on_system_scheme_changed)

        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed(self.tabs.currentIndex())

    # ---------- 主題 ----------
    def current_mode(self) -> str:
        return self._theme_mode

    def _apply_current_theme(self) -> None:
        resolved = apply_theme(QApplication.instance(), self.current_mode())
        apply_titlebar_theme(self, resolved == "dark")
        mode_label = _MODE_LABELS.get(self.current_mode(), self.current_mode())
        resolved_label = "深色" if resolved == "dark" else "淺色"
        # 按鈕固定顯示 ☀ / 🌙,不隨模式改變;目前是自動還是手動鎖定,
        # 由 tooltip 與右鍵選單的勾選呈現。
        self.theme_button.setToolTip(
            f"點擊切換深/淺,右鍵選擇跟隨系統"
            f"(目前:{mode_label},套用:{resolved_label})")

    def _toggle_theme(self) -> None:
        """左鍵:直接在深/淺之間翻面。

        以「目前實際套用的結果」為起點,而不是以模式為起點——這樣不論原本是
        跟隨系統還是手動鎖定,按下去必定看得到顏色改變。
        """
        resolved = resolve_theme(
            self.current_mode(), system_is_dark(QApplication.instance()))
        self._set_theme_mode("light" if resolved == "dark" else "dark")

    def _set_theme_mode(self, mode: str) -> None:
        if mode == self._theme_mode:
            return
        self._theme_mode = mode
        # 左鍵切換時也要同步選單勾選,否則右鍵打開會顯示過期的狀態
        if mode in self._theme_actions:
            self._theme_actions[mode].setChecked(True)
        self.settings.setValue("theme_mode", mode)
        self._apply_current_theme()
        self.append_log(f"主題切換為:{_MODE_LABELS.get(mode, mode)}")

    def _show_theme_menu(self, _pos=None) -> None:
        pos = self.theme_button.mapToGlobal(self.theme_button.rect().bottomLeft())
        self._theme_menu.exec(pos)

    def _on_theme_menu(self, action) -> None:
        self._set_theme_mode(action.data())

    def _on_system_scheme_changed(self, _scheme) -> None:
        if self.current_mode() == "system":
            self._apply_current_theme()

    def _open_in_preview(self, sub_path, video_path) -> None:
        self.preview_panel.set_media(sub_path, video_path)
        self.tabs.setCurrentWidget(self._preview_split)
        if video_path is None:
            self.append_log("該列未配對到影片,預覽僅載入字幕行清單;"
                            "可在預覽分頁手動開啟影片")

    def _on_tab_changed(self, index: int) -> None:
        """分頁第一次被顯示時才掃描它的資料夾。

        開啟時三個分頁全掃,等於為使用者沒要看的分頁白跑 ffprobe 子行程
        (一季 24 集約 1-5 秒),所以改成用到才掃。
        """
        widget = self.tabs.widget(index)
        # I4:記住「最後一個工作分頁」,供 StyleEditor 存/讀 profile 時
        # 對應 target_style_names(見 __init__ 對 _last_work_tab 的說明)。
        # 「樣式與預覽」分頁(self._preview_split,一個 QSplitter)沒有
        # style_picker,切過去不會覆蓋這個記憶。
        if hasattr(widget, "style_picker"):
            self._last_work_tab = widget
        auto_scan = getattr(widget, "auto_scan_once", None)
        if callable(auto_scan):
            auto_scan()

    # ---------- I4:profile 存/讀與分頁的 target_style_names 對應 ----------
    def _active_tab_selected_styles(self) -> Optional[List[str]]:
        """存檔要用的 target_style_names 來源(注入給 StyleEditor)。

        回傳 None 代表現在判斷不出「哪個分頁的勾選才是使用者要存的」
        (例如程式剛啟動、_on_tab_changed 還沒被觸發過一次)——StyleEditor
        收到 None 時會落回它自己那份隱藏值,不會被空清單覆蓋掉。
        """
        tab = self._last_work_tab
        return tab.style_picker.selected() if tab is not None else None

    def _apply_target_style_names_to_active_tab(self, names: list) -> None:
        """StyleEditor 載入 profile 後(profile_loaded 訊號),把它的
        target_style_names 餵給最後一個作用中的工作分頁,讓那個分頁的
        勾選跟著換過去——不然「載入 profile」對任何分頁的畫面都毫無
        效果,使用者只會看到編輯器欄位變了,分頁裡的勾選(以及依它算出
        的「預計」欄、執行按鈕的啟用狀態)完全沒反應。
        """
        tab = self._last_work_tab
        if tab is not None:
            tab.style_picker.set_selected(list(names))

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
        self.style_editor.restore_settings(self.settings)
        self.subtitle_tab.restore_settings(self.settings)
        self.mkv_tab.restore_settings(self.settings)
        self.mux_tab.restore_settings(self.settings)
        self._apply_current_theme()

    def closeEvent(self, event) -> None:
        self.subtitle_tab.shutdown()
        self.preview_panel.shutdown()
        self.mkv_tab.shutdown()
        self.mux_tab.shutdown()
        self.style_editor.save_settings(self.settings)
        self.subtitle_tab.save_settings(self.settings)
        self.mkv_tab.save_settings(self.settings)
        self.mux_tab.save_settings(self.settings)
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("theme_mode", self.current_mode())
        super().closeEvent(event)


def main() -> None:
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec()
