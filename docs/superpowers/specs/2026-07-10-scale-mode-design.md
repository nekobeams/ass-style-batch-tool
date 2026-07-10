# 縮放字級模式(Scale Mode)— 設計文件

日期:2026-07-10
關聯:v2 設計 `2026-07-08-ass-style-tool-v2-design.md`(本功能為其擴充)

## 目標

在現有「套用樣式」(整組替換為 profile)之外,新增第二種批次操作:**保持原樣式不變,只把字級等比縮放**。各 Style 的相對大小關係、對白內手動 `{\fs40}` 覆寫都跟著等比變化。原有功能完整保留,兩種模式在 GUI 中切換。

需求源自使用者提供的 CLI 工具 prompt(功能規格全數採納),但**只做 GUI 模式,不做 CLI**。

## 核心:scale_engine.py(純邏輯,逐行處理)

與現有 pysubs2 路徑完全分開的獨立引擎,原則是「**檔案完整性優先,只改必要數值**」:

### 解析
- 動態解析 `[V4+ Styles]` 與 `[V4 Styles]` 的 `Format:` 行,依欄位名稱找出 `Fontsize`、`Outline`、`Shadow` 的索引;**不可寫死欄位位置**(v4 與 v4+ 順序不同)
- Section 判斷大小寫不敏感、容忍前後空白

### 縮放模式(互斥)
- **倍率模式**:`factor`(如 1.25),所有 Style 的 Fontsize × factor
- **目標模式**:`target_size` + `base_style`(預設 `"Default"`;檔內找不到該名稱時用第一個 Style 當基準)。基準 Style 的 Fontsize 設為 target_size,實際 factor = target_size / 基準原值,其餘 Style 依同一 factor 等比縮放
- 邊界:基準 Style 的 Fontsize 解析失敗或 ≤ 0 → 該檔回報錯誤、不寫檔(單檔失敗不中斷整批)

### 縮放範圍選項
- `scale_decorations: bool = True` — 同步以相同 factor 縮放 Outline、Shadow
- `scale_inline_fs: bool = True` — 縮放 [Events] 內 inline `\fs<數字>` 覆寫(如 `{\fs40}` 或連寫 `\fs40`)。正則必須排除 `\fscx`、`\fscy`、`\fsp` 等以 `\fs` 開頭的其他標籤(以「\fs 後緊接數字」判定)
- `scale_fscxy: bool = False` — `\fscx`/`\fscy` 是百分比縮放,預設不動(改了會變形);開啟時同步乘 factor

### 數值格式
- Fontsize 可能是小數;計算後四捨五入到小數點 1 位
- 能整數就輸出整數(不產生 `40.0` 這種字串;`40.5` 保留一位小數)

### 完整性保證
- **保留原始編碼**:讀檔時偵測(utf-8-sig 優先,再 charset-normalizer,沿用既有 detect 邏輯但需記住「原編碼與是否有 BOM」),寫回時用同一編碼與 BOM 狀態
- **保留原始換行符**(CRLF/LF,以檔案實際內容為準),不強制轉換
- 逐行處理:不重排欄位、不刪除註解(`;` 開頭行)、不動其他 section、不動 `[Script Info]` 的 PlayResX/PlayResY
- 非 ASS/SSA 內容(找不到 Styles section)→ 回報錯誤不寫檔

### 介面(供 GUI 與測試)

```python
@dataclass
class ScaleOptions:
    factor: float | None            # 倍率模式
    target_size: float | None       # 目標模式(與 factor 互斥,恰一個非 None)
    base_style: str = "Default"
    scale_decorations: bool = True
    scale_inline_fs: bool = True
    scale_fscxy: bool = False

@dataclass
class StyleChange:
    name: str
    old_size: str
    new_size: str

@dataclass
class ScaleReport:
    style_changes: list[StyleChange]
    inline_fs_count: int
    factor_used: float

scale_text(text: str, options: ScaleOptions) -> tuple[str, ScaleReport]   # 純函式
scale_file(path: Path, options: ScaleOptions, out_path: Path | None) -> ScaleReport
    # out_path=None 表原地(先備份 .bak,沿用既有「.bak 已存在則不覆蓋」原則)
    # dry-run 由呼叫端用 scale_text 自行實現(不寫檔)
```

## GUI 整合(字幕檔分頁)

- 分頁頂部新增「**操作模式**」切換(radio):`套用樣式`(現有,行為不變)/ `縮放字級`(新)
- 切到縮放模式時,樣式 profile 相關驗證不參與;顯示縮放面板:
  - 模式二選一:「倍率 ×」數值框 /「主 Style 設為」數值框 + 基準 Style 名稱框(預設 Default)
  - 勾選:同步縮放外框/陰影(預設勾)、縮放對白內 \fs(預設勾)、同步縮放 \fscx/\fscy(預設不勾)
- **試算預覽(不寫檔)按鈕**(= dry-run):對掃描到的每個字幕檔跑 `scale_text`,log 列出每檔「Style 舊值 → 新值」與 inline \fs 修改數,不寫任何檔
- 執行:沿用掃描結果與輸出模式(原地 .bak / 輸出新資料夾),逐檔在背景執行緒跑 `scale_file`,進度/取消/總結與現有批次一致
- 單檔失敗記錄後繼續,不中斷整批(沿用既有原則)

## 測試策略(TDD)

純函式重點測試:
- Format 欄位索引解析:v4+ 與 v4 兩種順序、欄位名帶空白
- 倍率與目標模式數值計算(含基準 style fallback 到第一個)
- inline `\fs` 縮放:`{\fs40}`、連寫 `{\b1\fs40}`;**不誤傷** `\fscx100`、`\fscy100`、`\fsp2`;`--scale-fscxy` 開啟時 `\fscx/\fscy` 正確縮放
- 數值格式:`40`→整數輸出、`40.55`→一位小數、`40.0`→`40`
- 完整性 round-trip:縮放 factor=1.0 時輸出與輸入逐位元組一致(UTF-8 與 Big5 樣本、CRLF 與 LF 各一);註解行、其他 section、PlayRes 不變
- 編碼保留:Big5 進 → Big5 出;UTF-8-BOM 進 → UTF-8-BOM 出
- 測試樣本 fixture:v4+ 檔、v4 檔、含 inline \fs 對白檔、Big5 編碼檔

GUI 部分:offscreen Qt 測縮放面板取值/互斥驗證、模式切換;互動與視覺走手動清單。

## 範圍外

- CLI 介面(使用者確認不需要)
- SRT/其他格式
- MKV 內字幕軌的縮放(Plan 2c 完成 MKV 流程後可自然銜接,本版不做)
