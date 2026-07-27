"""「MKV」分頁:列出資料夾內的 MKV、用規則選定要重新套樣式的舊字幕軌、批次重封裝。

分頁主畫面只列檔案。「要對哪幾條舊字幕軌套樣式」由「修改既有軌道…」對話框
控制:在範本檔上勾選,規則以 (語言, 軌名) 套用到整批影片。mkvmerge -J 只在
真的需要軌道資訊時才跑(開對話框、或尚未設定規則就按開始處理),選資料夾
本身不跑任何外部程序。
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import Qt, QSettings, QThread, Signal
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QFileDialog,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QRadioButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..mkv_batch import MkvTools, track_key
from ..mkv_io import SubtitleTrack, extract_track
from ..profile import Profile
from ..scale_engine import ScaleError
from ..tools import mkvextract_path, mkvmerge_path
from ..track_select import TrackKey, resolve_tracks
from .batch_worker import MkvScanWorker, MkvWorker
from .layout_helpers import (action_row, group, main_splitter, page_layout,
                             settings_sidebar)
from .scale_panel import ScalePanel
from .scan_progress_dialog import ScanProgressDialog
from .select_tracks_dialog import SelectTracksDialog

_HEADERS = ["MKV", "將套用的軌"]


class MkvTab(QWidget):
    log = Signal(str)
    preview_requested = Signal(object, object)  # (暫存字幕路徑, MKV 路徑)

    def __init__(self, get_profile: Callable[[], Profile]) -> None:
        super().__init__()
        self._get_profile = get_profile
        self._files: List[Path] = []
        self._files_tracks: Dict[Path, List[SubtitleTrack]] = {}
        self._track_keys: Optional[Set[TrackKey]] = None  # None = 從未設定
        self._pending_action: Optional[str] = None        # "dialog" | "run"
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

        root = page_layout(self)

        if not self.tools_available:
            warn = QLabel("⚠ 找不到 mkvmerge/mkvextract:請安裝 MKVToolNix "
                          "後重新啟動(功能已停用,不影響其他分頁)")
            warn.setStyleSheet("QLabel { color: #d08a00; }")
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

        self.file_table = QTableWidget(0, len(_HEADERS))
        self.file_table.setAlternatingRowColors(True)
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.file_table.setHorizontalHeaderLabels(_HEADERS)
        self.file_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)

        # ----- 側欄:操作模式 -----
        mode_box = QVBoxLayout()
        self.apply_mode_radio = QRadioButton("套用樣式")
        self.apply_mode_radio.setChecked(True)
        self.scale_mode_radio = QRadioButton("縮放字級")
        mode_box.addWidget(self.apply_mode_radio)
        mode_box.addWidget(self.scale_mode_radio)
        self.scale_panel = ScalePanel()
        self.scale_panel.setHidden(True)
        mode_box.addWidget(self.scale_panel)
        self.scale_mode_radio.toggled.connect(
            lambda on: self.scale_panel.setHidden(not on))

        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.apply_mode_radio)
        self._mode_group.addButton(self.scale_mode_radio)

        # ----- 側欄:字幕軌 -----
        track_box = QVBoxLayout()
        self.modify_tracks_button = QPushButton("修改既有軌道…")
        self.modify_tracks_button.clicked.connect(self._on_modify_tracks)
        track_box.addWidget(self.modify_tracks_button)
        self.preview_button = QPushButton("送進預覽")
        self.preview_button.clicked.connect(self._on_send_preview)
        track_box.addWidget(self.preview_button)

        # ----- 側欄:輸出 -----
        out_box = QVBoxLayout()
        self.outdir_radio = QRadioButton("輸出到資料夾")
        self.outdir_radio.setChecked(True)
        out_box.addWidget(self.outdir_radio)
        outdir_row = QHBoxLayout()
        self.outdir_edit = QLineEdit()
        out_browse = QPushButton("…")
        out_browse.setMaximumWidth(32)
        out_browse.clicked.connect(self._browse_out)
        outdir_row.addWidget(self.outdir_edit, 1)
        outdir_row.addWidget(out_browse)
        out_box.addLayout(outdir_row)
        self.replace_radio = QRadioButton("取代原檔(驗證後覆蓋,不留備份)")
        out_box.addWidget(self.replace_radio)

        self._output_group = QButtonGroup(self)
        self._output_group.addButton(self.outdir_radio)
        self._output_group.addButton(self.replace_radio)

        self.splitter = main_splitter(
            self.file_table,
            settings_sidebar(group("操作模式", mode_box),
                             group("字幕軌", track_box),
                             group("輸出", out_box)))
        root.addWidget(self.splitter, 1)

        self.scan_button = QPushButton("重新掃描")
        self.scan_button.clicked.connect(self._on_scan)
        self.run_button = QPushButton("開始處理")
        self.run_button.setProperty("accent", True)
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._on_run)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        root.addLayout(action_row([self.scan_button],
                                  [self.run_button, self.cancel_button]))

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
            for b in (self.scan_button, self.modify_tracks_button,
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

    # ---------- 列檔(同步,不跑外部程序) ----------
    def _on_scan(self) -> None:
        if self._thread is not None:
            self.log.emit("批次處理進行中,請稍後再掃描")
            return
        folder = self.folder_edit.text().strip()
        if not folder or not Path(folder).is_dir():
            self.log.emit("請先選擇有效的資料夾")
            return
        self._scanned_folder = folder
        # 只掃當層。掃到軌道資訊要等使用者按「修改既有軌道…」或直接開始處理。
        files = sorted(p for p in Path(folder).glob("*.mkv") if p.is_file())
        self._files_tracks = {}
        self._apply_keys(None)
        self.populate(files)
        self.log.emit(f"找到 {len(files)} 個 MKV")

    def populate(self, files: List[Path]) -> None:
        self._files = list(files)
        self.file_table.setRowCount(len(self._files))
        for row, path in enumerate(self._files):
            name = QTableWidgetItem(path.name)
            name.setFlags(name.flags() | Qt.ItemIsUserCheckable)
            name.setCheckState(Qt.CheckState.Checked)
            self.file_table.setItem(row, 0, name)
            self.file_table.setItem(row, 1, QTableWidgetItem(""))
        self._refresh_track_column()
        if self._thread is None:
            self.run_button.setEnabled(bool(self._files)
                                       and self.tools_available)

    def checked_files(self) -> List[Path]:
        return [path for row, path in enumerate(self._files)
                if self.file_table.item(row, 0).checkState()
                == Qt.CheckState.Checked]

    # ---------- 規則 ----------
    def _apply_keys(self, keys: Optional[Set[TrackKey]]) -> None:
        """設定(或清除)規則,並同步按鈕文字與清單的「將套用的軌」欄。"""
        self._track_keys = keys
        self.modify_tracks_button.setText(
            "修改既有軌道…" if keys is None
            else f"修改既有軌道…(已選 {len(keys)} 條)")
        self._refresh_track_column()

    def _tracks_for(self, path: Path) -> Optional[List[SubtitleTrack]]:
        """該檔依目前規則要套用的軌;尚未掃過軌時回 None。"""
        tracks = self._files_tracks.get(path)
        if tracks is None:
            return None
        if self._track_keys is None:
            return list(tracks)
        return [t for t in tracks if track_key(t) in self._track_keys]

    def _refresh_track_column(self) -> None:
        for row, path in enumerate(self._files):
            picked = self._tracks_for(path)
            if picked is None:
                text = ""
            elif not picked:
                text = "✗ 無符合的軌"
            elif len(picked) == 1:
                text = f"✓ 軌 {picked[0].track_id}"
            else:
                text = "⚠ " + "、".join(f"軌 {t.track_id}" for t in picked)
            item = self.file_table.item(row, 1)
            if item is not None:
                item.setText(text)

    def current_jobs(self) -> List[Tuple[Path, List[SubtitleTrack]]]:
        """已勾選檔案依目前規則解析出的 (檔案, 軌清單);無軌者不列入。"""
        available = {p: self._files_tracks[p] for p in self.checked_files()
                     if p in self._files_tracks}
        if self._track_keys is None:
            resolved = {p: list(ts) for p, ts in available.items() if ts}
        else:
            resolved = resolve_tracks(self._track_keys, available)
        return sorted(resolved.items())

    # ---------- 掃軌(唯一會跑 mkvmerge -J 的路徑) ----------
    def _needs_track_scan(self) -> bool:
        return any(p not in self._files_tracks for p in self.checked_files())

    def _start_track_scan(self, pending: str) -> None:
        if self._scan_thread is not None:
            self.log.emit("軌道掃描進行中")
            return
        files = self.checked_files()
        if not files:
            self.log.emit("沒有勾選任何 MKV")
            return
        self._pending_action = pending
        self.scan_button.setEnabled(False)
        self._scan_thread = QThread()
        self._scan_worker = MkvScanWorker(files, self._tools.mkvmerge)
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_track_scan_done)
        self._scan_worker.cancelled.connect(self._on_track_scan_cancelled)
        self._scan_dialog = ScanProgressDialog(self)
        self._scan_worker.progress.connect(self._scan_dialog.set_progress)
        self._scan_dialog.cancelled.connect(self._request_scan_cancel)
        self._scan_dialog.show()      # 非 exec():維持既有非同步流程
        self._scan_thread.start()

    def _request_scan_cancel(self) -> None:
        """直接呼叫 worker.cancel(),不用 signal→worker slot 的連線。

        worker 已 moveToThread,但該執行緒在 run() 執行期間不會跑事件迴圈,
        排隊的 cancel() 要等掃描結束才會被處理——等於完全沒有作用。
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

    def _on_track_scan_done(self, files_tracks: dict) -> None:
        if self._closing:
            return
        pending = self._pending_action
        self._pending_action = None
        self._finish_scan()
        self._files_tracks.update(files_tracks)
        self._refresh_track_column()
        total = sum(len(v) for v in files_tracks.values())
        self.log.emit(f"掃描完成:{len(files_tracks)} 個 MKV,"
                      f"共 {total} 條 ASS 字幕軌")
        if pending == "dialog":
            self._open_select_dialog()
        elif pending == "run":
            self._start_batch()

    def _on_track_scan_cancelled(self) -> None:
        if self._closing:
            return
        # 取消 = 兩條路都不繼續:不開對話框、不啟動批次,已勾選的清單與
        # 上次的規則都保持原狀。
        self._pending_action = None
        self._finish_scan()
        self.log.emit("軌道掃描已取消")

    # ---------- 選軌對話框 ----------
    def _on_modify_tracks(self) -> None:
        if self._needs_track_scan():
            self._start_track_scan("dialog")
            return
        if not self.checked_files():
            self.log.emit("沒有勾選任何 MKV")
            return
        self._open_select_dialog()

    def _open_select_dialog(self) -> None:
        available = {p: self._files_tracks[p] for p in self.checked_files()
                     if p in self._files_tracks}
        if not any(available.values()):
            self.log.emit("所有勾選的 MKV 都讀不到 ASS 字幕軌")
            return
        dialog = SelectTracksDialog(available, self._track_keys, self)
        if dialog.exec():
            self._apply_keys(dialog.get_keys())

    # ---------- 送進預覽 ----------
    def _current_file(self) -> Optional[Path]:
        row = self.file_table.currentRow()
        if 0 <= row < len(self._files):
            return self._files[row]
        return None

    def _on_send_preview(self) -> None:
        path = self._current_file()
        if path is None:
            self.log.emit("請先選取一個 MKV 檔")
            return
        picked = self._tracks_for(path)
        if picked is None:
            self.log.emit("這個檔還沒掃過字幕軌,請先按「修改既有軌道…」")
            return
        if not picked:
            self.log.emit("這個檔沒有符合目前選擇的字幕軌")
            return
        track = picked[0]
        temp = self._preview_dir / f"{path.stem}_track{track.track_id}.ass"
        if not extract_track(path, track.track_id, temp,
                             self._tools.mkvextract):
            self.log.emit(f"抽取軌 {track.track_id} 失敗,無法預覽")
            return
        self.preview_requested.emit(temp, path)

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
        if not self.checked_files():
            self.log.emit("沒有勾選任何 MKV")
            return
        if self._needs_track_scan():
            # 從沒開過對話框就直接按開始處理:先掃軌,掃完接著跑批次
            self._start_track_scan("run")
            return
        self._start_batch()

    def _start_batch(self) -> None:
        jobs = self.current_jobs()
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
        self.modify_tracks_button.setEnabled(False)
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
        self.modify_tracks_button.setEnabled(self.tools_available)
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
        # 不會成立,process 會卡著不退出。
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
        settings.setValue("mkv/splitter", self.splitter.saveState())

    def restore_settings(self, settings: QSettings) -> None:
        self.folder_edit.setText(settings.value("mkv/folder", ""))
        self.outdir_edit.setText(settings.value("mkv/outdir", ""))
        if settings.value("mkv/output_mode", "outdir") == "replace":
            self.replace_radio.setChecked(True)
        else:
            self.outdir_radio.setChecked(True)
        state = settings.value("mkv/splitter")
        if state is not None:
            self.splitter.restoreState(state)
