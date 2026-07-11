"""預覽面板:mpv 播放器 + 字幕行清單 + 樣式變更 300ms 防抖熱重載。"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from ..ass_style import load_subs
from ..preview import render_preview_ass
from ..profile import Profile
from .gui_helpers import dialogue_lines, format_timestamp
from .player import MpvPlayerWidget

DEBOUNCE_MS = 300


class PreviewPanel(QWidget):
    def __init__(self, get_profile: Callable[[], Profile],
                 player: Optional[QWidget] = None) -> None:
        super().__init__()
        self._get_profile = get_profile
        self.player = player if player is not None else MpvPlayerWidget()
        self._source_sub: Optional[Path] = None
        self._temp_dir = Path(tempfile.mkdtemp(prefix="ass_style_preview_"))
        self._temp_ass = self._temp_dir / "preview.ass"

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        open_video = QPushButton("開啟影片…")
        open_video.clicked.connect(self._open_video)
        open_sub = QPushButton("載入字幕…")
        open_sub.clicked.connect(self._open_sub)
        pause = QPushButton("播放 / 暫停")
        pause.clicked.connect(self.player.toggle_pause)
        bar.addWidget(open_video)
        bar.addWidget(open_sub)
        bar.addWidget(pause)
        bar.addStretch(1)
        root.addLayout(bar)

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.player)
        self.line_list = QListWidget()
        self.line_list.itemClicked.connect(self._on_line_clicked)
        split.addWidget(self.line_list)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)

        self.status = QLabel("尚未載入字幕")
        root.addWidget(self.status)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._apply_preview)

    # ---------- 對外 ----------
    def set_media(self, sub_path: Path,
                  video_path: Optional[Path] = None) -> None:
        self._source_sub = Path(sub_path)
        if video_path is not None:
            self.player.load_video(Path(video_path))
        self._refresh_lines()
        self._apply_preview()

    def on_style_changed(self) -> None:
        if self._source_sub is not None:
            self._debounce.start()

    # ---------- 檔案選擇 ----------
    def _open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "開啟影片", "",
            "影片 (*.mkv *.mp4 *.avi *.webm *.ts);;所有檔案 (*)")
        if path:
            self.player.load_video(Path(path))
            self._apply_preview()

    def _open_sub(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "載入字幕", "", "ASS/SSA (*.ass *.ssa)")
        if path:
            self.set_media(Path(path))

    # ---------- 內部 ----------
    def _refresh_lines(self) -> None:
        self.line_list.clear()
        if self._source_sub is None:
            return
        try:
            subs = load_subs(self._source_sub)
        except Exception as exc:  # 單檔讀取失敗只顯示狀態,不中斷
            self.status.setText(f"字幕讀取失敗: {exc}")
            return
        for line in dialogue_lines(subs):
            item = QListWidgetItem(
                f"{format_timestamp(line.start_ms)}  {line.text}")
            item.setData(Qt.UserRole, line.start_ms)
            self.line_list.addItem(item)
        self.status.setText(
            f"{self._source_sub.name}(共 {self.line_list.count()} 行,點擊跳轉)")

    def _on_line_clicked(self, item: QListWidgetItem) -> None:
        self.player.seek(item.data(Qt.UserRole) / 1000.0)

    def _apply_preview(self) -> None:
        if self._source_sub is None:
            return
        try:
            profile = self._get_profile()
        except ValueError:
            return  # 欄位打到一半暫時無效,略過本次防抖
        try:
            render_preview_ass(self._source_sub, profile, self._temp_ass)
        except Exception as exc:
            self.status.setText(f"預覽產生失敗: {exc}")
            return
        if self.player.video_loaded():
            self.player.show_subtitle(self._temp_ass)

    def shutdown(self) -> None:
        self._debounce.stop()  # 防止已排定的防抖在關閉後對已清除的暫存目錄觸發
        self.player.shutdown()
        try:
            if self._temp_ass.exists():
                self._temp_ass.unlink()
            self._temp_dir.rmdir()
        except OSError:
            pass  # 暫存清理失敗不影響關閉
