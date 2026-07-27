"""「MKV」分頁:掃描 MKV 字幕軌、勾選、一鍵選整季、批次重封裝、送進預覽。"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QSettings, QThread, Signal
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QProgressBar, QPushButton,
                               QRadioButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..mkv_batch import MkvTools, select_same_type
from ..mkv_io import SubtitleTrack, extract_track
from ..profile import Profile
from ..scale_engine import ScaleError
from ..tools import mkvextract_path, mkvmerge_path
from .batch_worker import MkvScanWorker, MkvWorker
from .scale_panel import ScalePanel
from .scan_progress_dialog import ScanProgressDialog

_ROLE_PATH = Qt.UserRole
_ROLE_TRACK = Qt.UserRole + 1


class MkvTab(QWidget):
    log = Signal(str)
    preview_requested = Signal(object, object)  # (暫存字幕路徑, MKV 路徑)

    def __init__(self, get_profile: Callable[[], Profile]) -> None:
        super().__init__()
        self._get_profile = get_profile
        self._files_tracks: Dict[Path, List[SubtitleTrack]] = {}
        self._thread: Optional[QThread] = None
        self._worker = None
        self._scan_thread: Optional[QThread] = None
        self._scan_worker = None
        self._scan_dialog: Optional[ScanProgressDialog] = None
        self._scanned_folder: Optional[str] = None
        self._closing = False
        self._preview_dir = Path(tempfile.mkdtemp(prefix="ass_mkv_preview_"))
        self.setAcceptDrops(True)

        mkvmerge = mkvmerge_path()
        mkvextract = mkvextract_path()
        self.tools_available = mkvmerge is not None and mkvextract is not None
        self._tools = (MkvTools(mkvmerge, mkvextract)
                       if self.tools_available else None)

        root = QVBoxLayout(self)

        if not self.tools_available:
            warn = QLabel("⚠ 找不到 mkvmerge/mkvextract:請安裝 MKVToolNix "
                          "後重新啟動(功能已停用,不影響其他分頁)")
            warn.setStyleSheet("color: #d08a00;")
            root.addWidget(warn)

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

        self.tree = QTreeWidget()
        self.tree.setAlternatingRowColors(True)
        self.tree.setHeaderLabels(["MKV / 字幕軌", "語言", "軌名"])
        self.tree.setColumnWidth(0, 420)
        root.addWidget(self.tree, 1)

        # 操作模式
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
        self.scale_mode_radio.toggled.connect(
            lambda on: self.scale_panel.setHidden(not on))

        # 輸出模式
        out_row = QHBoxLayout()
        self.outdir_radio = QRadioButton("輸出到資料夾:")
        self.outdir_radio.setChecked(True)
        self.outdir_edit = QLineEdit()
        out_browse = QPushButton("…")
        out_browse.clicked.connect(self._browse_out)
        self.replace_radio = QRadioButton("取代原檔(驗證後覆蓋,不留備份)")
        out_row.addWidget(self.outdir_radio)
        out_row.addWidget(self.outdir_edit, 1)
        out_row.addWidget(out_browse)
        out_row.addWidget(self.replace_radio)
        root.addLayout(out_row)

        self._output_group = QButtonGroup(self)
        self._output_group.addButton(self.outdir_radio)
        self._output_group.addButton(self.replace_radio)

        action_row = QHBoxLayout()
        self.scan_button = QPushButton("重新掃描")
        self.scan_button.clicked.connect(self._on_scan)
        self.same_type_button = QPushButton("一鍵選整季同類型軌")
        self.same_type_button.clicked.connect(self._on_same_type)
        self.preview_button = QPushButton("送進預覽")
        self.preview_button.clicked.connect(self._on_send_preview)
        self.run_button = QPushButton("開始處理")
        self.run_button.setProperty("accent", True)
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._on_run)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        for b in (self.scan_button, self.same_type_button,
                  self.preview_button, self.run_button, self.cancel_button):
            action_row.addWidget(b)
        action_row.addStretch(1)
        root.addLayout(action_row)

        progress_row = QHBoxLayout()
        self.progress = QProgressBar()          # 整批
        self.file_progress = QProgressBar()     # 當前檔 mkvmerge %
        self.file_progress.setRange(0, 100)
        progress_row.addWidget(QLabel("整批:"))
        progress_row.addWidget(self.progress, 2)
        progress_row.addWidget(QLabel("當前檔:"))
        progress_row.addWidget(self.file_progress, 1)
        root.addLayout(progress_row)

        if not self.tools_available:
            for b in (self.scan_button, self.same_type_button,
                      self.preview_button, self.run_button):
                b.setEnabled(False)

    # ---------- 拖放 / 檔案選擇 ----------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and Path(path).is_dir():
                self._folder_chosen(path)
                break

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇含 MKV 的資料夾")
        if path:
            self._folder_chosen(path)

    def _folder_chosen(self, path: str) -> None:
        """選好資料夾(瀏覽/拖放)→ 設定路徑並自動掃描。"""
        self.folder_edit.setText(path)
        self._auto_scan()

    def _auto_scan(self) -> None:
        """資料夾有效且與上次不同、無掃描/批次進行中、工具齊全時自動掃描。"""
        if not self.tools_available:
            return
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

    # ---------- 掃描 ----------
    def _on_scan(self) -> None:
        if self._thread is not None:
            self.log.emit("批次處理進行中,請稍後再掃描")
            return
        folder = self.folder_edit.text().strip()
        if not folder or not Path(folder).is_dir():
            self.log.emit("請先選擇有效的資料夾")
            return
        self._scanned_folder = folder
        self.scan_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self._scan_thread = QThread()
        self._scan_worker = MkvScanWorker(
            sorted(p for p in Path(folder).glob("*.mkv") if p.is_file()),
            self._tools.mkvmerge)
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_scan_done)
        self._scan_worker.cancelled.connect(self._on_scan_cancelled)
        self._scan_dialog = ScanProgressDialog(self)
        self._scan_worker.progress.connect(self._scan_dialog.set_progress)
        self._scan_dialog.cancelled.connect(self._request_scan_cancel)
        self._scan_dialog.show()      # 非 exec():維持既有非同步流程
        self._scan_thread.start()

    def _request_scan_cancel(self) -> None:
        """直接呼叫 worker.cancel(),不用 signal→worker slot 的連線。

        worker 已 moveToThread,但該執行緒在 run() 執行期間不會跑事件迴圈,
        排隊的 cancel() 要等掃描結束才會被處理——等於完全沒有作用。
        直接呼叫是本檔其他取消按鈕(以及 mux/subtitle 分頁)一貫的寫法。
        """
        if self._scan_worker is not None:
            self._scan_worker.cancel()

    def _finish_scan(self) -> None:
        """完成/取消共用的收尾:關對話框、收執行緒、恢復掃描鈕。"""
        if self._scan_dialog is not None:
            self._scan_dialog.hide()
            self._scan_dialog.deleteLater()
            self._scan_dialog = None
        if self._scan_thread is not None:
            self._scan_thread.quit()
            self._scan_thread.wait()
        self._scan_thread = None
        self._scan_worker = None
        self.scan_button.setEnabled(True)

    def _on_scan_done(self, files_tracks: dict) -> None:
        if self._closing:
            return
        self._finish_scan()
        self.populate(files_tracks)
        total_tracks = sum(len(v) for v in files_tracks.values())
        self.log.emit(f"掃描完成:{len(files_tracks)} 個 MKV,"
                      f"共 {total_tracks} 條 ASS 字幕軌")

    def _on_scan_cancelled(self) -> None:
        if self._closing:
            return
        self._finish_scan()
        self._scanned_folder = None   # 取消 = 沒掃描過,允許同一資料夾重新觸發掃描
        # 不呼叫 populate:保留上一次的結果與表格內容。
        # 但仍要用與 populate 相同的條件恢復執行鈕,否則舊結果還在、
        # 執行鈕卻永遠是灰的。
        if self._thread is None:
            self.run_button.setEnabled(
                any(self._files_tracks.values()) and self.tools_available)
        self.log.emit("掃描已取消")

    def populate(self, files_tracks: Dict[Path, List[SubtitleTrack]]) -> None:
        self._files_tracks = dict(files_tracks)
        self.tree.clear()
        for path in sorted(files_tracks):
            top = QTreeWidgetItem([path.name, "", ""])
            top.setData(0, _ROLE_PATH, path)
            tracks = files_tracks[path]
            if not tracks:
                top.setText(2, "(無 ASS 字幕軌)")
            for track in tracks:
                child = QTreeWidgetItem(
                    [f"軌 {track.track_id}", track.language,
                     track.track_name or "-"])
                child.setData(0, _ROLE_PATH, path)
                child.setData(0, _ROLE_TRACK, track)
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked)
                top.addChild(child)
            self.tree.addTopLevelItem(top)
        self.tree.expandAll()
        if self._thread is None:
            self.run_button.setEnabled(
                any(files_tracks.values()) and self.tools_available)

    # ---------- 勾選 ----------
    def _iter_track_items(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                yield top.child(j)

    def checked_jobs(self) -> List[Tuple[Path, List[SubtitleTrack]]]:
        grouped: Dict[Path, List[SubtitleTrack]] = {}
        for item in self._iter_track_items():
            if item.checkState(0) == Qt.CheckState.Checked:
                path = item.data(0, _ROLE_PATH)
                grouped.setdefault(path, []).append(item.data(0, _ROLE_TRACK))
        return [(p, ts) for p, ts in grouped.items() if ts]

    def current_track(self) -> Optional[Tuple[Path, SubtitleTrack]]:
        item = self.tree.currentItem()
        if item is None:
            return None
        track = item.data(0, _ROLE_TRACK)
        if track is None:
            return None
        return item.data(0, _ROLE_PATH), track

    def apply_same_type_from_current(self) -> int:
        """以目前選取軌所屬檔案的勾選狀態為基準,套用到所有檔案。"""
        current = self.current_track()
        if current is None:
            self.log.emit("請先在樹狀清單選取一條字幕軌作為基準")
            return 0
        base_path = current[0]
        reference = [item.data(0, _ROLE_TRACK)
                     for item in self._iter_track_items()
                     if item.data(0, _ROLE_PATH) == base_path
                     and item.checkState(0) == Qt.CheckState.Checked]
        selected = select_same_type(reference, self._files_tracks)
        updated = 0
        for item in self._iter_track_items():
            path = item.data(0, _ROLE_PATH)
            if path == base_path:
                continue
            track = item.data(0, _ROLE_TRACK)
            want = track.track_id in selected.get(path, set())
            state = Qt.CheckState.Checked if want else Qt.CheckState.Unchecked
            if item.checkState(0) != state:
                item.setCheckState(0, state)
                updated += 1
        self.log.emit(f"已依基準檔同步 {updated} 條軌的勾選狀態")
        return updated

    def _on_same_type(self) -> None:
        self.apply_same_type_from_current()

    # ---------- 送進預覽 ----------
    def _on_send_preview(self) -> None:
        current = self.current_track()
        if current is None:
            self.log.emit("請先選取一條字幕軌")
            return
        mkv_path, track = current
        temp = self._preview_dir / f"{mkv_path.stem}_track{track.track_id}.ass"
        if not extract_track(mkv_path, track.track_id, temp,
                             self._tools.mkvextract):
            self.log.emit(f"抽取軌 {track.track_id} 失敗,無法預覽")
            return
        self.preview_requested.emit(temp, mkv_path)

    # ---------- 執行 ----------
    def _output_dir(self) -> Optional[Path]:
        if self.replace_radio.isChecked():
            return None
        text = self.outdir_edit.text().strip()
        return Path(text) if text else None

    def _on_run(self) -> None:
        if self._scan_thread is not None or self._thread is not None:
            self.log.emit("掃描或處理進行中,請稍候")
            return
        jobs = self.checked_jobs()
        if not jobs:
            self.log.emit("沒有勾選任何字幕軌")
            return
        if self.scale_mode_radio.isChecked():
            try:
                operation = self.scale_panel.get_options()
            except ScaleError as exc:
                self.log.emit(f"參數錯誤: {exc}")
                return
        else:
            try:
                operation = self._get_profile()
            except ValueError as exc:
                self.log.emit(f"欄位錯誤: {exc}")
                return
        output_dir = self._output_dir()
        if self.outdir_radio.isChecked() and output_dir is None:
            self.log.emit("請先選擇輸出資料夾")
            return

        self.progress.setValue(0)
        self.file_progress.setValue(0)
        self.scan_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        self._thread = QThread()
        self._worker = MkvWorker(jobs, operation, self._tools, output_dir)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_progress.connect(self.file_progress.setValue)
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
        self.log.emit(f"MKV 批次完成:成功 {ok},跳過 {skipped},錯誤 {error}")
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self.scan_button.setEnabled(True)
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    # ---------- 清理 ----------
    def shutdown(self) -> None:
        self._closing = True
        for worker in (self._worker, self._scan_worker):
            if worker is not None:
                worker.cancel()
        for thread in (self._thread, self._scan_thread):
            if thread is not None:
                thread.quit()
                thread.wait()
        # 沒有這行的話,取消/掃描完成時開出的模態 ScanProgressDialog 會留在
        # 畫面上、_scan_dialog 也留著沒清——套件化的 console=False 版本裡,
        # 主視窗關閉後 quitOnLastWindowClosed 因為這個還可見的對話框而永遠
        # 不會成立,process 會卡著不退出(對照 MuxTab.shutdown() 已有的
        # _finish_track_scan() 收尾)。
        self._finish_scan()
        import shutil
        shutil.rmtree(self._preview_dir, ignore_errors=True)

    # ---------- 設定持久化 ----------
    def save_settings(self, settings: QSettings) -> None:
        settings.setValue("mkv/folder", self.folder_edit.text())
        settings.setValue(
            "mkv/output_mode",
            "replace" if self.replace_radio.isChecked() else "outdir")
        settings.setValue("mkv/outdir", self.outdir_edit.text())

    def restore_settings(self, settings: QSettings) -> None:
        self.folder_edit.setText(settings.value("mkv/folder", ""))
        self.outdir_edit.setText(settings.value("mkv/outdir", ""))
        if settings.value("mkv/output_mode", "outdir") == "replace":
            self.replace_radio.setChecked(True)
        else:
            self.outdir_radio.setChecked(True)
