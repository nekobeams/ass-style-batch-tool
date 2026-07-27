"""「修改既有軌道」對話框(MKV 分頁):選出哪幾條舊字幕軌要重新套樣式。

刻意與封裝分頁的 ModifyTracksDialog 同一種心智模型——上半在範本檔上定
規則、下半逐檔驗證。差別在這裡的鍵是 (語言, 軌名) 而不是軌 ID:同一季裡
某集多一條音訊軌就會把字幕軌的 ID 推掉,依 ID 會套到別的語言上。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Set

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog,
                               QDialogButtonBox, QHBoxLayout, QHeaderView,
                               QLabel, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..mkv_batch import track_key
from ..mkv_io import SubtitleTrack
from ..track_select import (TrackKey, build_select_info_rows,
                            uncovered_track_count)

_COLS = ["套樣式", "軌 ID", "語言", "軌名"]
_INFO_COLS = ["影片", "解析結果"]


class SelectTracksDialog(QDialog):
    def __init__(self, files_tracks: Dict[Path, List[SubtitleTrack]],
                 existing: Optional[Set[TrackKey]] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("修改既有軌道")
        self._files_tracks = dict(files_tracks)
        # 範本取排序後、實際有 ASS 字幕軌的第一個檔案:跳過讀不到軌的壞檔,
        # 否則剛好排最前面的那個壞檔會讓對話框空白,按確定後清光所有設定。
        first = next(
            (p for p in sorted(self._files_tracks, key=lambda p: p.name)
             if self._files_tracks[p]),
            None)
        self._tracks: List[SubtitleTrack] = (
            list(self._files_tracks[first]) if first is not None else [])
        self._checks: List[QCheckBox] = []

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "勾選要重新套用樣式的字幕軌。規則依「語言 + 軌名」套用到整批影片。"))

        self.table = QTableWidget(len(self._tracks), len(_COLS))
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch)
        for r, track in enumerate(self._tracks):
            check = QCheckBox()
            # existing 為 None = 從未設定過 -> 預設全勾(維持舊行為:掃完
            # 全部勾起來,想排除哪條再自己取消)
            check.setChecked(True if existing is None
                             else track_key(track) in existing)
            check.toggled.connect(self._refresh_summary)
            self.table.setCellWidget(r, 0, self._center(check))
            self._checks.append(check)
            self.table.setItem(r, 1, QTableWidgetItem(str(track.track_id)))
            self.table.setItem(r, 2, QTableWidgetItem(track.language or "und"))
            self.table.setItem(r, 3, QTableWidgetItem(track.track_name or "-"))
        root.addWidget(self.table)

        self.info_table = QTableWidget(0, len(_INFO_COLS))
        self.info_table.setHorizontalHeaderLabels(_INFO_COLS)
        self.info_table.setAlternatingRowColors(True)
        self.info_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.info_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.info_table.verticalHeader().setVisible(False)
        self.info_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        root.addWidget(self.info_table)
        self.table.itemSelectionChanged.connect(self._refresh_info_table)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        if self._tracks:
            self.table.selectRow(0)      # 開啟時就有內容
        self._refresh_info_table()
        self._refresh_summary()

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _center(self, w: QWidget) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("QWidget { background: transparent; }")
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(w)
        return wrap

    def _selected_track(self) -> Optional[SubtitleTrack]:
        row = self.table.currentRow()
        if 0 <= row < len(self._tracks):
            return self._tracks[row]
        return None

    def _refresh_info_table(self) -> None:
        track = self._selected_track()
        if track is None:
            self.info_table.setRowCount(0)
            return
        rows = build_select_info_rows(track_key(track), self._files_tracks)
        self.info_table.setRowCount(len(rows))
        for r, info in enumerate(rows):
            if not info.track_ids:
                text = "✗ 沒有符合的軌"
            elif len(info.track_ids) == 1:
                text = f"✓ 軌 {info.track_ids[0]}"
            else:
                # 這正是面板要讓使用者看見的情況:同一個鍵命中多條軌
                ids = "、".join(f"軌 {i}" for i in info.track_ids)
                text = f"⚠ 有 {len(info.track_ids)} 條符合({ids}),都會套用"
            self.info_table.setItem(r, 0, QTableWidgetItem(info.video_name))
            self.info_table.setItem(r, 1, QTableWidgetItem(text))

    def _refresh_summary(self) -> None:
        videos, tracks = uncovered_track_count(self.get_keys(),
                                               self._files_tracks)
        self.summary.setText(
            "" if not tracks else
            f"⚠ {videos} 部影片另有 {tracks} 條未勾選的 ASS 字幕軌,不會被套用")

    def get_keys(self) -> Set[TrackKey]:
        return {track_key(track)
                for track, check in zip(self._tracks, self._checks)
                if check.isChecked()}
