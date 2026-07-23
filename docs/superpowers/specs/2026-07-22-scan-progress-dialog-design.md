# MKV 掃描進度對話框 Design

**背景**:「MKV」分頁按下掃描後,`MkvScanWorker`(`qt/batch_worker.py:137-154`)會走訪資料夾內每一個 `*.mkv`,對**每一個檔案**跑一次 `mkvmerge -J`(`list_ass_tracks`)。一整季 24-28 個檔案就是 24-28 次子行程呼叫。

問題有兩個:

1. **完全沒有進度回饋**。`MkvScanWorker` 只在全部跑完後發一次 `finished`,中間不發任何訊號。`MkvTab._on_scan`(`qt/mkv_tab.py:186-202`)只把掃描按鈕變灰就沒事了——分頁下方那兩條進度條是給**批次執行**用的,掃描階段不會動。使用者看到的就是一個像當掉的畫面。
2. **無法中斷**。`MkvScanWorker` 沒有取消機制(不像 `MkvWorker`/`MuxWorker` 都有 `cancel()`)。選錯資料夾或檔案太多時只能乾等。

其他兩個分頁的掃描(字幕檔、封裝)只做檔案系統走訪與集數配對,沒有逐檔子行程,速度快,**不在本次範圍**。

## 需求(使用者確認)

1. 掃描時**彈出一個小視窗**顯示進度(對標參考工具「MKV Muxing Batch GUI」的 Loading Media Info 視窗),而非只在分頁內顯示。
2. **可以取消**。取消後視同「沒有掃描過」——不採用半成品的不完整結果。
3. 只做 **MKV 分頁的掃描**。
4. 之前從 Modify Old Tracks 延後過來的「掃全批偵測軌道結構不一致並提醒」**這次不做**(現有的 per-video 過濾安全網已保證結果正確,不做也不會出錯)。

## 核心設計

### 1. `MkvScanWorker` 加進度與取消(`qt/batch_worker.py`)

目前的 `run()` 是「邊走訪邊掃描、跑完才發 `finished`」。改成:

- **先收集檔案清單**(把 `sorted(folder.rglob("*.mkv"))` 過濾出 `is_file()` 的結果一次收成 list),取得總數。
- 逐檔掃描,**每掃完一檔發一次** `progress(done, total)`。
- 新增 `cancel()` 方法設旗標,以及 `cancelled` 訊號。**每個檔案開始前**檢查旗標;已取消就發 `cancelled` 並直接返回,**丟棄已累積的部分結果**(不發 `finished`)。

新的訊號介面:

```python
class MkvScanWorker(QObject):
    finished = Signal(object)      # dict[Path, list[SubtitleTrack]](既有)
    progress = Signal(int, int)    # 已完成, 總數(新)
    cancelled = Signal()           # 使用者取消(新)

    def cancel(self) -> None: ...  # 設旗標(新)
```

**為什麼用獨立的 `cancelled` 訊號而不是發 `finished({})`**:兩者語意不同——「掃完了但資料夾裡沒有 MKV」與「使用者中途取消」必須能分辨,否則取消會被誤當成「掃描成功但沒東西」而清空既有結果。

**取消粒度(刻意的取捨)**:檢查點在檔案與檔案之間,所以按下取消時,**正在執行中的那一次 `mkvmerge` 會先跑完**才停止,不強制中止子行程。單檔通常零點幾秒,實務上感受不到;強殺子行程需要額外機制,不在本次範圍。

### 2. 新元件 `ScanProgressDialog`(新檔 `qt/scan_progress_dialog.py`)

一個小的 modal `QDialog`:

- 進度條 + 文字標籤(例:`掃描影片 9/24`)。
- 「取消」按鈕;**按視窗 X 或 Esc 也等同取消**(覆寫 `reject()`,統一走同一條取消路徑,避免「關了視窗但掃描還在背景跑」)。
- `setModal(True)`,掃描期間擋住分頁,避免誤點其他控制項。
- 對外介面:
  - `set_progress(done: int, total: int) -> None`
  - `cancelled = Signal()`(使用者按取消/關閉時發出)

**不確定→確定的兩段式進度**:一開始還在列舉資料夾內容時,總數尚未可知,此時進度條顯示不確定狀態(`setRange(0, 0)`)與「正在尋找檔案…」;**收到第一筆 `progress` 後**才把範圍設成實際總數、切換成真正的進度條與 `9/24` 文字。

（參考工具只有一個轉圈動畫;因為我們**知道總數**,改用真正的進度條資訊量更高。不在總數已知前假裝知道進度,是這個兩段式設計的用意。）

