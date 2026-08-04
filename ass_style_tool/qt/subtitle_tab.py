"""「字幕檔」分頁:選/拖資料夾、掃描預覽、批次執行(執行緒)+ 進度 + 取消。"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QByteArray, QSettings, QThread, Signal
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QFileDialog,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QRadioButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..batch_runner import scan_folder
from ..profile import Profile
from ..scale_engine import ScaleError, read_as_ass_text, scale_text
from ..style_scan import summarize
from .batch_worker import BatchWorker, ScaleWorker
from .gui_helpers import (CANCELLED_TEXT, PENDING_TEXT, RESULT_ICONS,
                          apply_plan_text, preview_rows, scale_plan_text)
from .layout_helpers import (action_row, group, main_splitter, page_layout,
                             settings_sidebar)
from .scale_panel import ScalePanel
from .style_picker import StylePicker

_HEADERS = ["集數", "字幕檔", "影片檔", "狀態", "預計 / 結果"]


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
        self._auto_scanned = False
        self.setAcceptDrops(True)

        root = page_layout(self)

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

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        # 「預計 / 結果」欄的文字長度變化很大(例如
        # 「Default 48 → 72、Sign 30 → 45」),沒有 resize 政策時會被裁到
        # 剩幾個字。跟著內容自動撐寬,不吃字幕檔欄(欄 1)已經佔走的
        # Stretch 名額(Minor bullet)。
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeToContents)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)

        # ----- 設定側欄:操作模式 -----
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

        # ----- 設定側欄:輸出 -----
        out_box = QVBoxLayout()
        self.inplace_radio = QRadioButton("原地覆蓋(備份 .bak)")
        self.inplace_radio.setChecked(True)
        self.outdir_radio = QRadioButton("輸出到資料夾")
        out_box.addWidget(self.inplace_radio)
        out_box.addWidget(self.outdir_radio)
        outdir_row = QHBoxLayout()
        self.outdir_edit = QLineEdit()
        out_browse = QPushButton("…")
        out_browse.setMaximumWidth(32)
        out_browse.clicked.connect(self._browse_out)
        outdir_row.addWidget(self.outdir_edit, 1)
        outdir_row.addWidget(out_browse)
        out_box.addLayout(outdir_row)

        self._output_group = QButtonGroup(self)
        self._output_group.addButton(self.inplace_radio)
        self._output_group.addButton(self.outdir_radio)

        # ----- 設定側欄:目標樣式 -----
        # group() 的第二參數收的是 QLayout(它會對其呼叫 setContentsMargins /
        # setSpacing),所以 picker 要先包一層 layout,不可直接傳 widget。
        self.style_picker = StylePicker()
        self.style_picker.changed.connect(self._on_styles_changed)
        style_box = QVBoxLayout()
        style_box.addWidget(self.style_picker)
        self.style_group = group("目標樣式", style_box)
        # 縮放模式的執行路徑走 scale_panel.get_options(),完全不讀
        # style_picker(_plans() 的縮放分支也不看它)——秀出來只會讓使用者
        # 以為勾選有作用,卻在執行時被靜默忽略,還會讓 StylePicker 在
        # 「掃描成功、什麼都沒勾」時顯示的提示「請勾選要套用的目標樣式」
        # 在縮放模式下對使用者下了一個沒有效果的指令(最終審查 Finding
        # 3)。跟封裝/MKV 分頁(mux_tab.py / mkv_tab.py)一致,整組隨模式
        # 隱藏。
        self.style_group.setHidden(self.scale_mode_radio.isChecked())

        self.splitter = main_splitter(
            self.table,
            settings_sidebar(group("操作模式", mode_box),
                             self.style_group,
                             group("輸出", out_box)))
        root.addWidget(self.splitter, 1)

        self.scan_button = QPushButton("重新掃描")
        self.scan_button.clicked.connect(self._on_scan)
        self.dry_run_button = QPushButton("試算預覽(不寫檔)")
        self.dry_run_button.setEnabled(False)
        self.dry_run_button.clicked.connect(self._on_dry_run)
        self.open_out_button = QPushButton("開啟輸出資料夾")
        self.open_out_button.clicked.connect(self._open_output)
        self.run_button = QPushButton("開始套用樣式")
        self.run_button.setProperty("accent", True)
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._on_run)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        root.addLayout(action_row(
            [self.scan_button, self.dry_run_button, self.open_out_button],
            [self.run_button, self.cancel_button]))

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
        # 掃描現在會逐檔跑 ffprobe + 樣式解析,不是瞬間完成,所以跟批次
        # 執行一樣要能取消、也要能看到進度(Finding 4)——沿用同一顆
        # 進度條與取消鈕,不另外加 UI 元件。
        self.cancel_button.setEnabled(True)
        self.progress.setValue(0)
        self._scan_thread = QThread()
        self._scan_worker = ScanWorker(Path(folder))
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        # 銷毀時機交給 Qt,不要留給 Python GC:worker 的 affinity 在這條
        # 執行緒上,thread.finished 是唯一能安全刪掉它的時機——Qt 在
        # QThreadPrivate::finish() 裡發完 finished 之後,會緊接著替這條
        # 執行緒送出一輪 DeferredDelete,所以 worker 的 C++ 物件會在
        # wait() 回來之前就確定銷毀。反過來在 wait() 之後才呼叫
        # worker.deleteLater() 是無效的:那時事件迴圈已經停了,刪除事件
        # 永遠不會被處理(等於洩漏)。見 _on_scan_finished() 的收尾說明,
        # 跟 mkv_tab.py/mux_tab.py 同一組修正、同一個理由。
        self._scan_thread.finished.connect(self._scan_worker.deleteLater)
        self._scan_worker.progress.connect(self._on_progress)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_thread.start()

    def _on_scan_finished(self, scan) -> None:
        self._scan = scan
        for w in scan.warnings:
            self.log.emit(f"警告: {w}")
        summary = summarize(list(getattr(scan, "styles", {}).values()))
        self.style_picker.set_available(summary.names)
        if summary.inconsistent:
            self.log.emit(
                f"注意:有 {len(summary.inconsistent)} 個檔案的樣式組合與其他檔不同")
        for path in summary.unreadable:
            self.log.emit(f"警告:無法解析樣式 {path.name}")
        self.scan_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if self._scan_thread is not None:
            self._scan_thread.quit()
            self._scan_thread.wait()
            # deleteLater() 的重點不是「盡快刪掉」,而是把這個 QThread 的
            # 所有權從 Python 手上交給 Qt:只設 = None 的話,分頁與執行緒
            # /worker 之間的訊號連線構成參照循環,refcount 歸不了零,C++
            # 物件最後是被 Python 的分代 GC 回收的——GC 的時機不可控,可
            # 能落在 Qt 正在派送事件的中途,與 widget 銷毀交錯,造成
            # Windows heap corruption(0xc0000374)。呼叫過 deleteLater()
            # 之後 GC 就再也不是銷毀者,改由 Qt 的事件迴圈負責。
            # 此時執行緒已經 wait() 過、不再運轉,QThread 物件本身的
            # affinity 在 GUI 執行緒,刪除事件送得到,與 worker 的情況不同。
            self._scan_thread.deleteLater()
        # 一定要在 populate_preview()(內部會呼叫 _update_run_enabled()/
        # _update_dry_run_enabled())之前把這兩個清空:這兩個函式把
        # self._scan_thread is not None 算進「忙碌」,如果 populate_preview
        # 在這裡之前執行,算出來的按鈕狀態永遠是「忙碌」,掃描結束後也
        # 沒有其他地方會再重算一次,執行鈕就這樣被永久鎖死(Finding 1)。
        self._scan_thread = None
        self._scan_worker = None
        count = self.populate_preview(scan)
        if scan.cancelled:
            # 使用者取消時 scan.styles 只有取消點之前已經解析完的檔案,
            # 不能沿用「掃描完成」的措辭,那會讓使用者誤以為整個資料夾
            # 都掃過了,實際上尾端的檔案根本沒被讀取(Finding 3)。
            completed = len(getattr(scan, "styles", {}))
            total = len(scan.matches)
            self.log.emit(f"掃描已取消:僅完成 {completed}/{total} 個字幕檔的解析")
            # 讓後續的自動掃描(資料夾切換/分頁切換)真的會重掃一次,
            # 而不是被「已經掃過這個資料夾」的記錄擋掉,永遠停在這份
            # 不完整的結果上。
            self._scanned_folder = None
            self._auto_scanned = False
        else:
            self.log.emit(f"掃描完成:共 {count} 個字幕檔")

    def populate_preview(self, scan) -> int:
        rows = preview_rows(scan, self._plans())
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(
                    (row.episode, row.sub_name, row.video_name,
                     row.status_label, row.plan)):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self._update_run_enabled()
        self._update_dry_run_enabled()
        return len(rows)

    def _plans(self) -> dict:
        """每個字幕檔的「預計」欄文字。掃描結果尚未有樣式資訊時回傳空的。"""
        if self._scan is None:
            return {}
        styles = getattr(self._scan, "styles", {})
        if self.scale_mode_radio.isChecked():
            try:
                options = self.scale_panel.get_options()
            except ScaleError:
                # 縮放參數還沒填完整(例如倍率欄位空著):這裡會在「掃描完成
                # → 切到縮放模式 → 清空/弄壞縮放欄位 → 勾選側欄樣式」等任一
                # 動作觸發的重算路徑上被打到,不能讓半成品輸入把整個預覽
                # 表格炸掉,但也不能留空白格——空白跟「還沒算過」分不出來,
                # 所以每一列都要跟其他早退路徑一樣秀出明確的標記。
                return {path: "⚠ 縮放參數有誤" for path in styles}
            return {path: scale_plan_text(fs, options)
                    for path, fs in styles.items()}
        try:
            profile = self.effective_profile()
        except ValueError:
            # C1(最終審查 Finding):effective_profile() → _get_profile()
            # → profile_from_values() 在編輯器欄位目前是壞的時候(例如
            # 字型名稱清空、字體大小改成非數字、對齊超出 1-9——編輯器
            # 欄位沒有即時驗證,打一個鍵就能踩到)會拋 ValueError。這個
            # 例外絕不能往上竄出呼叫這裡的 Qt slot(_on_scan_finished 等):
            # PySide6 會印出 traceback 但吞掉例外,slot 提前中斷,
            # scan_button 重新啟用、_scan_thread/_scan_worker 清空等收尾
            # 動作永遠不會執行,分頁就此靜默卡死一整個 session。跟縮放
            # 參數有誤走同一套處理方式:每一列都秀出明確標記,不讓
            # 半成品輸入把整個預覽表格炸掉。
            return {path: "⚠ 樣式設定有誤" for path in styles}
        names = self.style_picker.selected()
        return {path: apply_plan_text(fs, profile, names)
                for path, fs in styles.items()}

    def effective_profile(self) -> Profile:
        """把側欄勾選的樣式名蓋進目前的 profile。

        profile 描述「改成什麼樣子」,勾選描述「這批要改哪個」,兩者
        分開存放(勾選存 QSettings),執行時才合起來。
        """
        return replace(self._get_profile(),
                       target_style_names=self.style_picker.selected())

    def _on_styles_changed(self) -> None:
        if self._scan is None:
            return
        if self._thread is not None:
            # 批次執行中:表格欄位已經寫進真正的處理結果或「處理中…」
            # 標記,這時候用「當下」(可能剛被使用者改動)的勾選重算整欄
            # 會把這些已經定案的內容蓋掉,變成看不出來是不是這次批次寫的
            # 預測文字,也讓 _reconcile_stuck_rows() 掃不到(它只認
            # PENDING_TEXT)(Finding 1)。跑批次期間只更新按鈕可用狀態,
            # 不重畫表格;等批次結束後使用者若還想看新選擇的預告,重新
            # 掃描或再次改動勾選都會觸發正常的重畫。
            self._update_run_enabled()
            self._update_dry_run_enabled()
            return
        self.populate_preview(self._scan)

    def _update_run_enabled(self) -> None:
        has_rows = self.table.rowCount() > 0
        # 重新掃描進行中也算「忙碌」:_scan 隨時可能被 _on_scan_finished
        # 換成新的內容,這時候開放執行按鈕會讓使用者對著即將作廢的舊
        # scan 按下開始(Finding 2)。
        busy = self._thread is not None or self._scan_thread is not None
        if self.scale_mode_radio.isChecked():
            # 縮放模式不吃側欄的目標樣式勾選(ScalePanel.get_options() 已經
            # 自己給齊所有需要的參數),所以按鈕只看有沒有掃到列、有沒有在跑。
            self.run_button.setEnabled(has_rows and not busy)
        else:
            has_styles = bool(self.style_picker.selected())
            self.run_button.setEnabled(has_rows and has_styles and not busy)

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

    # ---------- 「預計 / 結果」欄的狀態轉換 ----------
    def mark_rows_pending(self) -> None:
        """開始執行時把整欄換成「處理中…」,避免舊預告被誤讀成這次的結果。

        字幕檔分頁的表格列跟 BatchWorker/ScaleWorker 實際處理的工作是
        1:1 對應的——populate_preview() 只依 scan.matches 建列,_on_run()
        也是把整個 scan.matches 交給 worker,不像封裝/MKV 分頁還有
        「勾選」「配對成功」等篩選,所以這裡不需要像那兩個分頁一樣做
        子集過濾(Task 10 review Finding 1 只在那兩個分頁成立)。
        """
        for r in range(self.table.rowCount()):
            self.table.setItem(r, 4, QTableWidgetItem(PENDING_TEXT))

    def _reconcile_stuck_rows(self) -> None:
        """收尾時把還卡在 PENDING_TEXT 的列換成明確標記。

        取消批次時 BatchWorker/ScaleWorker 一偵測到取消旗標就直接
        break,還沒輪到的列不會收到 file_done,不能留著被誤讀成還在
        處理中,或跟這次批次的結果搞混(Task 10 review Finding 2)。
        """
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 4)
            if item is not None and item.text() == PENDING_TEXT:
                self.table.setItem(r, 4, QTableWidgetItem(CANCELLED_TEXT))

    def _set_row_result(self, name: str, status: str) -> None:
        # 用檔名比對回表格列:這只有在資料夾掃描不遞迴(不會有兩個字幕檔
        # 同名)的前提下才安全——future 若改成遞迴掃描,這裡的比對邏輯
        # 也要一併換成完整路徑,否則同名檔案的結果會被誤套到錯的列。
        text = RESULT_ICONS.get(status, status)
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 1)          # 第 1 欄是字幕檔名
            if item is not None and item.text() == name:
                self.table.setItem(r, 4, QTableWidgetItem(text))
                return

    def _on_row_double_clicked(self, row: int, _column: int) -> None:
        if self._scan is None or row >= len(self._scan.matches):
            return
        match = self._scan.matches[row]
        self.preview_requested.emit(match.sub_path, match.video_path)

    # ---------- 模式切換 / 試算預覽 ----------
    def _on_mode_changed(self, scale_mode: bool) -> None:
        self.scale_panel.setHidden(not scale_mode)
        self.style_group.setHidden(scale_mode)
        self.run_button.setText("開始縮放" if scale_mode else "開始套用樣式")
        # 套用/縮放兩種模式的「預計」文字算法不同(_plans() 依模式分支),
        # 切模式當下必須重算整欄,不然畫面會留著前一個模式算出來的預告,
        # 被誤讀成「這個模式會這樣改」。populate_preview() 已經把
        # _update_run_enabled()/_update_dry_run_enabled() 包在裡面,尚未
        # 掃描過(self._scan is None)時才需要另外呼叫。
        if self._scan is not None:
            if self._thread is not None:
                # 批次執行中:跟 _on_styles_changed() 同一個理由——表格
                # 欄位已經寫進真正的處理結果或「處理中…」標記,這時候
                # 整欄重畫會把已定案的內容蓋掉,也會讓
                # _reconcile_stuck_rows() 掃不到(它只認 PENDING_TEXT)。
                # 模式切換鈕本身在批次執行中不會被停用(_on_run 只停用
                # scan_button/run_button/dry_run_button),所以這裡跟
                # _on_styles_changed() 一樣只更新按鈕可用狀態,不重畫表格。
                self._update_run_enabled()
                self._update_dry_run_enabled()
            else:
                self.populate_preview(self._scan)
        else:
            self._update_dry_run_enabled()
            self._update_run_enabled()

    def _update_dry_run_enabled(self) -> None:
        # 跟其餘三個忙碌判斷點(_update_run_enabled、_auto_scan、
        # auto_scan_once)看齊,重新掃描進行中(self._scan_thread)也要算
        # 忙碌:self._scan 隨時可能被 _on_scan_finished 換掉,不能讓試算
        # 預覽讀取即將作廢的舊 scan(Finding 4)。
        self.dry_run_button.setEnabled(
            self.scale_mode_radio.isChecked() and self._scan is not None
            and len(self._scan.matches) > 0 and self._thread is None
            and self._scan_thread is None)

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
        if (self._scan is None or self._thread is not None
                or self._scan_thread is not None):
            # 掃描或批次執行緒仍在跑的時候拒絕開始新的一批:_scan 在
            # rescan 完成前都是「即將被換掉」的舊資料,這裡若照跑,批次會
            # 對著就快被取代的 scan 動作,等 rescan 落地後 _on_scan_finished
            # 又會在批次跑到一半時整個重建表格,破壞 mark_rows_pending()
            # 「表格列與正在跑的工作 1:1 對應」的假設(Finding 2)。
            return
        if self.scale_mode_radio.isChecked():
            try:
                payload = self.scale_panel.get_options()
            except ScaleError as exc:
                self.log.emit(f"參數錯誤: {exc}")
                return
        else:
            try:
                payload = self.effective_profile()
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
        self.mark_rows_pending()

        self._thread = QThread()
        if self.scale_mode_radio.isChecked():
            self._worker = ScaleWorker(self._scan, payload, self._output_dir())
        else:
            self._worker = BatchWorker(self._scan, payload, self._output_dir())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        # 見 _on_scan() 的說明:worker 的銷毀要綁在 thread.finished 上,
        # 不能等 Python GC,也不能在 wait() 之後才 deleteLater()。
        self._thread.finished.connect(self._worker.deleteLater)
        self._worker.progress.connect(self._on_progress)
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
        # 批次執行與掃描共用同一顆取消鈕(Finding 4):兩者理論上不會
        # 同時在跑(Finding 2 已經讓 _on_run/_update_run_enabled 把兩個
        # 執行緒都算進忙碌判斷),但這裡兩個都檢查一次,不去假設呼叫方
        # 一定遵守那個互斥關係。
        cancelled = False
        if self._worker is not None:
            self._worker.cancel()
            cancelled = True
        if self._scan_worker is not None:
            self._scan_worker.cancel()
            cancelled = True
        if cancelled:
            self.cancel_button.setEnabled(False)

    def _on_finished(self, ok: int, skipped: int, error: int) -> None:
        self.log.emit(f"完成:成功 {ok},跳過 {skipped},錯誤 {error}")
        self._reconcile_stuck_rows()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            # 見 _on_scan_finished():把 QThread 的所有權交給 Qt,不要留給
            # GC。
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self.scan_button.setEnabled(True)
        # 不能直接把按鈕強制打開:跑批次的期間使用者可能已經改動側欄勾選
        # (例如把唯一選的樣式取消勾),_update_run_enabled() 才會重新檢查
        # 目前的狀態是否還滿足可執行的條件。
        self._update_run_enabled()
        self.cancel_button.setEnabled(False)
        self._update_dry_run_enabled()

    def shutdown(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        if self._scan_worker is not None:
            # ScanWorker.run() 是一次跑到底的單一呼叫,thread.quit() 只會
            # 要求事件迴圈退出、不會中斷它,沒有先呼叫 cancel() 讓
            # scan_folder() 的 should_cancel 檢查點生效的話,下面的
            # thread.wait() 會卡到掃描自然跑完為止(Finding 3)。
            self._scan_worker.cancel()
        for thread in (self._thread, self._scan_thread):
            if thread is not None:
                thread.quit()
                thread.wait()
                # 見 _on_scan_finished():把 QThread 的所有權交給 Qt,不要
                # 留給 GC。
                thread.deleteLater()
        # wait() 回來的當下,綁在 thread.finished 上的 worker.deleteLater()
        # 已經讓 worker 的 C++ 物件銷毀完畢,所以參照都必須放掉——留著就是
        # 一個指向已銷毀 C++ 物件的空殼 wrapper,之後任何人再去 touch 它
        # (例如又呼叫一次 shutdown() 裡的 worker.cancel())就會炸
        # RuntimeError。_on_finished()/_on_scan_finished() 這兩條正常收尾
        # 路徑在批次/掃描執行中呼叫 shutdown() 時並不會跑,跟
        # mkv_tab.py/mux_tab.py 的 shutdown() 同一個理由,同一個補法。
        self._thread = None
        self._worker = None
        self._scan_thread = None
        self._scan_worker = None

    # ---------- 設定持久化 ----------
    def save_settings(self, settings: QSettings) -> None:
        settings.setValue("subtitle/folder", self.folder_edit.text())
        settings.setValue(
            "subtitle/output_mode",
            "outdir" if self.outdir_radio.isChecked() else "inplace")
        settings.setValue("subtitle/outdir", self.outdir_edit.text())
        settings.setValue("subtitle/splitter", self.splitter.saveState())
        settings.setValue("subtitle/styles", self.style_picker.selected())

    def restore_settings(self, settings: QSettings) -> None:
        self.folder_edit.setText(settings.value("subtitle/folder", ""))
        self.outdir_edit.setText(settings.value("subtitle/outdir", ""))
        if settings.value("subtitle/output_mode", "inplace") == "outdir":
            self.outdir_radio.setChecked(True)
        else:
            self.inplace_radio.setChecked(True)
        state = settings.value("subtitle/splitter")
        # 直接判斷型別而不是靠 QSettings 的 type= 參數:PySide6 在轉換失敗時
        # 並不會如預期回傳 None/預設值,而是把原始(型別不對的)值原樣回傳,
        # 傳進 restoreState() 一樣會炸——手改/遷移壞掉的設定值必須擋在這裡。
        if isinstance(state, QByteArray):
            self.splitter.restoreState(state)
        saved_styles = settings.value("subtitle/styles", [])
        if isinstance(saved_styles, str):     # QSettings 單元素清單會退化成字串
            saved_styles = [saved_styles]
        self.style_picker.set_selected(list(saved_styles or []))

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
