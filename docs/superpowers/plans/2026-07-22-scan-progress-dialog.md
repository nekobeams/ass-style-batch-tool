# MKV 掃描進度對話框 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓「MKV」分頁掃描時彈出可取消的進度小視窗,取代目前掃描期間畫面像當掉、且無法中斷的狀況。

**Architecture:** 三塊。`MkvScanWorker` 先收集檔案清單取得總數、逐檔發 `progress`,並加上 `cancel()` 與獨立的 `cancelled` 訊號(取消時丟棄部分結果);新增純顯示的 modal `ScanProgressDialog`(不確定→確定兩段式進度、X/Esc 等同取消);`MkvTab` 把兩者接起來,並用共用收尾函式處理「完成」與「取消」兩條結束路徑。

**Tech Stack:** Python、PySide6(QThread/Signal/QDialog)、pytest(offscreen,`qapp` fixture)。

## Global Constraints

- 一律用 `py`,不要用 `python`。測試從 repo root:`py -m pytest tests -q`。目前基線 **349 passed**,實作後維持全綠(新增測試使總數上升)。
- **取消必須用獨立的 `cancelled` 訊號,不可用 `finished({})` 代替**:「掃完但資料夾沒有 MKV」與「使用者取消」語意不同,混用會讓取消被誤判成掃描成功而清空既有結果。
- **取消時丟棄已累積的部分結果**,不得回傳不完整的清單。
- **取消粒度為檔案與檔案之間**:檢查點在每個檔案開始前,正在執行中的那一次 `list_fn` 會先跑完;不強制中止子行程(刻意取捨)。
- 對話框:`setModal(True)`;總數未知時進度條為不確定狀態(`setRange(0, 0)`),**收到第一筆 progress 後**才切成確定範圍;取消鈕 / 視窗 X / Esc 一律走同一條取消路徑。
- 「完成」與「取消」兩條結束路徑**共用同一個收尾函式**(關對話框 + 收執行緒 + 恢復掃描鈕),避免其中一條漏做。
- **取消路徑不可呼叫 `populate`**(保留上一次結果),但必須用與 `populate` 相同的條件、對既有的 `self._files_tracks` 恢復 `run_button`,否則取消後表格還在、執行鈕卻永遠是灰的。
- 只動 MKV 分頁的掃描;字幕檔/封裝分頁與封裝分頁的單檔掃描皆不動。
- commit 訊息結尾加:`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- 環境:Bash 每次 `cd /c/Claude_code`。

---

## File Structure

- `ass_style_tool/qt/batch_worker.py`(修改):`MkvScanWorker` 加 `progress`/`cancelled` 訊號與 `cancel()`。
- `ass_style_tool/qt/scan_progress_dialog.py`(新增):`ScanProgressDialog`。
- `ass_style_tool/qt/mkv_tab.py`(修改):建立/顯示對話框、接線、共用收尾、取消路徑。
- 測試:`tests/test_mkv_worker.py`(加)、`tests/test_scan_progress_dialog.py`(新)、`tests/test_mkv_tab.py`(加)。

---

### Task 1: `MkvScanWorker` 加進度與取消

**Files:**
- Modify: `ass_style_tool/qt/batch_worker.py:137-154`
- Test: `tests/test_mkv_worker.py`

**Interfaces:**
- Produces:
  - `MkvScanWorker.progress = Signal(int, int)`(已完成, 總數)
  - `MkvScanWorker.cancelled = Signal()`
  - `MkvScanWorker.cancel() -> None`
  - 既有 `finished = Signal(object)` 與 `__init__(folder, mkvmerge, list_fn=list_ass_tracks)` 不變。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_mkv_worker.py` 末端加入(檔案已有 `qapp` fixture 用法與 `_track` helper):

