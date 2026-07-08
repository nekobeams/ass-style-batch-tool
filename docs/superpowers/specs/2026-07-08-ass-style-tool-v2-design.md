# ASS 字幕樣式批次工具 v2 — 設計文件

日期:2026-07-08
前作:`2026-07-08-ass-style-batch-tool-design.md`(v1,已實作完成並合入 master)

## 目標

在 v1(散裝 .ass/.ssa 批次改樣式)的基礎上擴充四項能力:

1. **即時預覽**:內嵌 mpv 播放器,載入影片後改樣式即時看到真實渲染效果(Subtitle Edit 式體驗)
2. **直接修改 MKV 內的字幕軌**:列舉、抽取、改樣式、重封裝,不動其他軌
3. **GUI 改版**:PySide6 深色分頁籤介面(風格參考 yaser01/mkv-muxing-batch-gui)
4. **打包發佈**:PyInstaller + Inno Setup 安裝程式,外部工具混合式內建

v1 核心邏輯模組(profile/resolution/ass_style/episode_match/batch_runner)**完全保留不動**,既有 62 個測試持續有效。舊 tkinter GUI(`gui.py`)移除(git 歷史可回溯)。

## 技術棧

- **PySide6**:GUI 框架(與參考專案相同)
- **python-mpv + libmpv**:內嵌播放器,ASS 由 mpv 內建 libass 精準渲染
- **MKVToolNix**(mkvmerge/mkvextract):MKV 列舉、抽取、重封裝
- **ffprobe**:沿用 v1(散裝影片解析度偵測)
- **PyInstaller(onedir)+ Inno Setup**:打包與安裝程式
- 既有:pysubs2、charset-normalizer、pytest

## 模組結構

```
ass_style_tool/
├── profile.py / resolution.py / ass_style.py / episode_match.py / batch_runner.py  (v1 不動)
├── tools.py          # 外部工具偵測:PATH → 常見安裝目錄(含登錄檔) → 內建 tools/ 資料夾
├── mkv_io.py         # mkvmerge -J 解析、mkvextract 抽軌、mkvmerge 重封裝命令組裝與進度解析
├── preview.py        # 預覽協調:套用目前樣式產生暫存 .ass、供 mpv sub-reload
└── qt/
    ├── main_window.py    # 主視窗、分頁籤、log 區、設定持久化(QSettings)
    ├── style_editor.py   # 樣式編輯面板 + profile 下拉切換 + 字型未安裝警告
    ├── file_table.py     # 檔案配對表格(字幕檔頁籤)與字幕軌表格(MKV 頁籤)
    ├── player.py         # 內嵌 mpv widget、時間軸、字幕行清單點擊跳轉
    └── theme.py          # 深色/淺色主題 QSS + 主題模式(跟隨系統/深色/淺色)切換與偵測
```

## GUI 佈局(深色、分頁籤)

- **「字幕檔」頁籤**:v1 流程——選資料夾 → 掃描預覽配對表格 → 批次套用(原地 .bak / 輸出新資料夾)
- **「MKV」頁籤**:選資料夾 → 掃描列出每個 MKV 的 ASS 字幕軌(語言/軌名/格式)→ 勾選要改的軌 → 重封裝
- **「樣式與預覽」頁籤**:左側樣式編輯欄位(v1 全部欄位),右側 mpv 播放器 + 時間軸 + 字幕行清單
- 底部共用 log 區 + 進度條 + 取消按鈕
- 整個視窗接受拖放資料夾/檔案(Qt 原生)

## 即時預覽

**資料流**:樣式欄位變更 → 300ms 防抖 → `preview.py` 把目前樣式套進當前字幕的複本、寫入暫存 .ass → mpv `sub-reload` → 畫面更新。

- 影片來源:掃描配對到的影片一鍵載入;或手動開啟任意影片檔
- **字幕行清單**:載入字幕後列出所有對白行,點擊 → mpv seek 到該行時間點
- 無影片時預覽區顯示操作提示;mpv 初始化失敗(缺 libmpv)則預覽功能降級停用,不影響批次功能
- 縮放規則與批次一致:暫存 .ass 用該字幕自己的 PlayRes 規則換算數值,所見即所得

## MKV 字幕軌處理

