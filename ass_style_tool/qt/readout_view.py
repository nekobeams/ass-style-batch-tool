"""換算對照讀出的純顯示元件:收 ReadoutData 渲染,不認識 profile/檔案/影片。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (QAbstractItemView, QGroupBox, QHeaderView,
                               QLabel, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from ..preview_readout import ReadoutData

_PLACEHOLDER = "載入字幕檔後顯示換算結果"


class ReadoutView(QGroupBox):
    def __init__(self) -> None:
        super().__init__("換算對照(套用後的實際數字)")
        layout = QVBoxLayout(self)
        self.mechanism = QLabel(_PLACEHOLDER)
        self.mechanism.setWordWrap(True)
        self.context_sub = QLabel("")
        self.context_sub.setWordWrap(True)
        self.context_video = QLabel("")
        self.context_video.setWordWrap(True)
        self.missing = QLabel("")
        self.missing.setWordWrap(True)
        self.missing.hide()
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["樣式", "原字幕現值", "套用後"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMaximumHeight(200)
        self.table.hide()
        self.note = QLabel("")
        for w in (self.mechanism, self.context_sub, self.context_video,
                  self.missing, self.table, self.note):
            layout.addWidget(w)

    def update_from(self, data: Optional[ReadoutData]) -> None:
        if data is None:
            self.mechanism.setText(_PLACEHOLDER)
            self.context_sub.setText("")
            self.context_video.setText("")
            self.note.setText("")
            self.missing.hide()
            self.table.setRowCount(0)
            self.table.hide()
            return
        self.mechanism.setText(data.mechanism)
        self.context_sub.setText(data.context_subtitle)
        self.context_video.setText(data.context_video)
        self.note.setText(data.note)
        if data.missing_message:
            self.missing.setText(data.missing_message)
            self.missing.show()
            self.table.hide()
        else:
            self.missing.hide()
            self.table.show()
            self.table.setRowCount(len(data.rows))
            for r, row in enumerate(data.rows):
                self.table.setItem(r, 0, QTableWidgetItem(row.label))
                self.table.setItem(r, 1, QTableWidgetItem(row.original))
                self.table.setItem(r, 2, QTableWidgetItem(row.applied))
