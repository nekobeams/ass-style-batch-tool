# ASS 字幕樣式批次修改工具 — 設計文件

日期:2026-07-08

## 背景與目標

使用者需要一個工具,能夠對「整季」動畫的 ASS/SSA 字幕檔進行批次樣式統一:
把每一集字幕中指定的 Style(如 `Default`,即一般對話字幕)改成同一組固定樣式(字型、大小、顏色、外框、陰影、位置),並在不同集數/片源解析度不一致時,依比例換算數值,讓視覺大小保持一致。其他 Style(OP/ED/標示片名等特效字幕)不受影響。

工具需要簡單的圖形介面(拖放資料夾 + 按鈕操作),供非命令列使用者操作。

## 技術棧與依賴

- Python 3.9+
- [`pysubs2`](https://pypi.org/project/pysubs2/):讀寫 ASS/SSA 檔案與 Style
- `charset-normalizer`:自動偵測字幕檔文字編碼
- `tkinterdnd2`(選用):讓 tkinter 支援拖放資料夾;未安裝時 GUI 自動退回「瀏覽資料夾」按鈕
- 系統需安裝 **ffmpeg/ffprobe** 並存在於 PATH 中,用來偵測影片實際解析度(用於預覽顯示與長寬比不符警告,不參與縮放計算)

## 模組拆分

| 模組 | 職責 |
|---|---|
| `ass_style.py` | 讀寫 ASS 檔、把目標樣式套用到指定 Style 名稱 |
| `episode_match.py` | 從檔名猜集數編號、配對字幕與影片檔 |
| `resolution.py` | 呼叫 ffprobe 偵測影片解析度、計算縮放比例 |
| `profile.py` | 讀寫 JSON 設定檔(目標樣式 profile) |
| `batch_runner.py` | 串接以上模組,跑整個資料夾,產生處理紀錄 |
| `gui.py` | tkinter 介面,呼叫 `batch_runner` 執行批次處理 |

每個模組只依賴其下層模組,可獨立測試(例如 `resolution.py` 不依賴 GUI 或 ASS 解析)。

## 設定檔(Profile)格式

JSON 檔,範例:

```json
{
  "profile_name": "我的一般字幕標準",
  "target_style_names": ["Default"],
  "base_resolution": { "width": 1920, "height": 1080 },
  "style": {
    "fontname": "思源黑體 CN",
    "fontsize": 72,
    "bold": false,
    "italic": false,
    "primary_colour": "&H00FFFFFF",
    "outline_colour": "&H00000000",
    "back_colour": "&H00000000",
    "outline": 3.6,
    "shadow": 1.0,
    "alignment": 2,
    "margin_l": 20,
    "margin_r": 20,
    "margin_v": 24
  }
}
```

- `target_style_names`:要套用此樣式的 Style 名稱清單(其餘 Style 不動)
- `base_resolution`:以上數值是依照這個解析度設計的基準
- `style` 下除 `fontname`/顏色/`bold`/`italic`/`alignment` 外,其餘欄位(`fontsize`、`outline`、`shadow`、`margin_l/r/v`)會依每集實際參考解析度做比例縮放

GUI 提供對應欄位(文字輸入、色彩選擇器、勾選框、下拉選單)編輯以上內容,並可「載入設定檔」/「另存新設定檔」。

## 參考解析度判斷與縮放邏輯

ASS 字幕的座標與字體大小是相對於檔案自己宣告的 `PlayResX`/`PlayResY` 虛擬畫布渲染的,播放器再把畫布縮放貼合到實際影片。因此縮放參考必須跟隨播放器的實際行為:

**每一集的參考解析度,依下列規則決定(與 libass/VSFilter 行為一致):**

1. 若該 ASS 檔的 `PlayResX`/`PlayResY` 皆有效(> 0)→ 直接使用此值作為參考解析度
2. 若只有其中一個有效 → 依 4:3 比例推導出另一個(播放器的實際行為)
3. 兩者皆缺失或無效 → 參考解析度為 **384×288**(ASS 規範/播放器的預設虛擬畫布),並在 log 記錄提示

**ffprobe 的角色**:偵測每集配對影片的實際解析度,用於——
- 在「掃描預覽」中顯示,供使用者確認配對正確
- 當 PlayRes 的長寬比與影片長寬比明顯不符時,在預覽與 log 中發出警告(此類檔案字幕可能變形,值得人工檢查)

ffprobe 結果**不參與**縮放計算;縮放只依上述 PlayRes 規則。

**工具絕不改寫 `[Script Info]` 中的 `PlayResX`/`PlayResY` 標頭**——只更新目標 Style 那一行的數值,避免影響特效字幕的絕對座標。同樣不改寫 `ScaledBorderAndShadow` 標頭,但會在 log 記錄各檔的設定值(此標頭影響外框/陰影是否隨解析度縮放,檔案間不一致時視覺會有微妙差異,記錄下來方便排查)。

**縮放公式:**

```
scale_y = 該集參考解析度高度 / base_resolution.height
scale_x = 該集參考解析度寬度 / base_resolution.width

new_fontsize  = round(style.fontsize  * scale_y)
new_outline   = round(style.outline   * scale_y, 2)
new_shadow    = round(style.shadow    * scale_y, 2)
new_margin_v  = round(style.margin_v  * scale_y)
new_margin_l  = round(style.margin_l  * scale_x)
new_margin_r  = round(style.margin_r  * scale_x)
```

## 集數/影片配對邏輯

1. 掃描輸入資料夾,列出所有字幕檔(`.ass`/`.ssa`)與影片檔(`.mkv`/`.mp4` 等常見副檔名)
2. 用正則表達式從檔名中抽取集數編號,涵蓋常見字幕組命名慣例(如 `[01]`、`[EP01]`、`[E01]`、`- 12 [` 等),並排除明顯非集數的數字(解析度如 `1080`/`720`、位元深度如 `10bit`、年份等)
3. 依抽取到的集數編號,將字幕檔與影片檔配對成一對一關係
4. 配對不到影片的字幕檔標記為「無對應影片」——不影響樣式套用與縮放(縮放只依 PlayRes 規則),僅少了預覽時的影片解析度資訊與長寬比警告
5. 若同一集數編號配對到多個候選字幕或影片(例如同集有兩種版本檔名),標記為「配對模糊」,在預覽與 log 中列出讓使用者自行確認

## 執行流程(GUI)

1. **輸入區**:拖放資料夾,或用「瀏覽資料夾」按鈕選取(`tkinterdnd2` 未安裝時退回按鈕模式)
2. **目標樣式編輯區**:字型名稱、大小、粗體/斜體、主色/外框色/陰影色(色彩選擇器)、外框寬度、陰影深度、對齊方式(1–9)、邊距 L/R/V、基準解析度、目標 Style 名稱清單
3. **設定檔區**:載入 / 另存 JSON 設定檔
4. **輸出模式**:單選「原地覆蓋(自動備份為 `.bak`)」或「輸出到新資料夾」
5. **掃描並預覽配對**:列出字幕/影片配對結果與抽取到的集數編號,供使用者在真正套用前肉眼確認
6. **開始套用樣式**:背景執行緒跑批次處理,log 區塊即時顯示每個檔案的處理結果,結束後顯示總結(成功/跳過/錯誤各幾集)

## 錯誤處理原則

單集處理失敗不中斷整批,只跳過該集並記錄原因:

- ffprobe 未安裝/找不到 → 程式啟動時偵測並提示,仍可繼續執行(僅預覽中少了影片解析度資訊與長寬比警告,不影響樣式套用)
- ASS 檔解析失敗 → 跳過該檔,記錄錯誤原因
- 找不到指定的目標 Style 名稱 → 跳過該檔樣式套用,記錄警告,**不會**自動新增 Style
- 文字編碼判斷失敗(UTF-8/Big5/GBK 皆讀取失敗)→ 跳過該檔,記錄錯誤
- 原地覆蓋模式下,寫入前必定先備份為 `.bak`;若備份失敗則不執行覆蓋
- 輸出統一以 UTF-8 with BOM 寫回(Aegisub 預設格式)
- 「輸出到新資料夾」模式只會寫入處理後的字幕檔;影片檔全程唯讀,兩種輸出模式都不會被搬動或複製

## 範圍外(不在本次設計內)

- 不支援 SRT 或其他無樣式字幕格式
- 不支援 Style 名稱在不同集數間不一致的自動判斷(假設命名基本一致)
- 不提供手動逐一指定字幕/影片配對表的介面(僅靠檔名規則自動配對 + 預覽確認)
- 不支援系統字型清單選擇器(字型名稱以文字輸入為主)
