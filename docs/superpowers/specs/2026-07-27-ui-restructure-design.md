# UI 重整設計:MKV 分頁重新定位、非遞迴掃描、版面方案 C

日期:2026-07-27
狀態:已與使用者確認,待寫實作計畫

## 背景

使用者在 2026-07-27 給出三點回饋,並明確選擇「三件放在同一個設計循環」——因為第 1 點會決定第 3 點的版面長什麼樣。

1. 「MKV 在掃的時候,應該只要列出 MKV 就好,字幕的控制應由 modify old track 那邊來進行控制」
2. 選資料夾不要掃到子資料夾
3. 「整體有些過於擁擠,介面的質感也不如我之前給你看過的範例」(參考工具:MKV Muxing Batch GUI v2.4.2)

第 3 點需要動版面配置。上一輪主題樣式刻意只做 QSS(方案 B)、把版面密度劃在範圍外,「擁擠」正是那次留下的結果。

## 已確認的決策

| # | 決策 | 使用者選擇 |
|---|---|---|
| 1 | 字幕軌選擇的歸屬 | MKV 分頁專屬的輕量選軌對話框(不合併封裝分頁的管線) |
| 2 | 跨檔對應規則的鍵 | **語言 + 軌名**(沿用既有 `mkv_batch.track_key`) |
| 3 | 對話框範圍與預設 | 只管「哪幾條舊字幕軌要套樣式」;**預設全勾**;按鈕名為「修改既有軌道…」 |
| 4 | 資料夾掃描深度 | 固定只掃當層,**不加**「包含子資料夾」勾選框 |
| 5 | 版面方案 | **C:右側設定側欄**(可拖曳分隔器) |

---

## 第 1 部分:MKV 分頁重新定位

### 現況

`MkvTab._on_scan` 啟動 `MkvScanWorker(folder, mkvmerge)`,對資料夾內每個 `*.mkv` 跑一次 `mkvmerge -J`(`list_ass_tracks`),回傳 `dict[Path, list[SubtitleTrack]]`,填成「檔案 → 該檔 ASS 字幕軌」的兩層勾選樹。使用者逐檔勾選要重新套樣式的軌,另有「一鍵選整季同類型軌」按鈕把某檔的勾選狀態依 `(語言, 軌名)` 同步到其他檔。

問題:掃描要對每個檔跑一次子行程(慢);主畫面一開始就攤開所有軌(吵);兩層樹佔掉大量垂直空間。

### 新設計

#### 主畫面

單層清單,不是樹:

| 欄 | 內容 |
|---|---|
| ☑ | 是否納入這次批次(掃描後**預設全部勾選**) |
| 檔名 | `EP01.mkv` |
| 將套用的軌 | 掃過軌之後才有值:`✓ 軌 3` / `✗ 無符合的軌` / `⚠ 軌 2、軌 3`;尚未掃軌時整欄留白 |

「將套用的軌」欄在兩個時機填值:關掉「修改既有軌道…」對話框時,以及「開始處理」前自動掃軌完成時。按「重新掃描」或換資料夾就清空。

掃描資料夾**不再跑任何外部程序**——只 `glob("*.mkv")`,同步完成。因此:

- 資料夾掃描不再需要 worker、執行緒與 `ScanProgressDialog`
- `_on_scan` 變成同步方法;`_auto_scan` 的「掃描進行中就跳過」判斷只剩批次執行那一路

#### 「修改既有軌道…」對話框

新檔 `ass_style_tool/qt/select_tracks_dialog.py`,結構刻意與封裝分頁的 `ModifyTracksDialog` 對稱(同一種心智模型:範本檔定規則 + 逐檔驗證面板)。

**上半:範本表格**

| 保留 | 軌 ID | 語言 | 軌名 |
|---|---|---|---|
| ☑ | 3 | chi | 繁體中文 |
| ☑ | 4 | jpn | 日文 |

- 範本 = 排序後**第一個有 ASS 字幕軌**的檔案(沿用 `ModifyTracksDialog` 跳過讀不到軌道的壞檔的做法,否則排最前面的壞檔會讓對話框空白)
- 所有列**預設勾選**(維持現況「掃完全部勾起來」的行為)

**下半:逐檔資訊面板**

顯示目前選取那一列的規則 `(語言, 軌名)` 在**每一部**已勾選影片的解析結果:

| 影片 | 解析結果 |
|---|---|
| EP01.mkv | ✓ 軌 3 |
| EP02.mkv | ✓ 軌 4 |
| EP03.mkv | ✗ 沒有符合的軌 |
| EP04.mkv | ⚠ 有 2 條符合(軌 2、軌 3),兩條都會套用 |

面板底下一行總結,處理「範本檔沒有的軌會被靜默略過」這個既有風險:

> ⚠ 3 部影片另有範本檔沒有的 ASS 字幕軌,不會被套用

(純顯示,不提供換範本;這輪不做。)

**回傳值**:`set[tuple[str, str]]` —— 被勾選的 `(語言, 軌名)` 鍵集合。

#### 純邏輯層(Qt-free,可單獨測)

新檔 `ass_style_tool/track_select.py`:

```python
def resolve_tracks(
    keys: Set[Tuple[str, str]],
    files_tracks: Dict[Path, List[SubtitleTrack]],
) -> Dict[Path, List[SubtitleTrack]]:
    """把鍵集合解析成逐檔要套用的軌清單(無符合者不出現在結果中)。"""


@dataclass
class SelectInfoRow:
    video_name: str
    track_ids: List[int]      # 空 = 找不到;>1 = 多條符合


def build_select_info_rows(
    key: Tuple[str, str],
    files_tracks: Dict[Path, List[SubtitleTrack]],
) -> List[SelectInfoRow]:
    """給資訊面板用;對應既有 track_info.build_track_info_rows 的角色。"""


def uncovered_track_count(
    keys: Set[Tuple[str, str]],
    files_tracks: Dict[Path, List[SubtitleTrack]],
) -> Tuple[int, int]:
    """回傳 (含未涵蓋軌的影片數, 未涵蓋軌總數),供總結那一行使用。"""
```

`mkv_batch.track_key` 保留(它正好就是新規則的鍵函式),由 `track_select` import。

#### 掃軌時機

`mkvmerge -J` 只在兩個時機跑,兩者都用既有的 `ScanProgressDialog`(可取消):

1. 按下「修改既有軌道…」——對**已勾選**的檔案掃(一個都沒勾時不掃,log 提示「沒有勾選任何 MKV」)
2. 按下「開始處理」而使用者從未開過對話框——掃完直接接著跑批次

掃描被使用者取消時,兩條路都不繼續:第 1 條不開對話框,第 2 條不啟動批次,已勾選的檔案清單與上次的規則都保持原狀。

`MkvScanWorker` 從吃「資料夾」改成吃 `list[Path]`(與 `TrackScanWorker` 同形狀),`rglob` 隨之消失。

取消掃描的接線一律沿用本專案的既定寫法:**tab 端 slot 直接呼叫 `worker.cancel()`**,絕不用 signal → worker slot 的連線(worker 已 `moveToThread`,該執行緒在 `run()` 期間不跑事件迴圈,排隊的呼叫等於無效——這個 bug 在掃描進度對話框那輪發生過)。

#### 狀態管理

`MkvTab` 新增/調整的狀態:

- `_track_keys: Optional[Set[Tuple[str, str]]]` —— `None` 表「從未設定」
- `_files_tracks: Dict[Path, List[SubtitleTrack]]` —— 最近一次掃軌結果(保留既有欄位名)

規則:

- 從未設定(`None`)→ 視為「所有 ASS 字幕軌都套」
- 換資料夾 / 按重新掃描 → `_track_keys = None`、`_files_tracks = {}`、按鈕文字回到「修改既有軌道…」(比照 `mux_tab` 換資料夾清 `_track_edits` 的做法)
- 有設定時按鈕顯示「修改既有軌道…(已選 2 條)」
- 全部取消勾選 → 空集合;按「開始處理」沿用既有訊息「沒有勾選任何字幕軌」

#### 送進預覽

現況需要在樹上選一條軌。改成:選一列**檔案** → 抽出該檔依目前規則解析出的**第一條**符合的軌;`_track_keys is None` 時用該檔第一條 ASS 軌。該檔尚未掃過軌時提示先按「修改既有軌道…」。

#### 移除

- `QTreeWidget` 與 `_ROLE_TRACK` 整套
- 「一鍵選整季同類型軌」按鈕、`MkvTab.apply_same_type_from_current`、`MkvTab.current_track`
- `mkv_batch.select_same_type`(功能被規則模型完全吸收,無其他呼叫端)

