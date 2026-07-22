# 套用樣式「換算對照」讀出 Design

**背景**:使用者在「套用樣式」模式常困惑於一件事——profile 裡設定的是基準值(例如基準 1920×1080、字級 72),但實際套用到某個字幕檔後,寫進檔案的數字完全不同(例如 640×360 的檔案變成字級 24)。目前工具**沒有任何地方**能在寫檔前把「這個檔案會被換算成多少」直接顯示出來:縮放模式有「試算預覽(不寫檔)」按鈕會把數字印到 log,但套用樣式模式完全沒有對應功能,使用者只能真的執行、再用外部編輯器(Aegisub/Subtitle Edit)打開輸出檔才看得到結果。

工具其實**已經有視覺預覽**:第四個「樣式與預覽」分頁右側是內嵌 mpv 播放器,會把 profile 以與批次完全相同的縮放套用到來源字幕、疊在影片畫面上即時熱重載(`preview.py:render_preview_ass` → `ass_style.apply_profile`)。但它有兩個侷限:(1) 只有載入影片後才會渲染字幕外觀,沒影片就只剩字幕行清單;(2) 它顯示的是「看起來長怎樣」,從不顯示「換算後的具體數字」。

本次補上真正缺的那塊:一個即時的**數字換算對照讀出**,讓使用者一眼看懂「原字幕現值 → 套用後的值」以及背後的縮放關係,並順帶把「與影片的比例關係」呈現出來。

## 需求(使用者確認)

1. 目標定調為「**方便使用者了解工具在做什麼**」——重點是可理解性,不是花俏。
2. 要能同時看清楚三者關係:**原字幕現在的值 → 套用 profile 後的值 → 在什麼影片上、比例對不對**。
3. 放在「樣式與預覽」分頁,與既有視覺預覽並存、互相印證;跟著樣式編輯即時更新。
4. 保證讀出的數字與批次實際寫檔的數字**完全一致**(不可各算一套)。

## 核心概念釐清(寫進設計以免做錯)

ASS 字級是相對於字幕自己的畫布(PlayResX/PlayResY),播放器把這塊畫布整個拉伸貼合影片畫面。因此:

- **影片的像素解析度不會改變字幕的相對大小**——同一個 24 級的字(畫布 360 高)在 360p 或 1080p 影片上都佔畫面高 6.67%。
- 影片解析度**唯一真正影響「適配對不對」的地方是長寬比**:字幕畫布 16:9、影片 4:3 → 字被拉伸變形。工具已有 `resolution.aspect_mismatch()` 在算這件事,只是目前沒顯示。

所以「原字幕 ↔ 影片」關係由兩者分工呈現:**視覺預覽**(把字直接畫在真實影片上)回答「看起來對不對」;**數字讀出 + 比例檢查**回答「數字怎麼變、比例對不對」。本次只做後者(前者已存在,僅加引導文字)。

## 核心設計

### 單一計算來源:`compute_applied_values`(`ass_style.py`)

把目前內嵌在 `apply_profile` 迴圈裡的縮放數學抽成一個純函式,讀出與寫檔共用同一份計算,杜絕預覽與實際結果不一致:

```python
@dataclass
class AppliedValues:
    scale_x: float
    scale_y: float
    ref_w: int          # 縮放實際採用的參考寬(經 reference_resolution 補值後)
    ref_h: int
    fontsize: int       # round(base.fontsize * scale_y)
    outline: float      # round(base.outline * scale_y, 2)
    shadow: float       # round(base.shadow * scale_y, 2)
    margin_l: int       # round(base.margin_l * scale_x)
    margin_r: int       # round(base.margin_r * scale_x)
    margin_v: int       # round(base.margin_v * scale_y)


def compute_applied_values(profile: Profile, play_res_x: int, play_res_y: int) -> AppliedValues:
    """給定 profile 與某檔案的 PlayRes,回傳套用後各數值欄位的換算結果。
    縮放/四捨五入規則必須與 apply_profile 寫檔時逐欄位一致。"""
```

- 計算方式完全比照現有 `apply_profile`:`reference_resolution(play_res_x, play_res_y)` 補值 → `compute_scale(ref_w, ref_h, profile.base_width, profile.base_height)` → 各欄位乘上 `scale_x`/`scale_y` 並套用同樣的 `round()` 位數。
- `apply_profile` 改為呼叫 `compute_applied_values` 取得換算結果,再把值指派到 style 上(fontname/bold/italic/顏色/alignment 這些**不縮放**的欄位維持原本直接指派)。行為必須逐位元組不變(以既有測試回歸驗證)。

### 讀出元件(`qt/preview_panel.py` 內新增)

在 `PreviewPanel` 內新增一塊唯讀顯示區(置於現有播放器/清單附近,具體版面實作階段決定),由上到下三層:

**① 白話機制說明(一句話)**
> 工具把 profile(基準 1920×1080)依這個檔案的畫布 640×360 等比縮小 **0.333×** 後套用

（縮放倍率取 `scale_y` 顯示到 3 位小數;基準值取自目前 profile,畫布取自目前載入的字幕檔。）

