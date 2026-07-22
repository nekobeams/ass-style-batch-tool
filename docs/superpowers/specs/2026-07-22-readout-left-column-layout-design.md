# 換算對照讀出移至左欄 Design

**背景**:上一個功能把「換算對照」讀出加在「樣式與預覽」分頁的**右側**預覽面板(mpv 播放器下方)。使用者回饋:編輯樣式才是主要動作,看換算只是順便,所以讀出應該放在**左側樣式編輯區**、跟著樣式欄位一起,而不是在右邊另一區。使用者選定「選項 1」:讀出併入左欄、捲動時一起捲。

同時點出一個現存版面問題:左側樣式編輯區(`style_editor.py`)目前是普通垂直排列、**沒有捲動區**,視窗一縮小欄位就被裁切。要把讀出放到欄位下面(更長),勢必得把左欄包進捲動區。使用者確認:**整個左欄(profile 選擇列 + 所有欄位 + 換算對照)一起捲動**。

功能本身(換算數字、比例檢查、缺失訊息、即時更新)完全不變,本次只搬位置 + 加捲動區 + 重整職責。

## 需求(使用者確認)

1. 換算對照讀出從右側預覽面板搬到**左側樣式編輯區的底部**,排在所有樣式欄位之後,捲到底就看到(選項 1)。
2. **整個左欄包進 `QScrollArea`**(`setWidgetResizable(True)`):profile 選擇列 + 樣式欄位 + 換算對照全部在同一個捲動區一起捲。視窗縮小 → 出現捲軸、不裁切;視窗夠大 → 與現況相同。
3. 右側預覽面板**不再**放讀出(讓影片區更寬)。
4. 讀出的內容與即時更新行為維持不變:白話機制說明、情境行 + 影片比例檢查、原字幕現值→套用後三欄表、目標樣式缺失訊息、以及跟著檔案載入與樣式編輯即時刷新。

## 核心設計

職責拆成三塊,讀出的「顯示」與「資料來源」解耦。

### 新元件 `ReadoutView`(`qt/readout_view.py`,純顯示、無資料來源)

把目前散在 `PreviewPanel` 裡的讀出顯示 widget 抽成一個獨立元件:

- 內含:機制說明 label、情境(字幕)label、情境(影片)label、缺失訊息 label(預設隱藏)、三欄表 `QTableWidget`(樣式/原字幕現值/套用後)、不縮放欄位註解 label。以一個 `QGroupBox`(標題「換算對照(套用後的實際數字)」)包起來。
- 方法 `update_from(data: Optional[ReadoutData]) -> None`:
  - `data is None` → 顯示佔位提示(「載入字幕檔後顯示換算結果」),表格清空/隱藏。
  - `data.missing_message` 非空 → 顯示缺失訊息 label、隱藏表格。
  - 否則 → 填機制/情境/表格/註解,顯示表格、隱藏缺失訊息。
- 這段渲染邏輯直接搬自現有 `PreviewPanel._update_readout` 的「填 widget」部分,行為不變。ReadoutView 不認識 profile / 檔案 / 影片,只認識 `ReadoutData`。

### `PreviewPanel`:改成用訊號送出 `ReadoutData`,不再自己放讀出 widget

- **移除**面板內的讀出 widget 與其 `QGroupBox`(`readout_mechanism`/`readout_context_sub`/`readout_context_video`/`readout_missing`/`readout_table`/`readout_note`)。
- **保留**資料蒐集:`_source_sub`、`_source_subs`、`_video_path`、`_video_res`、`_set_video`、`_lookup_original`、`get_play_res`,以及在 `_apply_preview` 末端呼叫更新的時機(檔案載入 + 樣式編輯防抖)。
- 新增訊號 `readout_changed = Signal(object)`(payload 為 `ReadoutData`)。
- `_update_readout` 改為:蒐集輸入 → `build_readout(...)` 得到 `ReadoutData` → `self.readout_changed.emit(data)`。
  - profile 無效(`get_profile()` 丟 `ValueError`)或尚未載入字幕(`_source_sub`/`_source_subs` 為 None)→ **不 emit**(維持接收端上一次顯示,與現行「保留上一次讀出」語意一致)。