#### 不動的部分

`process_mkv` 單檔管線(抽取 → 轉換 → 重封裝 →(驗證取代))**完全不變**,仍吃 `List[SubtitleTrack]`。這是刻意的:它是已驗證的核心路徑,這輪不碰。

---

## 第 2 部分:資料夾掃描不遞迴

兩處遞迴都改掉:

| 位置 | 改動 |
|---|---|
| `ass_style_tool/episode_match.py` 的 `find_files` | `Path(folder).rglob("*")` → `Path(folder).glob("*")` |
| `ass_style_tool/qt/batch_worker.py` 的 `MkvScanWorker.run` | `rglob("*.mkv")` 隨第 1 部分改寫消失;MKV 分頁改用 `glob("*.mkv")` |

`find_files` 的連帶影響(全部是預期內的):

- 字幕檔分頁(`batch_runner.scan_folder`)
- 封裝分頁的 `MuxScanWorker`(影片與字幕資料夾各呼叫一次)
- `mux_tab._on_scan_done` 取字幕下拉清單

**不加**「包含子資料夾」勾選框(使用者決定:畫面已經太擠)。

三處輸出檔名衝突保護(`BatchWorker` / `ScaleWorker` / `MkvWorker` / `MuxWorker` 的 `seen_basenames`)**保留**。同層不可能出現同名檔,但這段程式碼成本為零,拿掉只是無謂的風險。

順帶效果:打包前審查列為 Minor 的「不同子資料夾同名影片在 `track_info` 面板無法區分」(該面板用檔名當 key)自動消失。

---

## 第 3 部分:版面方案 C —— 右側設定側欄

### 動機

現況三個工作分頁都是一長串裸露的橫列由上而下堆疊,沒有分組、沒有留白、沒有視覺層級。封裝分頁最嚴重:9 條橫列把表格擠成只剩兩三列高。參考工具把設定放在獨立面板,清單因此能佔滿畫面——這是「質感」差距的主要來源。

### 共同骨架

新檔 `ass_style_tool/qt/layout_helpers.py` 提供共用建構器與間距常數,避免三個分頁各寫一份:

```python
MARGIN = 12          # 分頁外距
SPACING = 10         # 主要區塊之間
GROUP_SPACING = 8    # 群組盒內部

def group(title: str, inner: QLayout) -> QGroupBox: ...
def settings_sidebar(*groups: QGroupBox) -> QWidget:
    """垂直排列群組盒、頂部對齊、底部 addStretch(1)、setMinimumWidth(240)。"""
```

三個分頁一致採用:

```
QVBoxLayout(contentsMargins=12, spacing=10)
├─ 來源列(資料夾 QLineEdit + 瀏覽…)          ← 橫跨全寬
├─ QSplitter(Qt.Horizontal)   ← addWidget(..., 1)
│   ├─ 主清單 / 配對表格        (stretch 3)
│   └─ 設定側欄                 (stretch 1,最小寬 240)
├─ 動作列(次要動作靠左 → addStretch(1) → 主要動作 + 取消靠右)
└─ 進度列
```

### 各分頁側欄內容

| 分頁 | 側欄群組盒(由上而下) |
|---|---|
| 字幕檔 | 操作模式(套用樣式 / 縮放字級 + ScalePanel)、輸出 |
| MKV | 操作模式(+ ScalePanel)、字幕軌(「修改既有軌道…」按鈕 + 目前狀態文字)、輸出 |
| 封裝 | 封裝前處理(+ ScalePanel)、新字幕軌(語言 / 軌名 / 預設 / 強制)、既有軌道(「修改既有軌道…」按鈕)、輸出 |

### 動作列規則(三分頁一致)

- 靠左(次要):重新掃描、開啟輸出資料夾、試算預覽(不寫檔)
- 靠右(主要):開始 X(`accent=true`)、取消

### 必要的附帶修改

`ScalePanel` 目前是 4 欄 `QGridLayout`(倍率、基準 Style、三個核取方塊橫排),塞不進 240px 側欄 → 改成單欄垂直版面。`get_options()` 的介面與行為不變。

### 持久化

分隔器位置存進 QSettings,key 為 `subtitle/splitter`、`mkv/splitter`、`mux/splitter`,比照既有的 `save_settings` / `restore_settings` 做法。

### 範圍界線

