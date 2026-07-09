"""「字幕檔」分頁:選/拖資料夾、掃描預覽、批次執行(執行緒)+ 進度 + 取消。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QRadioButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..batch_runner import scan_folder
from ..profile import Profile
from .batch_worker import BatchWorker
from .gui_helpers import preview_rows

_HEADERS = ["集數", "字幕檔", "影片檔", "狀態"]


class SubtitleFileTab(QWidget):
    log = Signal(str)

    def __init__(self, get_profile: Callable[[], Profile]) -> None:
        super().__init__()
        self._get_profile = get_profile
        self._scan = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[BatchWorker] = None
        self._scan_thread: Optional[QThread] = None
        self._scan_worker = None
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("資料夾:"))
        self.folder_edit = QLineEdit()
        folder_row.addWidget(self.folder_edit, 1)
        browse = QPushButton("瀏覽…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(browse)
        root.addLayout(folder_row)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        # 輸出模式
        out_row = QHBoxLayout()
        self.inplace_radio = QRadioButton("原地覆蓋(備份 .bak)")
        self.inplace_radio.setChecked(True)
        self.outdir_radio = QRadioButton("輸出到資料夾:")
        self.outdir_edit = QLineEdit()
        out_browse = QPushButton("…")
        out_browse.clicked.connect(self._browse_out)
        out_row.addWidget(self.inplace_radio)
        out_row.addWidget(self.outdir_radio)
        out_row.addWidget(self.outdir_edit, 1)
        out_row.addWidget(out_browse)
        root.addLayout(out_row)

        action_row = QHBoxLayout()
        self.scan_button = QPushButton("掃描並預覽配對")
        self.scan_button.clicked.connect(self._on_scan)
        self.run_button = QPushButton("開始套用樣式")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._on_run)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        self.open_out_button = QPushButton("開啟輸出資料夾")
        self.open_out_button.clicked.connect(self._open_output)
        action_row.addWidget(self.scan_button)
        action_row.addWidget(self.run_button)
        action_row.addWidget(self.cancel_button)
        action_row.addWidget(self.open_out_button)
        action_row.addStretch(1)
        root.addLayout(action_row)

        self.progress = QProgressBar()
        root.addWidget(self.progress)

    # ---------- 拖放 ----------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and Path(path).is_dir():
                self.folder_edit.setText(path)
                break

    # ---------- 檔案選擇 ----------
    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇字幕資料夾")
        if path:
            self.folder_edit.setText(path)

    def _browse_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇輸出資料夾")
        if path:
            self.outdir_edit.setText(path)
            self.outdir_radio.setChecked(True)

    def _output_dir(self) -> Optional[Path]:
        if self.outdir_radio.isChecked():
            text = self.outdir_edit.text().strip()
            return Path(text) if text else None
        return None

    # ---------- 掃描 ----------
    def _on_scan(self) -> None:
        folder = self.folder_edit.text().strip()
        if not folder or not Path(folder).is_dir():
            self.log.emit("請先選擇有效的資料夾")
            return
        from .batch_worker import ScanWorker
        self.scan_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self._scan_thread = QThread()
        self._scan_worker = ScanWorker(Path(folder))
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_thread.start()

    def _on_scan_finished(self, scan) -> None:
        self._scan = scan
        for w in scan.warnings:
            self.log.emit(f"警告: {w}")
        count = self.populate_preview(scan)
        self.log.emit(f"掃描完成:共 {count} 個字幕檔")
        self.scan_button.setEnabled(True)
        if self._scan_thread is not None:
            self._scan_thread.quit()
            self._scan_thread.wait()
        self._scan_thread = None
        self._scan_worker = None

    def populate_preview(self, scan) -> int:
        rows = preview_rows(scan)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(
                    (row.episode, row.sub_name, row.video_name,
                     row.status_label)):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.run_button.setEnabled(len(rows) > 0)
        return len(rows)

    # ---------- 執行 ----------
    def _on_run(self) -> None:
        if self._scan is None:
            return
        try:
            profile = self._get_profile()
        except ValueError as exc:
            self.log.emit(f"欄位錯誤: {exc}")
            return
        if self.outdir_radio.isChecked() and self._output_dir() is None:
            self.log.emit("請先選擇輸出資料夾")
            return

        self.progress.setValue(0)
        self.scan_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        self._thread = QThread()
        self._worker = BatchWorker(self._scan, profile, self._output_dir())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_done.connect(
            lambda name, status: self.log.emit(f"[{status}] {name}"))
        self._worker.message.connect(self.log.emit)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(done)

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)

    def _on_finished(self, ok: int, skipped: int, error: int) -> None:
        self.log.emit(f"完成:成功 {ok},跳過 {skipped},錯誤 {error}")
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self.scan_button.setEnabled(True)
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def shutdown(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        for thread in (self._thread, self._scan_thread):
            if thread is not None:
                thread.quit()
                thread.wait()

    # ---------- 開啟輸出資料夾 ----------
    def _open_output(self) -> None:
        target = self._output_dir()
        if target is None:
            target = Path(self.folder_edit.text().strip() or ".")
        if target.is_dir():
            if sys.platform.startswith("win"):
                os.startfile(str(target))  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(target)])