```python
def test_scan_worker_emits_progress_per_file(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvScanWorker
    for name in ("e1.mkv", "e2.mkv", "e3.mkv"):
        (tmp_path / name).write_bytes(b"")
    worker = MkvScanWorker(tmp_path, Path("mkvmerge.exe"),
                           list_fn=lambda p, m: [])
    seen = []
    worker.progress.connect(lambda done, total: seen.append((done, total)))
    worker.run()
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_scan_worker_cancel_stops_early_and_emits_cancelled(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvScanWorker
    for name in ("e1.mkv", "e2.mkv", "e3.mkv"):
        (tmp_path / name).write_bytes(b"")
    calls = []

    def fake_list(path, mkvmerge):
        calls.append(path)
        worker.cancel()          # 第一個檔掃完就要求取消
        return []

    worker = MkvScanWorker(tmp_path, Path("mkvmerge.exe"), list_fn=fake_list)
    events = []
    worker.finished.connect(lambda d: events.append("finished"))
    worker.cancelled.connect(lambda: events.append("cancelled"))
    worker.run()
    assert events == ["cancelled"]   # 取消不可發 finished
    assert len(calls) == 1           # 真的提早停,不是跑完才丟棄


def test_scan_worker_no_mkv_finishes_empty(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvScanWorker
    (tmp_path / "note.txt").write_text("x")
    worker = MkvScanWorker(tmp_path, Path("mkvmerge.exe"),
                           list_fn=lambda p, m: [])
    got = {"finished": None, "progress": []}
    worker.finished.connect(lambda d: got.__setitem__("finished", d))
    worker.progress.connect(lambda a, b: got["progress"].append((a, b)))
    worker.run()
    assert got["finished"] == {}
    assert got["progress"] == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_mkv_worker.py -k "progress_per_file or cancel_stops_early or no_mkv_finishes" -q`
Expected: FAIL(`'MkvScanWorker' object has no attribute 'progress'`)

- [ ] **Step 3: 實作**

把 `ass_style_tool/qt/batch_worker.py` 的 `MkvScanWorker` 整個類別換成:

```python
class MkvScanWorker(QObject):
    """遞迴掃描資料夾內 *.mkv 並列舉各檔 ASS 字幕軌;支援進度回報與取消。"""

    finished = Signal(object)      # dict[Path, list[SubtitleTrack]]
    progress = Signal(int, int)    # 已完成, 總數
    cancelled = Signal()           # 使用者取消(部分結果丟棄)

    def __init__(self, folder: Path, mkvmerge: Path,
                 list_fn=list_ass_tracks) -> None:
        super().__init__()
        self._folder = Path(folder)
        self._mkvmerge = mkvmerge
        self._list_fn = list_fn
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        # 先收集清單以取得總數(供進度條顯示確定範圍)
        files = [p for p in sorted(self._folder.rglob("*.mkv")) if p.is_file()]
        total = len(files)
        result = {}
        for i, path in enumerate(files, start=1):
            # 檢查點在每個檔案之前;執行中的那一次 list_fn 會先跑完
            if self._cancelled:
                self.cancelled.emit()   # 丟棄 result,不發 finished
                return
            result[path] = self._list_fn(path, self._mkvmerge)
            self.progress.emit(i, total)
        self.finished.emit(result)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `py -m pytest tests/test_mkv_worker.py -q`
Expected: PASS(既有 + 3 個新測試)

- [ ] **Step 5: Commit**

```bash
git add ass_style_tool/qt/batch_worker.py tests/test_mkv_worker.py
git commit -m "Add progress and cancel to MkvScanWorker

Collects the file list first to get a total, emits progress(done, total)
per scanned file, and gains cancel() plus a distinct cancelled signal so
"user cancelled" is never mistaken for "scanned and found nothing".
Cancelling discards the partial result.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `ScanProgressDialog`

**Files:**
- Create: `ass_style_tool/qt/scan_progress_dialog.py`
- Test: `tests/test_scan_progress_dialog.py`

**Interfaces:**
- Produces:
  - `ScanProgressDialog(parent=None)`,屬性 `label`(QLabel)、`bar`(QProgressBar)
  - `set_progress(done: int, total: int) -> None`
  - `cancelled = Signal()`
  - 覆寫 `reject()`:取消鈕 / X / Esc 一律先發 `cancelled` 再關閉。

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_scan_progress_dialog.py`:

```python
from __future__ import annotations


def test_dialog_starts_indeterminate(qapp):
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    d = ScanProgressDialog()
    # 總數未知 → 不確定狀態(min==max==0)
    assert d.bar.minimum() == 0
    assert d.bar.maximum() == 0
    assert "尋找" in d.label.text()


def test_dialog_switches_to_determinate_on_first_progress(qapp):
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    d = ScanProgressDialog()
    d.set_progress(9, 24)
    assert d.bar.maximum() == 24
    assert d.bar.value() == 9
    assert d.label.text() == "掃描影片 9/24"