**流程**:
1. `mkvmerge -J <file>` 列舉軌道,過濾出 ASS/SSA 字幕軌(codec `S_TEXT/ASS`/`S_TEXT/SSA`),表格顯示語言/軌名/軌號
2. 預設全勾 ASS 軌;**「一鍵選整季同類型軌」**:以（語言, 軌名）為鍵,把目前檔案勾選狀態套用到所有已掃描 MKV
3. `mkvextract <file> tracks <id>:<temp.ass>` 抽出勾選軌
4. 走既有 `apply_profile`(PlayRes 縮放規則、只改目標 Style、不動標頭,與 v1 完全一致)
5. `mkvmerge -o <out> --subtitle-tracks !<被替換軌ID清單> <orig> [--language 0:.. --track-name 0:.. --default-track 0:.. --forced-track 0:..] <styled1.ass> ...` 重封裝——精確語意:原檔只排除被勾選(要替換)的字幕軌,其餘字幕軌與視訊/音訊/章節/**字型附件**原封保留;改後的 .ass 以附加軌加入,並用 mkvmerge 選項還原原軌的語言/軌名/default/forced 旗標
6. 解析 mkvmerge 的 `Progress: NN%` 輸出更新每檔進度條

**輸出模式**:
- 預設:輸出到新資料夾(原檔不動)
- 「取代原檔」:寫到同目錄暫存檔 → 驗證 mkvmerge 退出碼為 0/1(1=警告)且輸出檔可被 `mkvmerge -J` 重新解析 → 覆蓋原檔;任何一步失敗保留原檔並報錯。不留 .bak(影片檔太大),磁碟只需單集大小的暫存空間

**取消**:批次執行中可按「取消」——當前檔案跑完(或 mkvmerge 程序終止並清理暫存檔)後停止,不產生半成品。

## UX 完善項目

1. **設定持久化**(QSettings):視窗大小、最後資料夾、輸出模式、最後 profile、主題模式
2. **Profile 下拉切換**:列出 `profiles/` 內所有 JSON,一鍵切換;另存/刪除按鈕
3. **進度條 + 取消**:整批進度與當前檔案進度(MKV 模式含 mkvmerge 百分比)
4. **字幕行點擊跳轉**(見預覽)
5. **字型未安裝警告**:QFontDatabase 查不到樣式欄位的字型名稱時,欄位旁顯示黃色警告
6. **全視窗拖放**
7. **完成後「開啟輸出資料夾」按鈕**
8. **主題模式切換**(跟隨系統 / 深色 / 淺色)——見下節

## 主題模式(theme.py)

三種模式,右上角工具列放一個切換控制(下拉或循環按鈕,參考 MKV Muxing Batch GUI 的「Switch To Light Mode」位置):

- **跟隨系統(預設)**:依 Windows 深/淺色設定自動套用;系統設定變更時即時跟隨
- **深色**:強制深色
- **淺色**:強制淺色

**實作**:
- `theme.py` 提供兩份 QSS(深色、淺色)與 `apply_theme(app, mode)`;`mode` 為 `"system" | "dark" | "light"`
- 系統深/淺色偵測用 Qt 6.5+ 的 `QStyleHints.colorScheme()`;監聽 `QStyleHints.colorSchemeChanged` 訊號,在「跟隨系統」模式下即時重套 QSS
- 選擇用 QSettings 持久化(併入第 1 項設定持久化),重開程式沿用上次選擇
- 純函式部分(mode → 該用哪份 QSS 的決策)可單元測試;實際套用與訊號監聽為手動冒煙驗證

## 外部工具偵測(tools.py)

啟動時依序尋找每個工具(ffprobe、mkvmerge、mkvextract、libmpv):
1. 系統 PATH
2. 常見安裝目錄(MKVToolNix:登錄檔 + `C:\Program Files\MKVToolNix`;ffmpeg 常見路徑)
3. 程式自帶 `tools/` 資料夾(安裝程式放置)

找不到 → 對應功能停用,介面顯示缺什麼、如何補(裝系統版或重跑安裝程式勾選元件)。libmpv 由程式目錄直接載入(固定內建)。

## 打包與發佈

1. **PyInstaller(onedir 模式)**打包程式本體(含 PySide6、libmpv DLL)
2. **Inno Setup** 做安裝程式:開始功能表捷徑、解除安裝;ffmpeg 與 MKVToolNix 做成**可勾選元件**,安裝腳本偵測系統是否已裝(PATH/登錄檔)決定預設勾選狀態——已有的人不重複下載
3. 體積預期:程式本體 + libmpv 約 100MB;全勾約 250MB

## 錯誤處理原則

- 延續 v1:單檔失敗不中斷整批,log 記錄原因
- MKV 重封裝失敗:保留原檔,清理暫存,log 記 mkvmerge stderr
- 工具缺失:功能級停用 + 明確指引,不閃退
- mpv 失敗:預覽降級,批次功能不受影響

## 測試策略

- **單元測試(TDD,沿用 pytest)**:`tools.py`(路徑偵測,monkeypatch);`mkv_io.py`(`-J` JSON 解析用真實樣本 fixture、命令列組裝、進度行解析);`preview.py`(暫存 .ass 產生正確性)
- **既有 62 測試**:持續通過,核心模組不動
- **Qt GUI**:手動冒煙清單(視窗、拖放、預覽重載、MKV 勾選、取消、進度)
- **打包**:手動驗證安裝程式在乾淨環境的元件偵測與安裝後功能

## 範圍外(本版不做)

- 字幕時間軸調整/平移(只改樣式)
- 非 ASS/SSA 字幕軌(SRT/PGS)的轉換或改樣式
- macOS/Linux 打包(程式碼不刻意綁 Windows,但只發佈 Windows 安裝程式)
- 自動更新機制
- 多語系介面(僅繁體中文)

## 實作順序(供計畫拆分)

1. `tools.py`(其他模組的地基)
2. `mkv_io.py`(純邏輯,可完整 TDD)
3. `preview.py`
4. Qt GUI 骨架(主視窗/主題/分頁籤)→ 樣式面板 → 檔案表格 → mpv 播放器 → 批次執行整合
5. 打包(PyInstaller spec → Inno Setup 腳本)

規模較大,計畫階段預期拆成 2-3 個獨立實作計畫(核心模組 → GUI → 打包),各自可交付可測試。
