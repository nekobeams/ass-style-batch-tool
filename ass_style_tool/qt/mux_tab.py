"""「封裝」分頁:把外部 .ass 字幕依集數配對後 mux 進 MKV。"""
from __future__ import annotations

import dataclasses
from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, QByteArray, QSettings, QThread, Signal
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup,
                               QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QRadioButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..episode_match import find_files
from ..languages import LANGUAGES as _LANGUAGES
from ..mkv_batch import MkvTools
from ..mkv_mux import MuxMeta, MuxPair
from ..profile import Profile
from ..scale_engine import ScaleError
from ..style_scan import scan_styles, summarize
from ..tools import mkvextract_path, mkvmerge_path
from ..track_edit import TrackEdit
from .batch_worker import MuxScanWorker, MuxWorker, TrackScanWorker
from .gui_helpers import RESULT_ICONS, apply_plan_text, scale_plan_text
from .layout_helpers import (action_row, group, main_splitter, page_layout,
                             settings_sidebar)
from .modify_tracks_dialog import ModifyTracksDialog
from .scale_panel import ScalePanel
from .scan_progress_dialog import ScanProgressDialog
from .style_picker import StylePicker

_HEADERS = ["封裝", "影片", "字幕", "集數", "狀態", "預計 / 結果"]
_STATUS_LABELS = {"matched": "已配對", "no_subtitle": "無對應字幕",
                  "ambiguous": "配對模糊", "no_episode": "無法判斷集數"}
# 「原字幕直接封」不套用/縮放任何樣式,「預計 / 結果」欄沒有東西可預告;
# 但仍要顯示明確文字而不是留白——留白會跟「還沒算過」分不出來,尤其是
# 從套用/縮放模式切回來的當下,空白很容易被誤讀成「這裡本來就沒東西」。
_DIRECT_MODE_PLAN_TEXT = "直接封裝,不修改字幕"
# 常見字幕語言清單移到 ..languages(與 modify_tracks_dialog 的軌道語言欄
# 共用,避免同一份清單在兩處各自維護)。_LANGUAGES 這個名字繼續保留、
# re-export,既有呼叫端與測試都是這樣引用的。