- 版面上原本放讀出的位置留白(面板只剩播放器 + 時間軸 + 字幕行清單 + 狀態列)。

### `StyleEditor`:整個內容包進捲動區,底部嵌 `ReadoutView`

- 目前 `__init__` 直接把 `profile_row` + `form` 加進 `root = QVBoxLayout(self)` 並 `addStretch(1)`。改為:
  - 建一個 inner `QWidget`,其 `QVBoxLayout` 依序放:`profile_row`、`form`、`self.readout_view`(新)、`addStretch(1)`。
  - 建 `QScrollArea`,`setWidgetResizable(True)`、`setWidget(inner)`,並(依主題)`setFrameShape(QFrame.NoFrame)` 讓外觀不多一圈框。
  - `StyleEditor` 的 `root` 只放這個 `QScrollArea`。
- 新增 `self.readout_view = ReadoutView()`,並以屬性暴露供 `main_window` 接線。
- 既有欄位、色彩選擇、profile 存讀、字型警告、`values_changed` 訊號等邏輯完全不變(只是被包進 inner widget)。

### `main_window`:接線

- 目前 `_preview_split` 內 `style_editor`(左)+ `preview_panel`(右)結構不變。
- 新增一行接線:`self.preview_panel.readout_changed.connect(self.style_editor.readout_view.update_from)`。
- (先前讀出完全在 `PreviewPanel` 內部自建自顯示,main_window 端沒有相關接線可移除;本次只新增上面這一行。)

## 資料流

```
使用者編輯樣式 / 載入字幕檔
  → StyleEditor.values_changed(既有) 或 PreviewPanel.set_media
  → PreviewPanel._apply_preview(既有防抖)
  → PreviewPanel._update_readout: build_readout(...) → readout_changed.emit(data)
  → StyleEditor.readout_view.update_from(data) 渲染在左欄底部
```

（profile 無效或未載入檔 → 不 emit → 左欄讀出維持上一次/佔位提示。）

## 範圍外

- 不動縮放數學(`compute_applied_values`)、`build_readout` 的組裝邏輯、視覺預覽(mpv)本身。
- 不改讀出的內容/欄位/文案(只搬位置與載體)。
- 不做 profile 列固定在頂部(使用者選「全部一起捲動」)。

## 測試計畫(概要,交給 plan 細化)

- `ReadoutView`(`tests/test_readout_view.py`,新):
  - `update_from(None)` → 顯示佔位提示、表格空/隱藏。
  - `update_from(data)`(有 rows)→ 三欄表格內容正確、缺失 label 隱藏。
  - `update_from(data)`(有 missing_message)→ 缺失 label 顯示、表格隱藏。
- `PreviewPanel`(`tests/test_preview_panel.py`,改):既有讀出測試改為**驗證 `readout_changed` 送出的 `ReadoutData`**(用訊號捕捉,不再驗證面板內的表格 widget);涵蓋:載入檔 → emit 正確 rows/機制字串;有影片(mock `probe_video_resolution`)→ 比例狀態正確;profile 無效 → 不 emit(保留上次);樣式改變 → emit 的套用值改變。
- `StyleEditor`(`tests/test_style_editor.py`,加):內容被包進 `QScrollArea`;`readout_view` 存在且在捲動內容內;`readout_view.update_from(data)` 能正確渲染(或透過 StyleEditor 轉呼叫)。
- `main_window`(`tests/test_main_window.py`,加):`preview_panel.readout_changed` 有接到 `style_editor.readout_view`——例如對 preview_panel 觸發一次更新(mock 探測),斷言左欄 `readout_view` 表格被填。
- 既有全套測試維持通過(目前 319)。
