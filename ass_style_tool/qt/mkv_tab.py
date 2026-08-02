"""「MKV」分頁:列出資料夾內的 MKV、用規則選定要重新套樣式的舊字幕軌、批次重封裝。

分頁主畫面只列檔案。「要對哪幾條舊字幕軌套樣式」由「修改既有軌道…」對話框
控制:在範本檔上勾選,規則以 (語言, 軌名) 套用到整批影片。mkvmerge -J 只在
真的需要軌道資訊時才跑(開對話框、或尚未設定規則就按開始處理),選資料夾
本身不跑任何外部程序。
"""
from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import Qt, QByteArray, QSettings, QThread, Signal
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
from ..track_select import TrackKey, all_keys, resolve_tracks
from .batch_worker import MkvScanWorker, MkvWorker, TemplateStyleWorker
from .gui_helpers import CANCELLED_TEXT, PENDING_TEXT, RESULT_ICONS
from .layout_helpers import (action_row, group, main_splitter, page_layout,
                             settings_sidebar)
from .scale_panel import ScalePanel
from .scan_progress_dialog import ScanProgressDialog
from .select_tracks_dialog import SelectTracksDialog
from .style_picker import StylePicker

_HEADERS = ["MKV", "將套用的軌", "結果"]


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
        self._template_thread: Optional[QThread] = None
        self._template_worker = None
        self._template_video_name: Optional[str] = None
        self._scan_dialog: Optional[ScanProgressDialog] = None
        self._scanned_folder: Optional[str] = None
        self._auto_scanned = False
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
        # 「結果」欄跟另外兩個分頁的「預計 / 結果」欄是同一組 RESULT_ICONS
        # 文字,一樣沒有 resize 政策時會被裁到剩幾個字(Minor bullet)。
        self.file_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents)

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
        self.scale_mode_radio.toggled.connect(self._on_mode_changed)

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

        # ----- 側欄:目標樣式 -----
        # group() 的第二參數收的是 QLayout(它會對其呼叫 setContentsMargins /
        # setSpacing),所以 picker 要先包一層 layout,不可直接傳 widget。
        # 字幕在檔案內,樣式名要按需從第一個影片抽一條字幕軌讀出來(見
        # read_template_styles()),不像另外兩個分頁掃資料夾時就能順便讀到。
        self.style_picker = StylePicker()
        self.style_picker.changed.connect(self._refresh_run_button)
        style_box = QVBoxLayout()
        style_box.addWidget(self.style_picker)
        self.read_styles_button = QPushButton("讀取樣式名稱")
        self.read_styles_button.clicked.connect(self.read_template_styles)
        style_box.addWidget(self.read_styles_button)
        self.style_group = group("目標樣式", style_box)
        # 「縮放字級」模式的執行路徑走 scale_panel.get_options(),完全不讀
        # style_picker——秀出來只會讓使用者以為勾選有作用,卻在執行時被
        # 靜默忽略。跟封裝分頁(mux_tab.py)的作法一致,整組隨模式隱藏。
        self.style_group.setHidden(not self.apply_mode_radio.isChecked())

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
                             self.style_group,
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
                      self.preview_button, self.run_button,
                      self.read_styles_button):
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

    def auto_scan_once(self) -> None:
        """分頁第一次被顯示時自動掃描一次(主視窗切分頁時呼叫)。"""
        if self._auto_scanned:
            return
        folder = self.folder_edit.text().strip()
        if not folder or not Path(folder).is_dir():
            return
        if self._thread is not None or self._scan_thread is not None:
            return
        self._auto_scanned = True
        self._on_scan()

    # ---------- 模式切換 ----------
    def _on_mode_changed(self, scale_mode: bool) -> None:
        self.scale_panel.setHidden(not scale_mode)
        self.style_group.setHidden(scale_mode)
        self._refresh_run_button()

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
            # 這個分頁沒有逐檔「預計」(字幕在容器裡,要 mkvextract 才讀得
            # 到),「結果」欄重新列出時一律回到空白,不留上一輪批次的
            # 舊結果被誤讀成這次的。
            self.file_table.setItem(row, 2, QTableWidgetItem(""))
        self._refresh_track_column()
        self._refresh_run_button()

    # ---------- 「結果」欄 ----------
    def mark_rows_pending(self) -> None:
        """開始處理時把「這批真的會跑」的列換成「處理中…」。

        MkvWorker 只吃 current_jobs()(勾選且依目前規則解析出至少一條
        軌道的檔案),未勾選、或勾選但目前規則下沒有可套用軌道的檔案本來
        就不在這批工作內,若整欄一律標成處理中,跑完之後這些列既不會
        收到 file_done、也沒有任何收尾邏輯會去碰它們,就會永遠卡在
        「處理中…」——這裡必須用跟 current_jobs() 同一份判斷結果
        (Task 10 review Finding 1)。
        """
        job_names = {path.name for path, _tracks in self.current_jobs()}
        for row, path in enumerate(self._files):
            if path.name in job_names:
                self.file_table.setItem(row, 2, QTableWidgetItem(PENDING_TEXT))

    def _reconcile_stuck_rows(self) -> None:
        """收尾時把還卡在 PENDING_TEXT 的列換成明確標記。

        使用者取消處理時 MkvWorker 一偵測到取消旗標就直接 break,還沒
        輪到的列不會收到 file_done,不能留著被誤讀成還在處理中,或跟
        這次批次的結果搞混(Task 10 review Finding 2)。
        """
        for r in range(self.file_table.rowCount()):
            item = self.file_table.item(r, 2)
            if item is not None and item.text() == PENDING_TEXT:
                self.file_table.setItem(r, 2, QTableWidgetItem(CANCELLED_TEXT))

    def _set_row_result(self, name: str, status: str) -> None:
        # 用檔名比對回表格列:這只有在資料夾掃描不遞迴(不會有兩個 MKV
        # 同名)的前提下才安全——future 若改成遞迴掃描,這裡的比對邏輯
        # 也要一併換成完整路徑,否則同名檔案的結果會被誤套到錯的列。
        text = RESULT_ICONS.get(status, status)
        for r in range(self.file_table.rowCount()):
            item = self.file_table.item(r, 0)     # 第 0 欄是 MKV 檔名
            if item is not None and item.text() == name:
                self.file_table.setItem(r, 2, QTableWidgetItem(text))
                return

    def checked_files(self) -> List[Path]:
        return [path for row, path in enumerate(self._files)
                if self.file_table.item(row, 0).checkState()
                == Qt.CheckState.Checked]

    def current_files(self) -> List[Path]:
        """目前列出的影片路徑清單(不論勾選狀態)。

        給 read_template_styles() 取「第一個影片」當範本用;範本檔跟批次
        要不要套用某一檔無關,所以不像 checked_files() 只看有勾的。
        """
        return list(self._files)

    def _refresh_run_button(self) -> None:
        """依目前狀態(檔案、工具、模式、是否忙碌)重新計算執行鈕可不可按。

        「套用樣式」模式下沒勾任何目標樣式等於這批不會改到任何東西,不該
        讓使用者按下去;「縮放字級」模式不吃這個勾選(scale_panel 已經自
        己給齊所有需要的參數),維持原本只看有沒有檔案的邏輯。跟字幕檔/
        封裝分頁(subtitle_tab.py / mux_tab.py)是同一套語意。
        """
        gated_by_styles = (self.apply_mode_radio.isChecked()
                           and not self.style_picker.selected())
        self.run_button.setEnabled(
            bool(self._files) and self.tools_available
            and self._thread is None and not gated_by_styles)

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
        files = [p for p in self.checked_files() if p not in self._files_tracks]
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
            template_path = next(
                (p for p in sorted(available, key=lambda p: p.name)
                 if available[p]),
                None)
            template_keys = (all_keys({template_path: available[template_path]})
                             if template_path is not None else set())
            # 對話框只能顯示/切換範本檔本身有的鍵;既有規則裡範本檔沒有的鍵,
            # 對話框根本無從呈現,重開一次就會被靜默清掉——保留它們,只有
            # 範本檔真的能顯示的鍵才依使用者這次的勾選結果更新。
            preserved = (self._track_keys or set()) - template_keys
            self._apply_keys(dialog.get_keys() | preserved)

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

    # ---------- 範本檔樣式讀取 ----------
    def read_template_styles(self) -> None:
        """從第一個影片抽一條文字字幕軌,讀出樣式名稱當範本。

        不逐檔抽取:一季全抽很慢,而使用者的情境是全季樣式名一致,
        一個範本檔就夠。與「修改既有軌道」對話框同一種心智模型。

        抽取(mkvmerge -J)+ 解析都丟到背景執行緒跑,不在這個 slot 裡
        直接呼叫——兩段子行程加起來逾時上限有 360 秒,擺在 GUI 執行緒上
        視窗會整個「沒有回應」(最終審查 I8)。
        """
        if self._template_thread is not None:
            self.log.emit("正在讀取樣式名稱,請稍候")
            return
        files = self.current_files()
        if not files:
            self.log.emit("請先掃描資料夾")
            return
        mkvmerge, mkvextract = mkvmerge_path(), mkvextract_path()
        if mkvmerge is None or mkvextract is None:
            self.log.emit("找不到 MKVToolNix,無法讀取樣式名稱")
            return
        self._template_video_name = files[0].name
        self.read_styles_button.setEnabled(False)
        self._template_thread = QThread()
        self._template_worker = TemplateStyleWorker(
            files[0], mkvmerge, mkvextract, self._preview_dir)
        self._template_worker.moveToThread(self._template_thread)
        self._template_thread.started.connect(self._template_worker.run)
        self._template_worker.finished.connect(self._on_template_styles_done)
        self._template_thread.start()

    def _on_template_styles_done(self, result) -> None:
        if self._closing:
            # shutdown() 對 _template_thread 呼叫 wait() 之後,worker 執行
            # 緒排隊的 finished 訊號會在下一輪事件迴圈才送達——這時分頁
            # 可能已經在銷毀路上,touch read_styles_button/style_picker/
            # log 這些元件會有踩到已銷毀物件的風險。跟 _on_track_scan_done
            # 、mux_tab._on_scan_done() 同一個理由,同一個防護。
            return
        if self._template_thread is not None:
            self._template_thread.quit()
            self._template_thread.wait()
        self._template_thread = None
        self._template_worker = None
        self.read_styles_button.setEnabled(True)
        name = self._template_video_name
        extraction = result.extraction
        if extraction.path is None:
            if extraction.error == "extract_failed":
                self.log.emit(f"抽取 {name} 的字幕軌失敗,"
                              "無法讀取樣式名稱(檔案可能損壞或磁碟空間不足)")
            elif extraction.error == "identify_failed":
                # 連 mkvmerge -J 都沒問出這個檔案有哪些軌(逾時、檔案損毀
                # /被占用、mkvmerge 當掉、輸出不是合法 JSON),根本不知道
                # 有沒有字幕軌——不能跟下面「確認過就是沒有」的訊息混在
                # 一起講,那會把使用者導去錯的排查方向(以為片源是圖形
                # 字幕,實際上可能是檔案損毀或 MKVToolNix 出問題)。
                self.log.emit(
                    f"無法讀取 {name} 的字幕軌清單"
                    "(mkvmerge 執行失敗、逾時,或檔案已損毀/被占用)")
            elif extraction.error == "no_track":
                # Minor bullet:只抽了第一個檔案當範本(見
                # read_template_styles() 開頭的 docstring),訊息卻原本講
                # 「這批影片」,會讓人誤以為整批都檢查過了、全部都沒有
                # 文字字幕軌——其實後面的檔案根本沒被碰過。改成點名第一
                # 個檔案,不擴大成整批的結論。
                self.log.emit(
                    f"{name} 沒有文字字幕軌,無法讀取樣式名稱"
                    "(可能是 PGS/VobSub 圖形字幕;只檢查了第一個影片,"
                    "其餘影片未逐一確認)")
            else:
                # 最終審查 Minor:這裡原本是無條件 else,把任何未知的
                # error 值都當成「確認過沒有字幕軌」講——這正是 I9 那次
                # 修的同一種錯:「不知道」被講成「確定沒有」。三個已知原因
                # 都比對過還落到這裡,代表 TemplateExtraction 出現了目前
                # 沒處理過的新原因,老實講出來,不要冒充成確定的結論。
                self.log.emit(
                    f"讀取 {name} 的樣式名稱失敗(原因:{extraction.error})")
            return
        styles = result.styles
        if styles.error is not None:
            self.log.emit(f"範本字幕解析失敗:{styles.error}")
            return
        self.style_picker.set_available(sorted(styles.styles))
        self.log.emit(f"從 {name} 讀到 {len(styles.styles)} 個樣式")

    def effective_profile(self) -> Profile:
        """把側欄勾選的樣式名蓋進目前的 profile(與其他兩個分頁的作法相同)。"""
        return replace(self._get_profile(),
                       target_style_names=self.style_picker.selected())

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
                operation = self.effective_profile()
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
        self.mark_rows_pending()

        self._thread = QThread()
        self._worker = MkvWorker(jobs, operation, self._tools, output_dir)
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
        self.log.emit(f"MKV 批次完成:成功 {ok},跳過 {skipped},錯誤 {error}")
        self._reconcile_stuck_rows()
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
        self.modify_tracks_button.setEnabled(self.tools_available)
        self.cancel_button.setEnabled(False)

    # ---------- 清理 ----------
    def shutdown(self) -> None:
        self._closing = True
        for worker in (self._worker, self._scan_worker):
            if worker is not None:
                worker.cancel()
        for thread in (self._thread, self._scan_thread, self._template_thread):
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
        settings.setValue("mkv/styles", self.style_picker.selected())

    def restore_settings(self, settings: QSettings) -> None:
        self.folder_edit.setText(settings.value("mkv/folder", ""))
        self.outdir_edit.setText(settings.value("mkv/outdir", ""))
        if settings.value("mkv/output_mode", "outdir") == "replace":
            self.replace_radio.setChecked(True)
        else:
            self.outdir_radio.setChecked(True)
        state = settings.value("mkv/splitter")
        # 直接判斷型別而不是靠 QSettings 的 type= 參數:PySide6 在轉換失敗時
        # 並不會如預期回傳 None/預設值,而是把原始(型別不對的)值原樣回傳,
        # 傳進 restoreState() 一樣會炸——手改/遷移壞掉的設定值必須擋在這裡。
        if isinstance(state, QByteArray):
            self.splitter.restoreState(state)
        saved_styles = settings.value("mkv/styles", [])
        if isinstance(saved_styles, str):     # QSettings 單元素清單會退化成字串
            saved_styles = [saved_styles]
        self.style_picker.set_selected(list(saved_styles or []))
