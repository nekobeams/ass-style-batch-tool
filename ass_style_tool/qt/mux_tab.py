"""「封裝」分頁:把外部 .ass 字幕依集數配對後 mux 進 MKV。"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, QSettings, QThread, Signal
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup,
                               QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QRadioButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..episode_match import find_files
from ..mkv_batch import MkvTools
from ..mkv_io import list_all_tracks
from ..mkv_mux import MuxMeta, MuxPair
from ..profile import Profile
from ..scale_engine import ScaleError
from ..tools import mkvextract_path, mkvmerge_path
from ..track_edit import TrackEdit
from .batch_worker import MuxScanWorker, MuxWorker
from .modify_tracks_dialog import ModifyTracksDialog
from .scale_panel import ScalePanel

_HEADERS = ["封裝", "影片", "字幕", "集數", "狀態"]
_STATUS_LABELS = {"matched": "已配對", "no_subtitle": "無對應字幕",
                  "ambiguous": "配對模糊", "no_episode": "無法判斷集數"}
# 常見字幕語言(mkvmerge 用 ISO 639-2;一律用書目碼 chi/fre/ger…,與既有一致)。
# 最常用的三個排最前面維持原本的順手程度,「未定」保持在最後。
_LANGUAGES = [
    ("中文", "chi"), ("日文", "jpn"), ("英文", "eng"),
    ("韓文", "kor"), ("西班牙文", "spa"), ("法文", "fre"),
    ("德文", "ger"), ("義大利文", "ita"), ("葡萄牙文", "por"),
    ("俄文", "rus"), ("泰文", "tha"), ("越南文", "vie"),
    ("印尼文", "ind"), ("阿拉伯文", "ara"),
    ("未定", "und"),
]


class MuxTab(QWidget):
    log = Signal(str)

    def __init__(self, get_profile: Callable[[], Profile]) -> None:
        super().__init__()
        self._get_profile = get_profile
        self._pairs: List[MuxPair] = []
        self._available_subtitles: List[Path] = []
        self._thread: Optional[QThread] = None
        self._worker = None
        self._scan_thread: Optional[QThread] = None
        self._scan_worker = None
        self._scanned_key: Optional[tuple] = None
        self._track_edits: dict = {}
        self.setAcceptDrops(True)

        mkvmerge = mkvmerge_path()
        mkvextract = mkvextract_path()
        self.tools_available = mkvmerge is not None and mkvextract is not None
        self._tools = (MkvTools(mkvmerge, mkvextract)
                       if self.tools_available else None)

        root = QVBoxLayout(self)
        if not self.tools_available:
            warn = QLabel("⚠ 找不到 mkvmerge:請安裝 MKVToolNix 後重新啟動"
                          "(封裝功能已停用)")
            warn.setStyleSheet("color: #d08a00;")
            root.addWidget(warn)

        vrow = QHBoxLayout()
        vrow.addWidget(QLabel("影片資料夾:"))
        self.video_edit = QLineEdit()
        self.video_edit.editingFinished.connect(self._auto_scan)
        vrow.addWidget(self.video_edit, 1)
        vbrowse = QPushButton("瀏覽…")
        vbrowse.clicked.connect(self._browse_video)
        vrow.addWidget(vbrowse)
        root.addLayout(vrow)

        srow = QHBoxLayout()
        srow.addWidget(QLabel("字幕資料夾:"))
        self.subtitle_edit = QLineEdit()
        self.subtitle_edit.editingFinished.connect(self._auto_scan)
        srow.addWidget(self.subtitle_edit, 1)
        sbrowse = QPushButton("瀏覽…")
        sbrowse.clicked.connect(self._browse_subtitle)
        srow.addWidget(sbrowse)
        root.addLayout(srow)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        # 軌資訊
        meta_row = QHBoxLayout()
        meta_row.addWidget(QLabel("語言:"))
        self.language_combo = QComboBox()
        for label, code in _LANGUAGES:
            self.language_combo.addItem(f"{label} ({code})", code)
        meta_row.addWidget(self.language_combo)
        meta_row.addWidget(QLabel("軌名:"))
        self.trackname_edit = QLineEdit()
        meta_row.addWidget(self.trackname_edit, 1)
        self.default_check = QCheckBox("預設軌")
        self.forced_check = QCheckBox("強制軌")
        meta_row.addWidget(self.default_check)
        meta_row.addWidget(self.forced_check)
        root.addLayout(meta_row)

        # 封裝前處理
        op_row = QHBoxLayout()
        op_row.addWidget(QLabel("封裝前:"))
        self.direct_mode_radio = QRadioButton("原字幕直接封")
        self.direct_mode_radio.setChecked(True)
        self.apply_mode_radio = QRadioButton("先套用目前樣式")
        self.scale_mode_radio = QRadioButton("先縮放字級")
        op_row.addWidget(self.direct_mode_radio)
        op_row.addWidget(self.apply_mode_radio)
        op_row.addWidget(self.scale_mode_radio)
        op_row.addStretch(1)
        root.addLayout(op_row)

        self._preprocess_group = QButtonGroup(self)
        self._preprocess_group.addButton(self.direct_mode_radio)
        self._preprocess_group.addButton(self.apply_mode_radio)
        self._preprocess_group.addButton(self.scale_mode_radio)

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
        self.replace_radio = QRadioButton("取代原影片(驗證後覆蓋)")
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
        self.modify_tracks_button = QPushButton("修改既有軌道…")
        self.modify_tracks_button.setEnabled(False)
        self.modify_tracks_button.clicked.connect(self._on_modify_tracks)
        self.run_button = QPushButton("開始封裝")
        self.run_button.setProperty("accent", True)
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._on_run)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        for b in (self.scan_button, self.modify_tracks_button,
                  self.run_button, self.cancel_button):
            action_row.addWidget(b)
        action_row.addStretch(1)
        root.addLayout(action_row)

        prow = QHBoxLayout()
        self.progress = QProgressBar()
        self.file_progress = QProgressBar()
        self.file_progress.setRange(0, 100)
        prow.addWidget(QLabel("整批:"))
        prow.addWidget(self.progress, 2)
        prow.addWidget(QLabel("當前檔:"))
        prow.addWidget(self.file_progress, 1)
        root.addLayout(prow)

        if not self.tools_available:
            for b in (self.scan_button, self.run_button,
                      self.modify_tracks_button):
                b.setEnabled(False)

    # ---------- 拖放 / 檔案選擇 ----------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and Path(path).is_dir():
                self.video_edit.setText(path)
                self._auto_scan()
                break

    def _browse_video(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇影片資料夾")
        if path:
            self.video_edit.setText(path)
            self._auto_scan()

    def _browse_subtitle(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇字幕資料夾")
        if path:
            self.subtitle_edit.setText(path)
            self._auto_scan()

    def _browse_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇輸出資料夾")
        if path:
            self.outdir_edit.setText(path)
            self.outdir_radio.setChecked(True)

    # ---------- 掃描 ----------
    def _auto_scan(self) -> None:
        if not self.tools_available:
            return
        v = self.video_edit.text().strip()
        s = self.subtitle_edit.text().strip()
        if not (v and s and Path(v).is_dir() and Path(s).is_dir()):
            return
        if (v, s) == self._scanned_key:
            return
        if self._scan_thread is not None or self._thread is not None:
            return
        self._on_scan()

    def _on_scan(self) -> None:
        if self._thread is not None:
            self.log.emit("封裝進行中,請稍後再掃描")
            return
        v = self.video_edit.text().strip()
        s = self.subtitle_edit.text().strip()
        if not (v and s and Path(v).is_dir() and Path(s).is_dir()):
            self.log.emit("請先選擇有效的影片與字幕資料夾")
            return
        self._scanned_key = (v, s)
        self.scan_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self._scan_thread = QThread()
        self._scan_worker = MuxScanWorker(Path(v), Path(s))
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_scan_done)
        self._scan_thread.start()

    def _on_scan_done(self, pairs: list) -> None:
        if self._scan_thread is not None:
            self._scan_thread.quit()
            self._scan_thread.wait()
        self._scan_thread = None
        self._scan_worker = None
        self.scan_button.setEnabled(True)
        s = self.subtitle_edit.text().strip()
        if s and Path(s).is_dir():
            subs, _ = find_files(Path(s))
            self._available_subtitles = sorted(subs)
        self.populate(pairs)
        matched = sum(1 for p in pairs if p.status == "matched")
        self.log.emit(f"配對完成:{len(pairs)} 部影片,{matched} 部有對應字幕")

    def populate(self, pairs: List[MuxPair]) -> None:
        self._pairs = list(pairs)
        self.table.setRowCount(len(pairs))
        for r, pair in enumerate(pairs):
            check = QTableWidgetItem()
            check.setFlags(check.flags() | Qt.ItemIsUserCheckable)
            check.setCheckState(
                Qt.CheckState.Checked if pair.status == "matched"
                else Qt.CheckState.Unchecked)
            self.table.setItem(r, 0, check)
            self.table.setItem(r, 1, QTableWidgetItem(pair.video_path.name))
            combo = QComboBox()
            combo.setStyleSheet("QComboBox { background: transparent; }")
            combo.addItem("(無)", None)
            options = list(self._available_subtitles)
            if (pair.subtitle_path is not None
                    and pair.subtitle_path not in options):
                options.append(pair.subtitle_path)
            selected_index = 0
            for i, sub in enumerate(options, start=1):
                combo.addItem(sub.name, sub)
                if sub == pair.subtitle_path:
                    selected_index = i
            combo.setCurrentIndex(selected_index)
            combo.activated.connect(
                lambda _idx, row=r: self._on_subtitle_selected(row))
            self.table.setCellWidget(r, 2, combo)
            self.table.setItem(
                r, 3, QTableWidgetItem(
                    f"{pair.episode:02d}" if pair.episode is not None else "?"))
            self.table.setItem(
                r, 4, QTableWidgetItem(
                    _STATUS_LABELS.get(pair.status, pair.status)))
        self.run_button.setEnabled(
            self.tools_available and any(p.status == "matched" for p in pairs)
            and self._thread is None)
        self._refresh_modify_button()

    def checked_pairs(self) -> List[MuxPair]:
        result = []
        for r, pair in enumerate(self._pairs):
            item = self.table.item(r, 0)
            if (item is not None and item.checkState() == Qt.CheckState.Checked
                    and pair.status == "matched"):
                result.append(pair)
        return result

    def set_row_subtitle(self, row: int, subtitle_path: Optional[Path]) -> None:
        """手動指定(或清除)某列的字幕檔;同步 pair/狀態欄/勾選框。"""
        pair = self._pairs[row]
        if subtitle_path is not None:
            new_pair = dataclasses.replace(
                pair, subtitle_path=subtitle_path, status="matched")
        else:
            new_pair = dataclasses.replace(
                pair, subtitle_path=None, status="no_subtitle")
        self._pairs[row] = new_pair
        self.table.item(row, 4).setText(
            _STATUS_LABELS.get(new_pair.status, new_pair.status))
        check = self.table.item(row, 0)
        check.setCheckState(
            Qt.CheckState.Checked if new_pair.status == "matched"
            else Qt.CheckState.Unchecked)
        self.run_button.setEnabled(
            self.tools_available
            and any(p.status == "matched" for p in self._pairs)
            and self._thread is None)
        self._refresh_modify_button()

    def _on_subtitle_selected(self, row: int) -> None:
        combo = self.table.cellWidget(row, 2)
        self.set_row_subtitle(row, combo.currentData())

    # ---------- 軌資訊 / 操作 ----------
    def current_meta(self) -> MuxMeta:
        return MuxMeta(
            language=self.language_combo.currentData(),
            track_name=self.trackname_edit.text().strip(),
            default=self.default_check.isChecked(),
            forced=self.forced_check.isChecked())

    def current_operation(self):
        if self.scale_mode_radio.isChecked():
            return self.scale_panel.get_options()
        if self.apply_mode_radio.isChecked():
            return self._get_profile()
        return None

    def _output_dir(self) -> Optional[Path]:
        if self.replace_radio.isChecked():
            return None
        text = self.outdir_edit.text().strip()
        return Path(text) if text else None

    def _refresh_modify_button(self) -> None:
        self.modify_tracks_button.setEnabled(
            self.tools_available
            and any(p.status == "matched" for p in self._pairs)
            and self._thread is None)

    def _has_track_edits(self) -> bool:
        return any(
            (not e.keep) or e.set_default is not None or e.set_forced is not None
            or e.language or e.track_name
            for e in self._track_edits.values())

    def _on_modify_tracks(self) -> None:
        matched = [p for p in self._pairs if p.status == "matched"]
        if not matched:
            self.log.emit("沒有可用的來源影片可掃描軌道")
            return
        video = matched[0].video_path
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            tracks = list_all_tracks(video, self._tools.mkvmerge)
        finally:
            QApplication.restoreOverrideCursor()
        if not tracks:
            self.log.emit(f"無法讀取軌道: {video.name}")
            return
        dialog = ModifyTracksDialog(tracks, self._track_edits, self)
        if dialog.exec():
            self._track_edits = dialog.get_edits()
            self.modify_tracks_button.setText(
                "修改既有軌道…(已設定)" if self._has_track_edits()
                else "修改既有軌道…")

    # ---------- 執行 ----------
    def _on_run(self) -> None:
        if self._scan_thread is not None or self._thread is not None:
            self.log.emit("已有掃描或封裝進行中")
            return
        pairs = self.checked_pairs()
        if not pairs:
            self.log.emit("沒有勾選任何可封裝的影片")
            return
        try:
            operation = self.current_operation()
        except (ScaleError, ValueError) as exc:
            self.log.emit(f"參數錯誤: {exc}")
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
        self._worker = MuxWorker(pairs, self.current_meta(), operation,
                                 self._tools, output_dir,
                                 edits=self._track_edits)
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
        self.log.emit(f"封裝完成:成功 {ok},跳過 {skipped},錯誤 {error}")
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self.scan_button.setEnabled(True)
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self._refresh_modify_button()

    def shutdown(self) -> None:
        for thread in (self._thread, self._scan_thread):
            if thread is not None:
                thread.quit()
                thread.wait()

    # ---------- 設定持久化 ----------
    def save_settings(self, settings: QSettings) -> None:
        settings.setValue("mux/video_folder", self.video_edit.text())
        settings.setValue("mux/subtitle_folder", self.subtitle_edit.text())
        settings.setValue(
            "mux/output_mode",
            "replace" if self.replace_radio.isChecked() else "outdir")
        settings.setValue("mux/outdir", self.outdir_edit.text())

    def restore_settings(self, settings: QSettings) -> None:
        self.video_edit.setText(settings.value("mux/video_folder", ""))
        self.subtitle_edit.setText(settings.value("mux/subtitle_folder", ""))
        self.outdir_edit.setText(settings.value("mux/outdir", ""))
        if settings.value("mux/output_mode", "outdir") == "replace":
            self.replace_radio.setChecked(True)
        else:
            self.outdir_radio.setChecked(True)
