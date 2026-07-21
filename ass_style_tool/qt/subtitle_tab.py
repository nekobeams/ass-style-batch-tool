"""「字幕檔」分頁:選/拖資料夾、掃描預覽、批次執行(執行緒)+ 進度 + 取消。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QSettings, QThread, Signal
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QFileDialog,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QRadioButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..batch_runner import scan_folder
from ..profile import Profile
from ..scale_engine import ScaleError, read_as_ass_text, scale_text
from .batch_worker import BatchWorker, ScaleWorker
from .gui_helpers import preview_rows
from .scale_panel import ScalePanel

_HEADERS = ["集數", "字幕檔", "影片檔", "狀態"]


class SubtitleFileTab(QWidget):
    log = Signal(str)
    preview_requested = Signal(object, object)  # (sub_path, video_path|None)

    def __init__(self, get_profile: Callable[[], Profile]) -> None:
        super().__init__()
        self._get_profile = get_profile
        self._scan = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[BatchWorker] = None
        self._scan_thread: Optional[QThread] = None
        self._scan_worker = None
        self._scanned_folder: Optional[str] = None
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("資料夾:"))
        self.folder_edit = QLineEdit()
        # 貼上/輸入路徑後(Enter 或失焦)自動掃描
        self.folder_edit.editingFinished.connect(self._auto_scan)
        folder_row.addWidget(self.folder_edit, 1)
        browse = QPushButton("瀏覽…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(browse)
        root.addLayout(folder_row)

        # 操作模式:套用樣式(既有)/ 縮放字級(新)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("操作模式:"))
        self.apply_mode_radio = QRadioButton("套用樣式")
        self.apply_mode_radio.setChecked(True)
        self.scale_mode_radio = QRadioButton("縮放字級")
        mode_row.addWidget(self.apply_mode_radio)
        mode_row.addWidget(self.scale_mode_radio)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.apply_mode_radio)
        self._mode_group.addButton(self.scale_mode_radio)

        self.scale_panel = ScalePanel()
        self.scale_panel.setHidden(True)
        root.addWidget(self.scale_panel)
        self.scale_mode_radio.toggled.connect(self._on_mode_changed)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
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

        self._output_group = QButtonGroup(self)
        self._output_group.addButton(self.inplace_radio)
        self._output_group.addButton(self.outdir_radio)

        action_row = QHBoxLayout()
        self.scan_button = QPushButton("重新掃描")
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
        self.dry_run_button = QPushButton("試算預覽(不寫檔)")
        self.dry_run_button.setEnabled(False)
        self.dry_run_button.clicked.connect(self._on_dry_run)
        action_row.addWidget(self.dry_run_button)
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
                self._folder_chosen(path)
                break

    # ---------- 檔案選擇 ----------
    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇字幕資料夾")
        if path:
            self._folder_chosen(path)

    def _folder_chosen(self, path: str) -> None:
        """選好資料夾(瀏覽/拖放)→ 設定路徑並自動掃描。"""
        self.folder_edit.setText(path)
        self._auto_scan()

    def _auto_scan(self) -> None:
        """資料夾有效且與上次不同、且無掃描/批次進行中時,自動觸發掃描。"""
        folder = self.folder_edit.text().strip()
        if (not folder or not Path(folder).is_dir()
                or folder == self._scanned_folder):
            return
        if self._scan_thread is not None or self._thread is not None:
            return
        self._on_scan()

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
        self._scanned_folder = folder
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
        self._update_dry_run_enabled()
        return len(rows)

    def _on_row_double_clicked(self, row: int, _column: int) -> None:
        if self._scan is None or row >= len(self._scan.matches):
            return
        match = self._scan.matches[row]
        self.preview_requested.emit(match.sub_path, match.video_path)

    # ---------- 模式切換 / 試算預覽 ----------
    def _on_mode_changed(self, scale_mode: bool) -> None:
        self.scale_panel.setHidden(not scale_mode)
        self.run_button.setText("開始縮放" if scale_mode else "開始套用樣式")
        self._update_dry_run_enabled()

    def _update_dry_run_enabled(self) -> None:
        self.dry_run_button.setEnabled(
            self.scale_mode_radio.isChecked() and self._scan is not None
            and len(self._scan.matches) > 0 and self._thread is None)

    def _on_dry_run(self) -> None:
        if self._scan is None:
            return
        try:
            options = self.scale_panel.get_options()
        except ScaleError as exc:
            self.log.emit(f"參數錯誤: {exc}")
            return
        self.log.emit("=== 試算預覽(不寫檔)===")
        for match in self._scan.matches:
            try:
                text, _codec, _converted = read_as_ass_text(match.sub_path)
                _new, report = scale_text(text, options)
            except Exception as exc:  # noqa: BLE001
                self.log.emit(f"[error] {match.sub_path.name}: {exc}")
                continue
            self.log.emit(
                f"[試算] {match.sub_path.name}(倍率 {report.factor_used:.3f})")
            for change in report.style_changes:
                self.log.emit(
                    f"    {change.name}: {change.old_size} → {change.new_size}")
            self.log.emit(f"    inline \\fs 將修改 {report.inline_fs_count} 處")

    # ---------- 執行 ----------
    def _on_run(self) -> None:
        if self._scan is None:
            return
        if self.scale_mode_radio.isChecked():
            try:
                payload = self.scale_panel.get_options()
            except ScaleError as exc:
                self.log.emit(f"參數錯誤: {exc}")
                return
        else:
            try:
                payload = self._get_profile()
            except ValueError as exc:
                self.log.emit(f"欄位錯誤: {exc}")
                return
        if self.outdir_radio.isChecked() and self._output_dir() is None:
            self.log.emit("請先選擇輸出資料夾")
            return

        self.progress.setValue(0)
        self.scan_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.dry_run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        self._thread = QThread()
        if self.scale_mode_radio.isChecked():
            self._worker = ScaleWorker(self._scan, payload, self._output_dir())
        else:
            self._worker = BatchWorker(self._scan, payload, self._output_dir())
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
        self._update_dry_run_enabled()

    def shutdown(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        for thread in (self._thread, self._scan_thread):
            if thread is not None:
                thread.quit()
                thread.wait()

    # ---------- 設定持久化 ----------
    def save_settings(self, settings: QSettings) -> None:
        settings.setValue("subtitle/folder", self.folder_edit.text())
        settings.setValue(
            "subtitle/output_mode",
            "outdir" if self.outdir_radio.isChecked() else "inplace")
        settings.setValue("subtitle/outdir", self.outdir_edit.text())

    def restore_settings(self, settings: QSettings) -> None:
        self.folder_edit.setText(settings.value("subtitle/folder", ""))
        self.outdir_edit.setText(settings.value("subtitle/outdir", ""))
        if settings.value("subtitle/output_mode", "inplace") == "outdir":
            self.outdir_radio.setChecked(True)
        else:
            self.inplace_radio.setChecked(True)

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