class MuxTab(QWidget):
    log = Signal(str)

    def __init__(self, get_profile: Callable[[], Profile]) -> None:
        super().__init__()
        self._get_profile = get_profile
        self._pairs: List[MuxPair] = []
        self._available_subtitles: List[Path] = []
        self._file_styles: dict = {}   # subtitle_path -> FileStyles(「預計」欄用)
        self._thread: Optional[QThread] = None
        self._worker = None
        self._scan_thread: Optional[QThread] = None
        self._scan_worker = None
        self._scanned_key: Optional[tuple] = None
        self._track_edits: dict = {}
        self._track_edits_key: Optional[tuple] = None
        self._track_scan_thread: Optional[QThread] = None
        self._track_scan_worker = None
        self._track_scan_dialog: Optional[ScanProgressDialog] = None
        self._closing = False
        self._auto_scanned = False
        self.setAcceptDrops(True)

        mkvmerge = mkvmerge_path()
        mkvextract = mkvextract_path()
        self.tools_available = mkvmerge is not None and mkvextract is not None
        self._tools = (MkvTools(mkvmerge, mkvextract)
                       if self.tools_available else None)

        root = page_layout(self)
        if not self.tools_available:
            warn = QLabel("⚠ 找不到 mkvmerge:請安裝 MKVToolNix 後重新啟動"
                          "(封裝功能已停用)")
            warn.setStyleSheet("QLabel { color: #d08a00; }")
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

        # ----- 側欄:封裝前處理 -----
        pre_box = QVBoxLayout()
        self.direct_mode_radio = QRadioButton("原字幕直接封")
        self.direct_mode_radio.setChecked(True)
        self.apply_mode_radio = QRadioButton("先套用目前樣式")
        self.scale_mode_radio = QRadioButton("先縮放字級")
        for radio in (self.direct_mode_radio, self.apply_mode_radio,
                      self.scale_mode_radio):
            pre_box.addWidget(radio)
        self.scale_panel = ScalePanel()
        self.scale_panel.setHidden(True)
        pre_box.addWidget(self.scale_panel)
        self.scale_mode_radio.toggled.connect(self._on_preprocess_mode_changed)
        self.apply_mode_radio.toggled.connect(self._on_preprocess_mode_changed)

        self._preprocess_group = QButtonGroup(self)
        for radio in (self.direct_mode_radio, self.apply_mode_radio,
                      self.scale_mode_radio):
            self._preprocess_group.addButton(radio)

        # ----- 側欄:目標樣式 -----
        # group() 的第二參數收的是 QLayout(它會對其呼叫 setContentsMargins /
        # setSpacing),所以 picker 要先包一層 layout,不可直接傳 widget。
        self.style_picker = StylePicker()
        self.style_picker.changed.connect(self._on_styles_changed)
        style_box = QVBoxLayout()
        style_box.addWidget(self.style_picker)
        self.style_group = group("目標樣式", style_box)
        self.style_group.setHidden(True)

        # ----- 側欄:新字幕軌 -----
        meta_box = QVBoxLayout()
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("語言"))
        self.language_combo = QComboBox()
        for label, code in _LANGUAGES:
            self.language_combo.addItem(f"{label} ({code})", code)
        lang_row.addWidget(self.language_combo, 1)
        meta_box.addLayout(lang_row)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("軌名"))
        self.trackname_edit = QLineEdit()
        name_row.addWidget(self.trackname_edit, 1)
        meta_box.addLayout(name_row)
        flag_row = QHBoxLayout()
        self.default_check = QCheckBox("預設軌")
        self.forced_check = QCheckBox("強制軌")
        flag_row.addWidget(self.default_check)
        flag_row.addWidget(self.forced_check)
        flag_row.addStretch(1)
        meta_box.addLayout(flag_row)

        # ----- 側欄:既有軌道 -----
        old_box = QVBoxLayout()
        self.modify_tracks_button = QPushButton("修改既有軌道…")
        self.modify_tracks_button.setEnabled(False)
        self.modify_tracks_button.clicked.connect(self._on_modify_tracks)
        old_box.addWidget(self.modify_tracks_button)

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
        self.replace_radio = QRadioButton("取代原影片(驗證後覆蓋)")
        out_box.addWidget(self.replace_radio)

        self._output_group = QButtonGroup(self)
        self._output_group.addButton(self.outdir_radio)
        self._output_group.addButton(self.replace_radio)

        self.splitter = main_splitter(
            self.table,
            settings_sidebar(group("封裝前處理", pre_box),
                             self.style_group,
                             group("新字幕軌", meta_box),
                             group("既有軌道", old_box),
                             group("輸出", out_box)))
        root.addWidget(self.splitter, 1)

        self.scan_button = QPushButton("重新掃描")
        self.scan_button.clicked.connect(self._on_scan)
        self.run_button = QPushButton("開始封裝")
        self.run_button.setProperty("accent", True)
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._on_run)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        root.addLayout(action_row([self.scan_button],
                                  [self.run_button, self.cancel_button]))

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

    # ---------- 模式切換 ----------
    def _on_preprocess_mode_changed(self, _on: bool = False) -> None:
        self.scale_panel.setHidden(not self.scale_mode_radio.isChecked())
        # 只有「先套用目前樣式」才會讀 style_picker:current_operation() 在
        # 縮放模式回傳 scale_panel.get_options(),根本不會去看勾了哪些樣式
        # ——秀出來只會讓使用者以為勾選有作用,卻在執行時被靜默忽略。跟字幕
        # 檔分頁(subtitle_tab.py)的縮放模式是同一套語意,兩邊要維持一致。
        self.style_group.setHidden(not self.apply_mode_radio.isChecked())
        # 三種前處理模式各自的「預計」文字算法不同,切換當下必須重算整欄
        # (Task 10:同一個 Task 6 review 缺陷在這裡也有一份)。
        self._recompute_plan_column()
        self._refresh_run_button()

    # ---------- 掃描 ----------
    def _folders_ready(self) -> bool:
        """兩個資料夾都選好且真的存在才值得自動掃描。"""
        video = self.video_edit.text().strip()
        subtitle = self.subtitle_edit.text().strip()
        return bool(video and subtitle
                    and Path(video).is_dir() and Path(subtitle).is_dir())

    def auto_scan_once(self) -> None:
        """分頁第一次被顯示時自動掃描一次(主視窗切分頁時呼叫)。"""
        if self._auto_scanned:
            return
        if not self._folders_ready():
            return
        if self._thread is not None or self._scan_thread is not None:
            return
        self._auto_scanned = True
        self._on_scan()

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
        if self._closing:
            return
        if self._scan_thread is not None:
            self._scan_thread.quit()
            self._scan_thread.wait()
        self._scan_thread = None
        self._scan_worker = None
        self.scan_button.setEnabled(True)
        if self._track_edits and self._scanned_key != self._track_edits_key:
            # 換了一組影片/字幕資料夾:先前設定的軌道修改是依 track id 套用
            # 的,套到新資料夾的檔案上等於用錯誤的軌道 id 亂改,必須清掉。
            self._track_edits = {}
            self._track_edits_key = None
            self.modify_tracks_button.setText("修改既有軌道…")
        s = self.subtitle_edit.text().strip()
        if s and Path(s).is_dir():
            subs, _ = find_files(Path(s))
            self._available_subtitles = sorted(subs)
        matched_pairs = [p for p in pairs if p.subtitle_path is not None]
        results = [scan_styles(p.subtitle_path) for p in matched_pairs]
        summary = summarize(results)
        self.style_picker.set_available(summary.names)
        self._file_styles = dict(
            zip((p.subtitle_path for p in matched_pairs), results))
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
            self.table.setItem(
                r, 5, QTableWidgetItem(self._plan_text_for(pair)))
        self._refresh_run_button()
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
        # 手動指定的字幕檔通常沒掃過樣式(不在 self._file_styles 裡),
        # _plan_text_for() 對 file_styles=None 會自然回傳空字串——比留著
        # 前一個字幕檔算出來的舊「預計」文字被誤讀成這次的預告好。
        self.table.item(row, 5).setText(self._plan_text_for(new_pair))
        check = self.table.item(row, 0)
        check.setCheckState(
            Qt.CheckState.Checked if new_pair.status == "matched"
            else Qt.CheckState.Unchecked)
        self._refresh_run_button()
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
            return self.effective_profile()
        return None

    def effective_profile(self) -> Profile:
        """把側欄勾選的樣式名蓋進目前的 profile(與字幕檔分頁的作法相同)。"""
        return replace(self._get_profile(),
                       target_style_names=self.style_picker.selected())

    # ---------- 「預計 / 結果」欄 ----------
    def _plan_text_for(self, pair: MuxPair) -> str:
        """單一列的「預計」欄文字,依目前的封裝前處理模式分支。"""
        if self.direct_mode_radio.isChecked():
            return _DIRECT_MODE_PLAN_TEXT
        if pair.subtitle_path is None:
            return ""
        file_styles = self._file_styles.get(pair.subtitle_path)
        if self.scale_mode_radio.isChecked():
            try:
                options = self.scale_panel.get_options()
            except ScaleError:
                # 縮放參數還沒填完整:同一坑字幕檔分頁(subtitle_tab.py)的
                # _plans() 已經踩過,這裡不能留空白讓人誤讀成「還沒算過」。
                return "⚠ 縮放參數有誤"
            return scale_plan_text(file_styles, options)
        return apply_plan_text(file_styles, self.effective_profile(),
                               self.style_picker.selected())

    def _recompute_plan_column(self) -> None:
        """切換前處理模式、或目標樣式勾選改變時重算整欄。

        `_on_preprocess_mode_changed()`/`_on_styles_changed()` 都要呼叫
        這個——不然畫面會留著前一個模式(或前一次勾選)算出來的預告,
        被誤讀成「目前這個模式/勾選會這樣改」(跟字幕檔分頁同一個 Task 6
        review 發現、延到 Task 10 修的缺陷)。
        """
        for r, pair in enumerate(self._pairs):
            item = self.table.item(r, 5)
            if item is not None:
                item.setText(self._plan_text_for(pair))

    def mark_rows_pending(self) -> None:
        """開始封裝時把整欄換成「處理中…」,避免舊預告被誤讀成這次的結果。"""
        for r in range(self.table.rowCount()):
            self.table.setItem(r, 5, QTableWidgetItem("處理中…"))

    def _set_row_result(self, name: str, status: str) -> None:
        text = RESULT_ICONS.get(status, status)
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 1)          # 第 1 欄是影片檔名
            if item is not None and item.text() == name:
                self.table.setItem(r, 5, QTableWidgetItem(text))
                return

    def _output_dir(self) -> Optional[Path]:
        if self.replace_radio.isChecked():
            return None
        text = self.outdir_edit.text().strip()
        return Path(text) if text else None

    def _on_styles_changed(self) -> None:
        """套用模式的「預計」文字依目標樣式勾選而定,勾選一變就要重算。"""
        self._recompute_plan_column()
        self._refresh_run_button()

    def _refresh_run_button(self) -> None:
        # 「先套用目前樣式」一個樣式都沒勾等於這批不會改到任何東西,不該讓
        # 使用者按下去;直接封裝/先縮放字級不吃這個勾選,維持原本只看有沒
        # 有掃到可封裝的列。跟字幕檔分頁(subtitle_tab.py)的
        # _update_run_enabled() 是同一套邏輯。
        gated_by_styles = (self.apply_mode_radio.isChecked()
                           and not self.style_picker.selected())
        self.run_button.setEnabled(
            self.tools_available
            and any(p.status == "matched" for p in self._pairs)
            and self._thread is None
            and not gated_by_styles)

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
        if self._track_scan_thread is not None:
            self.log.emit("軌道掃描進行中")
            return
        matched = [p for p in self._pairs if p.status == "matched"]
        if not matched:
            self.log.emit("沒有可用的來源影片可掃描軌道")
            return
        self._track_scan_thread = QThread()
        self._track_scan_worker = TrackScanWorker(
            [p.video_path for p in matched], self._tools.mkvmerge)
        self._track_scan_worker.moveToThread(self._track_scan_thread)
        self._track_scan_thread.started.connect(self._track_scan_worker.run)
        self._track_scan_worker.finished.connect(self._on_track_scan_done)
        self._track_scan_worker.cancelled.connect(
            self._on_track_scan_cancelled)
        self._track_scan_dialog = ScanProgressDialog(self)
        self._track_scan_worker.progress.connect(
            self._track_scan_dialog.set_progress)
        self._track_scan_dialog.cancelled.connect(
            self._request_track_scan_cancel)
        self._track_scan_dialog.show()   # 非 exec():維持非同步流程
        self._track_scan_thread.start()

    def _request_track_scan_cancel(self) -> None:
        """直接呼叫 worker.cancel(),不用 signal→worker slot 的連線。

        worker 已 moveToThread,但該執行緒在 run() 執行期間不會跑事件迴圈,
        排隊的 cancel() 要等掃描結束才會被處理——等於完全沒有作用。
        """
        if self._track_scan_worker is not None:
            self._track_scan_worker.cancel()

    def _finish_track_scan(self) -> None:
        """完成/取消共用的收尾:關對話框、收執行緒。"""
        if self._track_scan_dialog is not None:
            self._track_scan_dialog.hide()
            self._track_scan_dialog.deleteLater()
            self._track_scan_dialog = None
        if self._track_scan_thread is not None:
            self._track_scan_thread.quit()
            self._track_scan_thread.wait()
        self._track_scan_thread = None
        self._track_scan_worker = None

    def _on_track_scan_done(self, tracks_by_file: dict) -> None:
        if self._closing:
            return
        self._finish_track_scan()
        if not any(tracks_by_file.values()):
            self.log.emit("所有影片都讀不到軌道資訊")
            return
        dialog = ModifyTracksDialog(tracks_by_file, self._track_edits, self)
        if dialog.exec():
            self._track_edits = dialog.get_edits()
            self._track_edits_key = self._scanned_key
            self.modify_tracks_button.setText(
                "修改既有軌道…(已設定)" if self._has_track_edits()
                else "修改既有軌道…")

    def _on_track_scan_cancelled(self) -> None:
        if self._closing:
            return
        self._finish_track_scan()
        self.log.emit("軌道掃描已取消")

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
        self.mark_rows_pending()

        self._thread = QThread()
        self._worker = MuxWorker(pairs, self.current_meta(), operation,
                                 self._tools, output_dir,
                                 edits=(self._track_edits
                                       if self._has_track_edits() else {}))
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_progress.connect(self.file_progress.setValue)
        self._worker.file_done.connect(
            lambda name, status: self.log.emit(f"[{status}] {name}"))
        self._worker.file_done.connect(self._set_row_result)
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
        # 不能直接把按鈕強制打開:跑批次期間使用者可能已經改動側欄勾選
        # (例如把唯一選的樣式取消勾),_refresh_run_button() 才會重新檢查
        # 目前狀態是否還滿足可執行的條件。
        self._refresh_run_button()
        self.cancel_button.setEnabled(False)
        self._refresh_modify_button()

    def shutdown(self) -> None:
        self._closing = True
        for worker in (self._worker, self._scan_worker,
                       self._track_scan_worker):
            if worker is not None and hasattr(worker, "cancel"):
                worker.cancel()
        for thread in (self._thread, self._scan_thread,
                       self._track_scan_thread):
            if thread is not None:
                thread.quit()
                thread.wait()
        # 沒有這行的話 _track_scan_thread/_worker/_dialog 會留著已被
        # quit() 的殘骸,之後排隊中的 cancelled signal 可能在 tab 已經
        # 拆完之後才觸發 _on_track_scan_cancelled。
        self._finish_track_scan()

    # ---------- 設定持久化 ----------
    def save_settings(self, settings: QSettings) -> None:
        settings.setValue("mux/video_folder", self.video_edit.text())
        settings.setValue("mux/subtitle_folder", self.subtitle_edit.text())
        settings.setValue(
            "mux/output_mode",
            "replace" if self.replace_radio.isChecked() else "outdir")
        settings.setValue("mux/outdir", self.outdir_edit.text())
        settings.setValue("mux/splitter", self.splitter.saveState())
        settings.setValue("mux/styles", self.style_picker.selected())

    def restore_settings(self, settings: QSettings) -> None:
        self.video_edit.setText(settings.value("mux/video_folder", ""))
        self.subtitle_edit.setText(settings.value("mux/subtitle_folder", ""))
        self.outdir_edit.setText(settings.value("mux/outdir", ""))
        if settings.value("mux/output_mode", "outdir") == "replace":
            self.replace_radio.setChecked(True)
        else:
            self.outdir_radio.setChecked(True)
        state = settings.value("mux/splitter")
        # 直接判斷型別而不是靠 QSettings 的 type= 參數:PySide6 在轉換失敗時
        # 並不會如預期回傳 None/預設值,而是把原始(型別不對的)值原樣回傳,
        # 傳進 restoreState() 一樣會炸——手改/遷移壞掉的設定值必須擋在這裡。
        if isinstance(state, QByteArray):
            self.splitter.restoreState(state)
        saved_styles = settings.value("mux/styles", [])
        if isinstance(saved_styles, str):     # QSettings 單元素清單會退化成字串
            saved_styles = [saved_styles]
        self.style_picker.set_selected(list(saved_styles or []))