### 3. `MkvTab` 接線(`qt/mkv_tab.py`)

- `_on_scan` 建立 `ScanProgressDialog`,以 `show()` 顯示(非 `exec()`——現有掃描是非同步的 QThread 流程,用 `exec()` 的巢狀事件迴圈會打亂既有結構)。
- 接線:
  - `worker.progress` → `dialog.set_progress`
  - `dialog.cancelled` → `worker.cancel`
  - `worker.finished` → 既有 `_on_scan_done`
  - `worker.cancelled` → 新的 `_on_scan_cancelled`
- **共用收尾**:抽出一個 `_finish_scan()` 私有方法,負責「關閉並釋放對話框 + `quit()`/`wait()` 執行緒 + 把 `_scan_thread`/`_scan_worker` 設回 None + 恢復掃描按鈕」。`_on_scan_done` 與 `_on_scan_cancelled` 都先呼叫它,再各自做後續。兩條結束路徑共用同一段收尾,避免其中一條漏關對話框或漏收執行緒。
- `_on_scan_done`:呼叫 `_finish_scan()` → `populate(files_tracks)` → log 掃描完成訊息(維持現有行為)。
- `_on_scan_cancelled`:呼叫 `_finish_scan()` → **不呼叫 `populate`**(保留上一次的結果與表格內容)→ log「掃描已取消」。

**取消後的按鈕狀態**:`_on_scan` 會同時把 `scan_button` 與 `run_button` 變灰。`_on_scan_done` 靠 `populate` 內的既有邏輯恢復 `run_button`(`qt/mkv_tab.py:236-238`:`if self._thread is None: run_button.setEnabled(any(files_tracks.values()) and self.tools_available)`)。取消路徑不跑 `populate`,因此必須自行用**同一條件、對既有的 `self._files_tracks`** 恢復:

```python
if self._thread is None:
    self.run_button.setEnabled(
        any(self._files_tracks.values()) and self.tools_available)
```

否則取消一次重新掃描後,畫面上還留著上一次的結果,執行按鈕卻永遠是灰的(要再掃一次才能恢復)。

## 邊界情況

- **資料夾內沒有任何 MKV**:總數 0,迴圈不執行,直接發 `finished({})`。對話框可能連一筆 `progress` 都沒收到就關閉(停在不確定狀態),屬正常;既有的「掃描完成:0 個 MKV」訊息照舊。
- **掃描期間再次觸發掃描**:現有 `_on_scan` 已有 `self._thread`(批次執行中)的防護;掃描對話框為 modal,期間使用者點不到掃描按鈕,不需額外防護。
- **取消後立刻再掃描**:`_finish_scan()` 已 `wait()` 等執行緒真正結束並清空參照,可安全重新開始。
- **單檔掃描失敗**:`list_ass_tracks` 本身任何失敗都回 `[]`(既有行為),不中斷整輪掃描,進度照常前進。

## 範圍外

- 封裝分頁「修改既有軌道…」的**單檔**掃描(目前用等待游標同步執行):只有一個檔案,不套用本對話框。
- **全批軌道結構一致性檢查與提醒**:使用者明確選擇本次不做。
- 字幕檔 / 封裝分頁的掃描:純檔案系統走訪,速度快,不加進度對話框。
- **強制中止執行中的子行程**:取消的粒度為檔案之間(見上)。
- 對話框顯示**目前檔名**:參考工具亦僅顯示計數;本次只做計數,保持版面單純。

## 測試計畫(概要,交給 plan 細化)

- `MkvScanWorker`(注入假的 `list_fn`,完全不碰 mkvmerge):
  - 逐檔發出的 `progress` 序列正確(`(1,N) … (N,N)`),`finished` 帶完整結果。
  - `cancel()` 後:發 `cancelled` 而**非** `finished`;且**不再對剩餘檔案呼叫 `list_fn`**(以呼叫次數斷言,證明真的提早停止,而非跑完才丟棄)。
  - 資料夾內無 MKV → 直接 `finished({})`、無 `progress`。
- `ScanProgressDialog`:
  - 初始為不確定狀態;收到第一筆 `set_progress` 後切成確定範圍且文字顯示 `9/24` 形式。
  - 按取消 → 發 `cancelled`;`reject()`(X/Esc)→ 同樣發 `cancelled`。
- `MkvTab`:
  - `_on_scan_done` 會關閉對話框並填入表格。
  - `_on_scan_cancelled` 會關閉對話框、**不**動表格內容,且依既有 `_files_tracks` 正確恢復 `run_button`。
- 既有全套測試維持通過(目前 349)。
