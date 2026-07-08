# ASS 字幕樣式批次工具

批次把整季動畫的 ASS/SSA 字幕檔中指定的 Style(例如 `Default` 一般對話)
統一改成你設定的字型、大小、顏色、外框、陰影、位置,並依各集字幕檔的
PlayResX/PlayResY 按比例縮放數值,讓不同解析度片源的視覺大小一致。
其他 Style(OP/ED/特效/標示)完全不受影響。

## 安裝

需要 Python 3.9+。

```powershell
python -m pip install -r requirements.txt
```

選配:

- `tkinterdnd2` — 支援拖放資料夾(未安裝時退回「瀏覽資料夾」按鈕)
- `ffmpeg/ffprobe`(需在 PATH 中)— 掃描預覽時顯示影片實際解析度,
  並在 PlayRes 長寬比與影片不符時發出警告;不影響樣式套用本身

## 使用

```powershell
python -m ass_style_tool
```

1. 選擇(或拖放)放字幕/影片的資料夾
2. 編輯目標樣式,或「載入設定檔」(見 `profiles/sample-1080p.json`)
3. 選擇輸出模式:原地覆蓋(自動備份 `.bak`)或輸出到新資料夾
4. 按「掃描並預覽配對」,確認每個字幕檔的集數與影片配對正確
5. 按「開始套用樣式」,在 log 檢視每檔結果與總結

## 縮放規則

樣式數值以設定檔的「基準解析度」為基準;每個字幕檔依自己的
PlayResX/PlayResY 按比例換算(缺一個依 4:3 推導、全缺依規範用 384x288)。
工具**不會**改寫 PlayResX/PlayResY/ScaledBorderAndShadow 標頭,
也不會動到未列在「目標 Style 名稱」中的樣式。

## 開發

```powershell
python -m pytest tests -v
```

設計文件:`docs/superpowers/specs/2026-07-08-ass-style-batch-tool-design.md`