def test_dialog_reject_emits_cancelled(qapp):
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    d = ScanProgressDialog()
    seen = []
    d.cancelled.connect(lambda: seen.append(True))
    d.reject()                 # 等同按取消 / X / Esc
    assert seen == [True]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_scan_progress_dialog.py -q`
Expected: FAIL(`No module named 'ass_style_tool.qt.scan_progress_dialog'`)

- [ ] **Step 3: 實作 `scan_progress_dialog.py`**

```python
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
```

- [ ] **Step 4: 跑測試確認通過**

Run: `py -m pytest tests/test_scan_progress_dialog.py -q`
Expected: PASS(3 個測試)

- [ ] **Step 5: Commit**

```bash
git add ass_style_tool/qt/scan_progress_dialog.py tests/test_scan_progress_dialog.py
git commit -m "Add ScanProgressDialog for the MKV folder scan

Modal dialog with a per-file count label and progress bar. Starts
indeterminate while the file list is still being collected, switching to a
real range on the first progress update. Cancel button, window X and Esc
all route through reject() so they emit one cancelled signal.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `MkvTab` 接線與取消路徑

**Files:**
- Modify: `ass_style_tool/qt/mkv_tab.py:186-214`
- Test: `tests/test_mkv_tab.py`

**Interfaces:**
- Consumes: `MkvScanWorker.progress`/`cancelled`/`cancel()`(Task 1);`ScanProgressDialog(parent)`、`set_progress`、`cancelled`(Task 2)。
- Produces: `MkvTab._scan_dialog`、`MkvTab._finish_scan()`、`MkvTab._on_scan_cancelled()`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_mkv_tab.py` 末端加入(檔案已有 `_tab(monkeypatch)` helper 與 `FILES` 常數):

```python
def test_scan_done_closes_dialog_and_populates(qapp, monkeypatch):
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    tab = _tab(monkeypatch)
    tab._scan_dialog = ScanProgressDialog(tab)
    tab._on_scan_done(FILES)
    assert tab._scan_dialog is None                    # 對話框已關閉並釋放
    assert tab.tree.topLevelItemCount() == len(FILES)  # 結果有填進表格


def test_scan_cancelled_keeps_previous_results(qapp, monkeypatch):
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    tab = _tab(monkeypatch)
    tab.populate(FILES)                          # 先有一次成功掃描的結果
    before = tab.tree.topLevelItemCount()
    tab.run_button.setEnabled(False)             # 模擬 _on_scan 把按鈕變灰
    tab._scan_dialog = ScanProgressDialog(tab)
    tab._on_scan_cancelled()
    assert tab._scan_dialog is None              # 對話框已關閉
    assert tab.tree.topLevelItemCount() == before  # 舊結果保留,未被清空
    assert tab.run_button.isEnabled() is True    # 依既有結果恢復,不會卡在灰色
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_mkv_tab.py -k "scan_done_closes_dialog or scan_cancelled_keeps" -q`
Expected: FAIL(`AttributeError: 'MkvTab' object has no attribute '_on_scan_cancelled'`)

- [ ] **Step 3: 加 import 與狀態**

在 `ass_style_tool/qt/mkv_tab.py` 的 import 區(既有 `from .batch_worker import MkvScanWorker, MkvWorker` 附近)加入:

```python
from .scan_progress_dialog import ScanProgressDialog
```

在 `__init__` 的狀態初始化區(既有 `self._scan_thread: Optional[QThread] = None` 附近)加入:

```python
        self._scan_dialog: Optional[ScanProgressDialog] = None
```

- [ ] **Step 4: 改 `_on_scan` 建立並顯示對話框**

把 `_on_scan` 中從 `self._scan_thread = QThread()` 到 `self._scan_thread.start()` 的區塊改為:

```python
        self._scan_thread = QThread()
        self._scan_worker = MkvScanWorker(Path(folder), self._tools.mkvmerge)
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_scan_done)
        self._scan_worker.cancelled.connect(self._on_scan_cancelled)
        self._scan_dialog = ScanProgressDialog(self)
        self._scan_worker.progress.connect(self._scan_dialog.set_progress)
        self._scan_dialog.cancelled.connect(self._scan_worker.cancel)
        self._scan_dialog.show()      # 非 exec():維持既有非同步流程
        self._scan_thread.start()
