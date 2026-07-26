# 軌道資訊面板(Information About Tracks)Design

**背景**:封裝分頁的「修改既有軌道…」目前只掃**第一部**已配對影片,把它的軌道當作範本讓使用者設定(保留/丟棄、預設、forced、語言、軌名),再依**軌道 ID** 套用到整批。正確性靠 per-video 過濾(該檔沒有那個 ID 就跳過該條規則),但使用者**事前完全看不到**哪幾部影片其實沒有這條軌、或那條軌在別的檔案裡長得不一樣。

對標參考工具「MKV Muxing Batch GUI」Modify Old Tracks 對話框下半部的 Information About Tracks 面板。

## 實作前發現的既有缺陷(本次一併修掉)

檢視 `track_edit.build_source_track_flags`(`ass_style_tool/track_edit.py:40-64`)後確認:**規則純粹以軌道 ID 比對,不驗證該 ID 在別的檔案裡是否為同一種軌道。**

- 保留/丟棄:`kept = [i for i in ids if edits.get(i, TrackEdit()).keep]`,`ids` 是該檔**該類型**的 ID。若使用者把 A 片的字幕軌 2 設為丟棄,而 B 片的軌 2 是**音訊**,則處理 B 片的音訊群組時 `edits.get(2).keep` 為 False → **音訊軌被丟掉**。
- 屬性:`for t in tracks: e = edits.get(t.track_id)` → 語言 `chi` 會被設到 B 片的軌 2 上,不論它是什麼。

同一來源整季的軌道結構通常一致,所以實務上多半不會踩到;但一旦踩到,在「取代原影片」模式下是不可逆的。使用者確認本次一併修掉。

## 需求(使用者確認)

1. **開對話框時就掃描全部已配對影片**(每檔一次 `mkvmerge -J`),搭配可取消的進度小視窗;掃描期間可取消,取消則不開對話框。
2. 面板顯示參考工具那組欄位(**影片 / 找到 / 預設 / forced / 軌名 / 語言**),**外加類型比對警告**——這是唯一能看出上述缺陷有沒有踩到的方式。
3. **套用時真的不套錯**:同一個軌 ID 在某檔案的類型與範本不同時,該檔案不套用這條設定。
4. 面板**唯讀**(不做每檔個別覆寫)。

## 元件與職責

### 1. `TrackScanWorker`(`qt/batch_worker.py`,新增)

沿用 `MkvScanWorker` 已驗證的模式,差別在於掃的是**指定的影片清單**而非整個資料夾:

```python
class TrackScanWorker(QObject):
    finished = Signal(object)      # dict[Path, list[MediaTrack]]
    progress = Signal(int, int)    # 已完成, 總數
    cancelled = Signal()           # 使用者取消(部分結果丟棄)

    def __init__(self, video_paths, mkvmerge, list_fn=list_all_tracks) -> None: ...
    def cancel(self) -> None: ...
```

- 取消檢查點在**每個檔案之前**;執行中的那一次 `list_fn` 會先跑完(與 `MkvScanWorker` 相同的刻意取捨,不強制中止子行程)。
- 取消時發 `cancelled` 而**非** `finished({})`——兩者語意不同,混用會讓「取消」被誤判成「掃完但沒有任何軌道」。
- 掃描範圍:**所有 `status == "matched"` 的配對影片**(不是只有已勾選的)。使用者可能在開啟對話框後才調整勾選,掃全部比較可預期。

### 2. `build_track_info_rows`(`ass_style_tool/track_info.py`,新增純邏輯模組,無 Qt)

面板顯示的資料組裝抽成純函式,不碰 Qt 也不碰 mkvmerge,可完整單元測試:

```python
@dataclass
class TrackInfoRow:
    video_name: str
    found: bool
    type_matches: bool      # found 為 False 時無意義,一律 False
    track_type: str         # 該檔案這個 ID 實際的類型(找不到時為 "")
    default: Optional[bool] # 類型不符或找不到時為 None
    forced: Optional[bool]
    track_name: str
    language: str

def build_track_info_rows(
    track_id: int,
    template_type: str,
    tracks_by_file: Dict[Path, List[MediaTrack]],
) -> List[TrackInfoRow]:
    """依檔名排序回傳每部影片對這個軌 ID 的狀況。"""
```

三種情況:

| 情況 | `found` | `type_matches` | 其餘欄位 |
|---|---|---|---|
| 該檔沒有這個 ID | False | False | 空/None |
| 有,類型與範本相同 | True | True | 該檔實際的 default/forced/軌名/語言 |
| 有,類型不同 | True | False | `track_type` 填該檔實際類型;default/forced 為 None |

### 3. `TrackEdit.track_type` 與型別比對(`ass_style_tool/track_edit.py`,修改)

`TrackEdit` 新增欄位:

```python
track_type: Optional[str] = None   # 這條設定是為哪種軌道建立的
```

`build_source_track_flags` 的比對規則改為:**設定有記錄 `track_type` 且與該檔案該 ID 的實際類型不同時,視為這條設定不存在**。

