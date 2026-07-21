# SRT 字幕輸入支援 Design

**背景**:目前工具只掃描/處理 `.ass`/`.ssa` 字幕檔。使用者希望能吃常見的 SRT 格式。核心讀寫函式(`ass_style.load_subs`/`save_subs`)其實已經格式無關(`pysubs2.SSAFile.from_string()` 會自動辨識 SRT 並轉成內部物件,`save_subs` 一律輸出 ASS),真正的缺口在掃描階段的副檔名白名單,以及三個需要小心處理的邊界:輸出檔名正規化、縮放引擎的格式假設、輸出資料夾的檔名衝突防護。

## 需求(使用者確認)

1. **輸入格式**:這次只加 SRT(`.srt`)。WebVTT 等其他格式留待之後,不在本次範圍。
2. **兩種批次模式都要支援 SRT**:「套用樣式」與「縮放字級」都要能吃 SRT 輸入。
3. **輸出一律是 ASS 內容**:SRT 本身沒有樣式/字級的資料結構可以承載,套用樣式或縮放後的結果只能以 ASS 格式輸出。
4. **原地覆蓋模式對 SRT 的行為**:產生新的 `.ass` 檔放在同資料夾,**不動原始 `.srt`、不做 `.bak` 備份**(因為沒有覆蓋動作,原檔完好保留)。例:`movie.srt` → 同資料夾多一個 `movie.ass`。

## 核心設計

### 輸出檔名正規化規則

新增一個共用小函式(放 `ass_style.py`,兩個模式共用):

```python
def ass_output_name(src: Path) -> Path:
    """決定輸出檔名。.ass/.ssa 保留原副檔名(維持既有行為);其他格式(.srt)
    正規化成 .ass。回傳只是檔名決策,不含目錄。"""
    if src.suffix.lower() in {".ass", ".ssa"}:
        return src
    return src.with_suffix(".ass")
```

- `.ass`/`.ssa` 來源:輸出檔名不變(`.ssa` 維持 `.ssa` 副檔名寫入 ASS 內容,是 v1 最終審查已接受的既有行為 N4,不在本次改動)。
- `.srt` 來源:輸出檔名的副檔名換成 `.ass`。

### 「套用樣式」模式(`batch_runner.process_file`)

改動只在輸出階段(讀入與套用邏輯完全不變,因為 `load_subs`/`apply_profile`/`save_subs` 已格式無關):

- **輸出資料夾模式**:`save_subs(subs, output_dir / ass_output_name(match.sub_path).name)`
- **原地覆蓋模式**:
  - 來源是 `.ass`/`.ssa` → 行為完全不變(先 `.bak` 備份,再覆寫原檔)
  - 來源是 `.srt` → 目標路徑是 `match.sub_path.with_suffix(".ass")`,**不做 `.bak` 備份**(沒有覆蓋原檔,原 `.srt` 保留);若同名 `.ass` 已存在則覆寫(視同重跑,與既有 `.ass` 原地覆蓋的重跑語意一致)

### 「縮放字級」模式(`scale_engine`)

縮放引擎目前直接對**原始文字**做 regex(找 `Style:` 行的 Fontsize 與 `\fs` 標籤),假設輸入本來就是 ASS 語法。SRT 原始文字沒有這些,直接餵進去會找不到任何東西可縮放(不會壞,但不會做任何事)。因此非 ASS/SSA 來源需要先轉成 ASS 文字:

- `read_subtitle_text(path)` 之後、`scale_text()` 之前,加一個格式轉換步驟:若來源副檔名不是 `.ass`/`.ssa`,用 `pysubs2.SSAFile.from_string(text).to_string("ass")` 轉成 ASS 文字,再餵給既有的 `scale_text()`。轉換後的 ASS 有一個 pysubs2 預設的 `Default` Style(Fontsize 20),縮放倍率會正確作用在這個基準字級上(例:倍率 2 → 40)。
- **編碼**:縮放引擎目前保留原始檔案編碼(例如 Big5 進、Big5 出)。SRT→ASS 是換格式,輸出不再保留原編碼,一律用 UTF-8 with BOM(與 `save_subs` 一致)。ASS/SSA 來源維持既有的編碼保留行為不變。
- **共用路徑**:「試算預覽」按鈕與真正跑批次都要走同一條轉換路徑,不可各寫一套(避免預覽與實際結果不一致)。

### 輸出資料夾檔名衝突防護(`qt/batch_worker.py`)

`BatchWorker`/`ScaleWorker` 的輸出資料夾模式內建「同 basename 只寫一次」的防護(`seen_basenames`)。目前用**原始檔名**當比對 key,但正規化成 `.ass` 後會漏判:同資料夾的 `ep1.srt` 與 `ep1.ass` 兩個來源,原始檔名不同(不觸發防護),卻都想寫入同一個 `ep1.ass` → 後者靜默覆蓋前者。

- 修正:`seen_basenames` 的比對 key 改用**正規化後的輸出檔名**(`ass_output_name(match.sub_path).name`)而非原始檔名。這樣 `ep1.srt` 與 `ep1.ass` 會被正確判定為衝突,第二個被擋下並記為 error(與既有衝突防護行為一致)。
- 只改 `BatchWorker`/`ScaleWorker`(處理字幕檔的兩個 worker);`MkvWorker`/`MuxWorker` 處理的是 MKV 檔不受影響,不動。

## 掃描階段(`episode_match.py`)

`SUB_EXTS` 從 `{".ass", ".ssa"}` 擴充為 `{".ass", ".ssa", ".srt"}`。集數配對、影片配對邏輯不變(對副檔名無關)。掃描找不到字幕時的警告文字順帶更新(目前寫死「.ass/.ssa」)。

## 測試計畫(概要,交給 plan 細化)

- `ass_output_name`:`.ass`→`.ass`、`.ssa`→`.ssa`、`.srt`→`.ass`、大小寫(`.SRT`)
- `episode_match`:`.srt` 檔會被掃到並正確配對
- 套用樣式(`process_file`):
  - SRT 輸出資料夾模式 → 產生 `.ass`、內容含套用後的 Style、原 `.srt` 不動
  - SRT 原地模式 → 同資料夾產生 `.ass`、原 `.srt` 保留、無 `.bak`
  - `.ass` 來源行為回歸不變(原地備份+覆寫)
- 縮放(`scale_engine`):
  - SRT 輸入 → 轉 ASS 後縮放基準 Style 字級、輸出 UTF-8-sig ASS
  - `.ass`/Big5 來源回歸不變(保留原編碼)
- 檔名衝突防護:同資料夾 `ep1.srt` + `ep1.ass` 走輸出資料夾模式 → 第二個被擋、記 error
- 既有全套測試(284)維持通過

## 範圍外

- WebVTT / MicroDVD / SAMI / TTML 等其他 pysubs2 支援的格式(架構上加起來很容易,但這次只驗證 SRT;之後要加只需擴 `SUB_EXTS` 並確認轉換路徑)
- 反向輸出(把 ASS 樣式「烤」回 SRT 純文字)——SRT 無樣式概念,不做
- SRT 特有的定位標籤(`{\an8}` 之類在 SRT 少見的擴充語法)特殊處理——pysubs2 的標準轉換怎麼處理就怎麼處理,不另外加工