```

- [ ] **Step 5: 加共用收尾並改寫兩條結束路徑**

把既有的 `_on_scan_done` 整個方法換成下面三個方法(`_finish_scan` 為兩條路徑共用):

```python
    def _finish_scan(self) -> None:
        """完成/取消共用的收尾:關對話框、收執行緒、恢復掃描鈕。"""
        if self._scan_dialog is not None:
            self._scan_dialog.close()
            self._scan_dialog.deleteLater()
            self._scan_dialog = None
        if self._scan_thread is not None:
            self._scan_thread.quit()
            self._scan_thread.wait()
        self._scan_thread = None
        self._scan_worker = None
        self.scan_button.setEnabled(True)

    def _on_scan_done(self, files_tracks: dict) -> None:
        self._finish_scan()
        self.populate(files_tracks)
        total_tracks = sum(len(v) for v in files_tracks.values())
        self.log.emit(f"掃描完成:{len(files_tracks)} 個 MKV,"
                      f"共 {total_tracks} 條 ASS 字幕軌")

    def _on_scan_cancelled(self) -> None:
        self._finish_scan()
        # 不呼叫 populate:保留上一次的結果與表格內容。
        # 但仍要用與 populate 相同的條件恢復執行鈕,否則舊結果還在、
        # 執行鈕卻永遠是灰的。
        if self._thread is None:
            self.run_button.setEnabled(
                any(self._files_tracks.values()) and self.tools_available)
        self.log.emit("掃描已取消")
```

- [ ] **Step 6: 跑新測試 + 相關全套**

Run: `py -m pytest tests/test_mkv_tab.py tests/test_mkv_worker.py tests/test_scan_progress_dialog.py -q`
Expected: PASS(全綠)

- [ ] **Step 7: 全套回歸**

Run: `py -m pytest tests -q`
Expected: PASS(349 + 新增測試,全綠)

- [ ] **Step 8: Commit**

```bash
git add ass_style_tool/qt/mkv_tab.py tests/test_mkv_tab.py
git commit -m "Show a cancellable progress dialog during the MKV scan

_on_scan now opens ScanProgressDialog and wires worker progress into it,
with the dialog's cancel routed back to the worker. Completion and
cancellation share one teardown that closes the dialog and reaps the
thread; cancelling keeps the previous results and restores the run button
from them instead of leaving it stuck disabled.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- `MkvScanWorker` 逐檔 progress + cancel + 獨立 cancelled + 丟棄部分結果 → Task 1 ✓
- 取消粒度(檔案之間、執行中的 list_fn 先跑完)→ Task 1 Step 3 的檢查點位置與註解 ✓
- modal 對話框、不確定→確定兩段式、X/Esc 等同取消 → Task 2 ✓
- `MkvTab` 接線、`show()` 而非 `exec()` → Task 3 Step 4 ✓
- 共用收尾函式 → Task 3 Step 5 `_finish_scan` ✓
- 取消不 populate、用相同條件對既有 `_files_tracks` 恢復 run_button → Task 3 Step 5 + `test_scan_cancelled_keeps_previous_results` ✓
- 空資料夾直接 finished({}) 且無 progress → Task 1 `test_scan_worker_no_mkv_finishes_empty` ✓
- 只動 MKV 分頁 → 檔案清單僅含 batch_worker/mkv_tab/新對話框 ✓
- 測試計畫各項 → 各 Task 涵蓋 ✓

**2. Placeholder scan:** 無 TBD/TODO;每個 code step 均含完整程式碼與可執行指令。

**3. Type consistency:** `progress = Signal(int, int)`(Task 1)對應 `set_progress(done, total)`(Task 2)與 Task 3 的 `progress.connect(dialog.set_progress)` 一致;`cancelled = Signal()` 在 worker 與 dialog 皆為無參數,Task 3 分別接到 `_on_scan_cancelled` 與 `worker.cancel` 一致;`_scan_dialog`/`_finish_scan`/`_on_scan_cancelled` 命名在 Task 3 內與測試一致。

## 範圍外(本計畫不做)

- 封裝分頁「修改既有軌道…」的單檔掃描、全批軌道一致性檢查、字幕檔/封裝分頁掃描的進度、強制中止執行中的子行程、對話框顯示目前檔名。