**② 情境行 + 影片比例檢查**
```
此檔案:[GoldenTime][01].tc.ass · 字幕畫布 640×360
影片:  [GoldenTime][01].mkv · 1920×1080 · 比例相符 ✓
```
- 影片解析度以既有的 `resolution.probe_video_resolution(video_path)`(ffprobe)取得;比例判斷用既有的 `resolution.aspect_mismatch(canvas, video)`。
- 比例不符時顯示:`⚠ 比例不符,字幕可能被拉伸變形`。
- **無影片 / ffprobe 不可用 / 探測失敗時優雅降級**:「影片」行改顯示 `載入影片可看到實際疊在畫面上的效果`(引導使用者去用視覺預覽),不顯示比例檢查,其餘讀出照常運作。

**③ 三欄對照表(只列會縮放的欄位)**
```
樣式        原字幕現值    套用後
字級        28       →    24
外框        2.8      →    1.2
陰影        0        →    0.33
邊界 V      18       →    8
```
- 「套用後」欄取自 `compute_applied_values`。
- 「原字幕現值」欄取自目前載入字幕檔中**將被修改的目標樣式**(見下「目標樣式判定」),讀其現有的 fontsize/outline/shadow/marginv。
- 只列會縮放的欄位(字級/外框/陰影/邊界)——這些才是「數字為什麼變」的困惑點。邊界 L/R/V 是否全列或僅列 V,實作階段依版面決定,至少列字級、外框、陰影、邊界 V。
- 表格下方一行小字:`字型、顏色、對齊 直接採用 profile 設定(不縮放)`——一句話交代其餘欄位的行為。

**目標樣式判定與特殊情況**:
- 「將被修改的目標樣式」= profile 的 `target_style_names` 中,第一個實際存在於此檔案的樣式名。
- 若 profile 目標樣式名在此檔案中都不存在(例如目標設「字幕」但檔案只有「Default」):三欄表的「原字幕現值」欄顯示 `此檔案無此樣式 → 將略過`,明確解釋「為什麼套了沒反應」。「套用後」欄一併留白或標示不適用。
  - 註:此判定僅為讀出呈現用途,反映 `apply_profile` 預設(依名稱精確比對)的行為;不涉及 SRT 轉檔的 `apply_to_all_styles` 路徑(該路徑不經由本預覽面板)。

### 更新時機(沿用既有訊號,不新增計時器)

讀出在下列時機刷新,與視覺預覽同步:
- **載入字幕檔時**:`PreviewPanel.set_media()`(已存在,會設定 `_source_sub` 並讀檔)。
- **編輯樣式值時**:`StyleEditor.values_changed` → `PreviewPanel.on_style_changed()` → 現有 300ms 防抖 → `_apply_preview()`。在 `_apply_preview()`(或其呼叫的更新流程)內一併更新讀出。
- 需追蹤目前影片路徑:`PreviewPanel` 記錄 `set_media`/`_open_video` 傳入的 video_path,供比例檢查探測用。
- profile 欄位打到一半暫時無效(`get_profile()` 丟 `ValueError`)時,與現有邏輯一致——略過本次更新,保留上一次讀出。
- 尚未載入任何字幕檔時:讀出顯示佔位提示(例如「載入字幕檔後顯示換算結果」)。

## 範圍外(YAGNI)

- **視覺渲染器**:已存在(mpv/libass),本次只加「無影片時引導載入」的文字,不改渲染管線。
- **字幕檔分頁的整批 log 試算**:單檔即時讀出已足夠達成「看懂工具」目標;整批預檢(套用樣式版的 dry-run)可作未來擴充,本次不做。
- **顏色/字型的視覺化對比**(色塊、字型樣本):不縮放的欄位以文字一句話交代即可,不做視覺化。
- **影片像素解析度影響字級的錯誤呈現**:明確不把影片解析度當成字級縮放因子(那會誤導);影片解析度僅用於比例檢查與情境顯示。

## 測試計畫(概要,交給 plan 細化)

- `compute_applied_values`(純函式,好測):
  - 640×360 對基準 1920×1080 → scale 0.333,驗證字級 72→24、外框 3.6→1.2、陰影 1.0→0.33、邊界依 scale_x/scale_y 換算的結果與四捨五入位數。
  - PlayRes 缺漏 / 單邊缺(觸發 `reference_resolution` 補值)→ 參考解析度與縮放正確。
  - scale=1.0(基準與畫布相同)→ 數值不變。
- `apply_profile` 回歸:抽取計算後,既有寫檔行為逐欄位不變(沿用既有測試 + 確認與 `compute_applied_values` 對齊)。
- 讀出資料組裝(將 UI 呈現邏輯與純資料組裝分離以便測試):
  - 目標樣式存在 → 三欄「原值→套用後」正確(原值取自檔案樣式、套用後取自 compute)。
  - 目標樣式不存在 → 標示「將略過」。
  - 有影片且比例相符/不符 → 比例檢查結果正確(mock `probe_video_resolution`)。
  - 無影片 / 探測失敗 → 降級文字正確,不崩潰。
- 既有全套測試(297)維持通過。
