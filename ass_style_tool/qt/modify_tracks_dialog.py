"""「修改既有軌道」對話框:純 UI over 一批 MediaTrack,回傳 Dict[int, TrackEdit]。"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QDialog, QDialogButtonBox, QHBoxLayout,
                               QHeaderView, QLineEdit, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..mkv_io import MediaTrack
from ..track_edit import TrackEdit
from ..track_info import build_track_info_rows

_TYPE_LABELS = {"video": "影片", "audio": "音訊", "subtitles": "字幕"}
_TRISTATE = [("不變", None), ("是", True), ("否", False)]
_COLS = ["保留", "類型", "編碼", "語言", "軌名", "預設", "強制"]
_INFO_COLS = ["影片", "找到", "預設", "強制", "軌名", "語言"]
_TRISTATE_TEXT = {True: "是", False: "否", None: ""}


class ModifyTracksDialog(QDialog):
    def __init__(self, tracks_by_file: Dict[Path, List[MediaTrack]],
                 existing: Optional[Dict[int, TrackEdit]] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("修改既有軌道")
        self._tracks_by_file = dict(tracks_by_file)
        # 範本取排序後、實際有軌道的第一個檔案——與資訊面板的排序一致,
        # 但跳過讀不到軌道(list_all_tracks 失敗回傳 [])的檔案,否則
        # 剛好排最前面的那個壞檔會讓整個對話框空白,OK 後清空所有設定。
        first = next(
            (p for p in sorted(self._tracks_by_file, key=lambda p: p.name)
             if self._tracks_by_file[p]),
            None)
        self._tracks = list(self._tracks_by_file[first]) if first else []
        existing = existing or {}
        self._keep_checks: List[QCheckBox] = []
        self._lang_edits: List[QLineEdit] = []
        self._name_edits: List[QLineEdit] = []
        self._default_combos: List[QComboBox] = []
        self._forced_combos: List[QComboBox] = []

        root = QVBoxLayout(self)
        self.table = QTableWidget(len(self._tracks), len(_COLS))
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        for r, t in enumerate(self._tracks):
            e = existing.get(t.track_id)
            if (e is not None and e.track_type is not None
                    and e.track_type != t.track_type):
                # 同一個 ID 曾經是別種軌道設定的——這批範本裡它是另一種
                # 軌道,套用會重演 prefill 把設定「改型別」帶過去的問題,
                # 視為沒有既有設定。
                e = None
            if e is None:
                e = TrackEdit()
            keep = QCheckBox()
            keep.setChecked(e.keep)
            self.table.setCellWidget(r, 0, self._center(keep))
            self._keep_checks.append(keep)
            self.table.setItem(
                r, 1, QTableWidgetItem(_TYPE_LABELS.get(t.track_type,
                                                        t.track_type)))
            self.table.setItem(r, 2, QTableWidgetItem(t.codec_id))
            lang = QLineEdit(e.language or "")
            lang.setPlaceholderText(t.language or "und")
            lang.setStyleSheet("QLineEdit { background: transparent; }")
            self.table.setCellWidget(r, 3, lang)
            self._lang_edits.append(lang)
            name = QLineEdit(e.track_name or "")
            name.setPlaceholderText(t.track_name)
            name.setStyleSheet("QLineEdit { background: transparent; }")
            self.table.setCellWidget(r, 4, name)
            self._name_edits.append(name)
            dcombo = self._tristate_combo(e.set_default)
            self.table.setCellWidget(r, 5, dcombo)
            self._default_combos.append(dcombo)
            fcombo = self._tristate_combo(e.set_forced)
            self.table.setCellWidget(r, 6, fcombo)
            self._forced_combos.append(fcombo)
        root.addWidget(self.table)

        self.info_table = QTableWidget(0, len(_INFO_COLS))
        self.info_table.setHorizontalHeaderLabels(_INFO_COLS)
        self.info_table.setAlternatingRowColors(True)
        self.info_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.info_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.info_table.verticalHeader().setVisible(False)
        self.info_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        root.addWidget(self.info_table)
        self.table.itemSelectionChanged.connect(self._refresh_info_table)
        if self._tracks:
            self.table.selectRow(0)      # 開啟時就有內容
        self._refresh_info_table()

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

    def _tristate_combo(self, value: Optional[bool]) -> QComboBox:
        combo = QComboBox()
        combo.setStyleSheet("QComboBox { background: transparent; }")
        for label, val in _TRISTATE:
            combo.addItem(label, val)
        combo.setCurrentIndex([v for _, v in _TRISTATE].index(value))
        return combo

    def _selected_track(self) -> Optional[MediaTrack]:
        row = self.table.currentRow()
        if 0 <= row < len(self._tracks):
            return self._tracks[row]
        return None

    def _refresh_info_table(self) -> None:
        track = self._selected_track()
        if track is None:
            self.info_table.setRowCount(0)
            return
        rows = build_track_info_rows(
            track.track_id, track.track_type, self._tracks_by_file)
        self.info_table.setRowCount(len(rows))
        for r, info in enumerate(rows):
            if not info.found:
                found_text = "✗"
            elif not info.type_matches:
                # 這正是面板要讓使用者看見的情況:同一個 ID 是別種軌道
                found_text = (f"⚠ 類型不符({_TYPE_LABELS.get(track.track_type, track.track_type)}"
                              f" → {_TYPE_LABELS.get(info.track_type, info.track_type)}),不會套用")
            else:
                found_text = "✓"
            values = [
                info.video_name, found_text,
                _TRISTATE_TEXT[info.default], _TRISTATE_TEXT[info.forced],
                info.track_name, info.language,
            ]
            for c, text in enumerate(values):
                self.info_table.setItem(r, c, QTableWidgetItem(text))

    def get_edits(self) -> Dict[int, TrackEdit]:
        edits: Dict[int, TrackEdit] = {}
        for r, t in enumerate(self._tracks):
            lang = self._lang_edits[r].text().strip()
            name = self._name_edits[r].text().strip()
            edits[t.track_id] = TrackEdit(
                keep=self._keep_checks[r].isChecked(),
                set_default=self._default_combos[r].currentData(),
                set_forced=self._forced_combos[r].currentData(),
                language=lang or None,
                track_name=name or None,
                track_type=t.track_type,
            )
        return edits