- 保留/丟棄:類型不符 → 該 ID 視為預設 `TrackEdit()`(保留),不會被丟掉。
- 屬性:類型不符 → 不產生任何旗標。
- `track_type is None` → **維持現行行為**(不比對、照舊套用),既有呼叫端與既有測試不受影響。對話框一律會填入類型。

### 4. `ModifyTracksDialog`(`qt/modify_tracks_dialog.py`,修改)

- 建構參數改為 `ModifyTracksDialog(tracks_by_file: Dict[Path, List[MediaTrack]], existing=None, parent=None)`。
  傳整份 map 而非「範本 + map」兩個參數,避免兩者不一致;對話框仍不碰 mkvmerge,可離線測試。
- **範本**(上半部編輯表格)= `tracks_by_file` 中**第一個檔案**的軌道清單(依檔名排序後的第一個),行為與現行相同。
- `get_edits()` 產生的每個 `TrackEdit` 都填入該列範本軌道的 `track_type`。
- 新增下半部資訊表格(唯讀),欄位:**影片 / 找到 / 預設 / forced / 軌名 / 語言**。
  - 上表選取列變更 → 依該列的軌 ID 與類型呼叫 `build_track_info_rows` 重建下表。
  - 找到但類型不符的列:「找到」欄顯示 `⚠ 類型不符(字幕 → 音訊)`,並在該列註明**不會套用**。
- 對話框開啟時預設選取上表第一列,使資訊表一開始就有內容。

### 5. 封裝分頁接線(`qt/mux_tab.py`,修改)

`_on_modify_tracks` 由「同步掃第一部 + 等待游標」改為:

1. 取得所有 `matched` 配對影片;沒有就 log 提示並返回。
2. 建 `TrackScanWorker` + `QThread` + `ScanProgressDialog`,接線方式與 MKV 分頁掃描相同(`worker.progress → dialog.set_progress`、`dialog.cancelled → 直接呼叫 worker.cancel()`)。
3. **`dialog.cancelled` 必須接到一個分頁端的 slot,由它直接呼叫 `worker.cancel()`**,不可直接 `connect(worker.cancel)`——worker 已 `moveToThread`,直接連線會變成排隊連線,而該執行緒在 `run()` 期間不跑事件迴圈,取消將完全無效(此坑已於掃描進度對話框那輪踩過並修正)。
4. 掃完 → 開 `ModifyTracksDialog(tracks_by_file, self._track_edits, self)`;按 OK → `self._track_edits = dialog.get_edits()`。
5. 取消 → 不開對話框,log 記一行「已取消」。
6. 掃描結果全空(所有檔案都讀不到軌道)→ log 提示、不開對話框。

## 邊界與注意

- **掃不到軌道的檔案**:`list_all_tracks` 任何失敗都回 `[]`(既有行為),與「這個檔案真的沒有軌道」無法區分。該檔案在資訊面板會顯示為「找到 ✗」。屬既有限制,不在本次處理。
- **範本檔案本身**:也會出現在資訊面板中(它的每一列必然是「找到 ✓ 且類型相符」)。
- **掃描期間再次點擊**:進度對話框為 modal,期間點不到按鈕。
- **效能**:24 部影片約數秒到十數秒,與 MKV 分頁的掃描同一量級,已有進度與取消。

## 範圍外

- 每檔個別覆寫(面板唯讀)。
- 軌道重新排序、章節/附件的修改。
- 區分「掃描失敗」與「檔案真的沒有軌道」。
- 依資訊面板的結果自動調整勾選或自動排除有問題的檔案。

## 測試計畫(概要,交給 plan 細化)

- `TrackScanWorker`(注入假 `list_fn`,完全不碰 mkvmerge):
  - 逐檔 `progress` 序列正確、`finished` 帶完整 map。
  - `cancel()` 後發 `cancelled` 而非 `finished`,且**不再對剩餘檔案呼叫 `list_fn`**(以呼叫次數斷言,證明真的提早停)。
  - 空清單 → 直接 `finished({})`。
- `build_track_info_rows`(純函式):三種情況(找不到 / 類型相符 / 類型不符)各自的欄位值;依檔名排序。
- `build_source_track_flags` 型別比對:
  - **具體案例**:字幕軌 2 設為丟棄,某檔案的軌 2 是音訊 → 該檔案**不得**出現 `--no-audio` 或把音訊排除的旗標。
  - 類型不符時不產生 default/forced/語言/軌名 旗標。
  - 類型相符 → 與現行行為相同。
  - `track_type=None` → 維持舊行為(回歸保護)。
- `ModifyTracksDialog`:給定多檔 map,切換上表選取列 → 下表內容跟著換;`get_edits()` 產生的 `TrackEdit` 帶有正確的 `track_type`。
- `mux_tab`:掃描完成 → 開對話框;取消 → 不開對話框且不動 `_track_edits`。
- 既有全套測試維持通過(目前 386)。
