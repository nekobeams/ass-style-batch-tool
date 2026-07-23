"""掃描進度小視窗:顯示逐檔進度並可取消。

總數在列舉完檔案前未知,因此進度條先以不確定狀態顯示,收到第一筆進度後
才切成確定範圍——不在知道總數之前假裝知道進度。
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                               QProgressBar, QVBoxLayout)

_SEARCHING = "正在尋找檔案…"


class ScanProgressDialog(QDialog):
    cancelled = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("讀取媒體資訊")
        self.setModal(True)
        root = QVBoxLayout(self)
        self.label = QLabel(_SEARCHING)
        root.addWidget(self.label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)          # 總數未知 → 不確定狀態
        root.addWidget(self.bar)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def set_progress(self, done: int, total: int) -> None:
        """第一次收到進度時把不確定狀態切成確定範圍。"""
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)
        self.label.setText(f"掃描影片 {done}/{total}")

    def reject(self) -> None:
        """取消鈕 / 視窗 X / Esc 一律走同一條取消路徑。"""
        self.cancelled.emit()
        super().reject()
