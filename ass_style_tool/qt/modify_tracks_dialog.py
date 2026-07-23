"""「修改既有軌道」對話框:純 UI over 一批 MediaTrack,回傳 Dict[int, TrackEdit]。"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QDialog, QDialogButtonBox, QHBoxLayout,
                               QHeaderView, QLineEdit, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..mkv_io import MediaTrack
from ..track_edit import TrackEdit

_TYPE_LABELS = {"video": "影片", "audio": "音訊", "subtitles": "字幕"}
_TRISTATE = [("不變", None), ("是", True), ("否", False)]
_COLS = ["保留", "類型", "編碼", "語言", "軌名", "預設", "強制"]


class ModifyTracksDialog(QDialog):
    def __init__(self, tracks: List[MediaTrack],
                 existing: Optional[Dict[int, TrackEdit]] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("修改既有軌道")
        self._tracks = list(tracks)
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
            e = existing.get(t.track_id, TrackEdit())
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
            )
        return edits