- 「樣式與預覽」分頁維持現狀(它本來就是 `QSplitter(style_editor | preview_panel)`,已符合方案 C 的精神)
- `main_window` 的分頁籤、主題按鈕、底部 log 區不動
- `theme.py` 只微調 `QGroupBox` 的 `margin-top` / `padding` 讓群組標題有呼吸空間,**不動任何配色值**

---

## 測試策略

### 受影響的既有測試(已實際清點)

| 檔案 | 現有測試數 | 影響 |
|---|---|---|
| `tests/test_mkv_tab.py` | 23 | 約 6 個要重寫:`test_populate_builds_tree_all_checked`、`test_checked_jobs_respects_unchecking`、`test_apply_same_type_from_current`、`test_current_track`、`test_tree_has_alternating_rows`、`test_run_button_enabled_after_populate` |
| `tests/test_mkv_batch.py` | 15 | `select_same_type` 相關測試移轉成 `track_select.resolve_tracks` 的測試 |
| `tests/test_episode_match.py` | 17 | `find_files` 的遞迴測試改成驗證**不**遞迴 |
| `tests/test_mkv_worker.py` | 9 | `MkvScanWorker` 改吃 `list[Path]` 後跟著調 |
| `tests/test_mux_tab.py` | 29 | 版面改動;控件屬性名不變,多數不受影響 |

其餘分頁測試抓的是 `tab.folder_edit`、`tab.run_button` 這類屬性名,方案 C 不改屬性名,不受影響。

### 新增測試

- `tests/test_track_select.py` —— `resolve_tracks` / `build_select_info_rows` / `uncovered_track_count` 的純邏輯測試(找不到、剛好一條、多條符合、範本沒有的軌)
- `tests/test_select_tracks_dialog.py` —— 對話框的預設全勾、取消勾選後 `get_keys()` 的結果、資訊面板隨選取列更新、範本檔跳過讀不到軌的壞檔
- `tests/test_layout_helpers.py` —— 側欄最小寬度、群組盒建構
- 三個分頁各補一個分隔器位置 save/restore roundtrip 測試

### 這個專案的驗證要求(血淚教訓,必須遵守)

1. **視覺/版面需求要用實際 render 量測驗證**,不能只看程式碼「有沒有那一行」。上一輪主題樣式 2 個 per-task 審查零 findings,最終審查實際 render 成點陣圖才抓到 6 個 Important(深色交錯列 2/255 色差、表格只高亮單格)。
2. **宣稱在守某個約束的測試,要用 mutation 驗證它真的會失敗**。掃描進度對話框那輪補的跨執行緒測試是套套邏輯,對修好前的程式碼也會通過。
3. **`setStyleSheet` 一律要帶型別選擇器**。裸的宣告會往下傳給子孫控件——上一輪替表格 cell widget 加 `background: transparent` 沒帶選擇器,害深色下拉文字對比從 13.36:1 崩到 1.25:1。
4. **worker 的 `cancel()` 一律從 GUI 執行緒的 slot 直接呼叫**,絕不用 signal → worker slot 的連線。

---

## 明確不做(YAGNI)

- 不把 MKV 分頁併進封裝分頁
- 不讓 MKV 分頁取得保留 / 丟棄 / 預設 / 強制 / 語言 / 軌名的編輯能力(那要改寫 `process_mkv` 走 `build_mux_command`,動到已驗證的核心管線)
- 不加「包含子資料夾」勾選框
- 不提供在選軌對話框裡更換範本檔
- 不動 `theme.py` 的任何配色值
- 不動「樣式與預覽」分頁的版面

## 風險

| 風險 | 緩解 |
|---|---|
| 方案 C 在預設 1000px 寬視窗下,表格只剩約 680px | 分隔器可拖曳,位置存進 QSettings;封裝分頁 5 欄在 680px 下仍可讀 |
| 版面重寫可能悄悄改變控件的啟用/停用時序 | 保留所有現有控件屬性名,既有測試多數直接沿用;新增的分隔器測試不覆蓋既有斷言 |
| `(語言, 軌名)` 鍵在兩條軌都是 `und` 且無軌名時會同時命中 | 資訊面板明確顯示「⚠ 有 2 條符合,兩條都會套用」,不靜默 |
| 範本檔沒有的軌會被靜默略過 | 對話框底部總結那一行明講「N 部影片另有範本檔沒有的 ASS 字幕軌,不會被套用」 |
