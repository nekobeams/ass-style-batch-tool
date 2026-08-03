**[English](README.en.md)** | 繁體中文

# ASS 字幕樣式批次工具

批次修改整季動畫字幕的樣式,不必逐檔手動改,也不必碰不該碰的東西。

## 這個工具解決什麼問題

收下來的一季字幕,常常來自不同壓製組,解析度、樣式設定都不一致——同一句「一般對話」在這集是 48px,下一集因為片源是 1080p 而不是 720p,看起來就變小了。手動一集一集開 Aegisub 改,很累而且容易漏。

這個工具做三件事:

1. **依片源解析度自動換算**——每個字幕檔按照自己的 PlayResX/PlayResY 換算數值,讓不同解析度片源的視覺大小維持一致,不是全部套用同一組死數字。
2. **只改你指定的樣式**——精準命中要改的 Style(例如 `Default`),OP/ED/特效/標示等其他樣式完全不受影響,也不會動到 PlayResX/PlayResY/ScaledBorderAndShadow 這些標頭。
3. **檔名不必對得上**——依集數編號配對字幕與影片,不同壓製組的命名習慣(`[VCB-Studio]`、`[LoliHouse]`、`[DBD-Raws]` 等)都認得。

## 功能總覽(四個分頁)

- **字幕檔**——批次套用樣式,或縮放字級。掃描資料夾後即時預覽每一集會被改成什麼(套用前預告、套用後結果),再按下去真正執行。
- **MKV**——直接修改封裝進 MKV 容器裡的字幕軌,不必自己先用 mkvextract 抽出來、改完再用 mkvmerge 封回去。
- **封裝**——把外部字幕檔(可選是否先套用樣式)封裝進對應的 MKV。
- **樣式與預覽**——內嵌 mpv,像 Subtitle Edit 一樣點字幕行就跳轉播放位置,即時看到樣式改完的實際效果。

樣式清單是**掃描出來的**,不是要你自己去別的軟體查了再手動打進來——選好資料夾,工具會告訴你這批檔案裡實際有哪些樣式名稱可以選。

## 下載與安裝

**一般使用者**:到 [Releases](../../releases) 下載安裝程式,執行安裝精靈即可。安裝程式會自動偵測系統上是否已有 ffmpeg/MKVToolNix,只在缺少時才提供安裝選項,libmpv(播放預覽用)固定內建。

**從原始碼執行**:

```powershell
py -m pip install -r requirements.txt
py -m ass_style_tool
```

需要 Python 3.9+。**Windows 上請用 `py`,不要用 `python`**——多數 Windows 安裝環境的 `python` 指令是個什麼都不做的商店存根(exit code 49),`py` 才是真正的 launcher。

MKV/封裝分頁需要 [MKVToolNix](https://mkvtoolnix.download/)(`mkvmerge`/`mkvextract` 在 PATH 中);影片解析度偵測需要 `ffprobe`(在 PATH 中,選配,缺少時只影響長寬比警告,不影響樣式套用本身);內嵌預覽需要 `libmpv-2.dll`,從原始碼執行時要自行取得對應 Windows 版本並放進 Python 的 `site-packages`(與 `mpv.py` 同層)。

## 快速上手

1. 選擇(或拖放)放字幕/影片的資料夾——選好就自動掃描,不必再按一次掃描鈕。
2. 側欄勾選要改的目標樣式(找不到樣式名稱?先確認資料夾選對了)。
3. 選擇輸出模式:原地覆蓋(自動備份)或輸出到新資料夾。
4. 表格裡每一列會先顯示「預計」會被改成什麼,不滿意就回頭調整樣式設定。
5. 按執行,log 會即時顯示每檔結果與總結。

樣式設定可以在「樣式與預覽」分頁編輯字型、大小、顏色、外框、陰影、位置,並存成設定檔重複使用(參考 `profiles/sample-1080p.json`)。

## 縮放規則

樣式數值以設定檔的「基準解析度」為基準;每個字幕檔依自己的 PlayResX/PlayResY 按比例換算(缺一個依 4:3 推導、全缺依規範用 384×288)。工具**不會**改寫 PlayResX/PlayResY/ScaledBorderAndShadow 標頭,也不會動到未列在目標樣式清單中的其他樣式。

## 開發

```powershell
py -m pytest tests -q
```

設計文件與各功能的實作計畫在 `docs/superpowers/specs/` 與 `docs/superpowers/plans/`。

## 授權

[GPLv3](LICENSE)。本程式使用 [libmpv](https://github.com/mpv-player/mpv)(GPLv2 或更新版本),安裝程式隨附其授權全文,見 `installer_payload/libmpv/README.txt` 的來源說明。
