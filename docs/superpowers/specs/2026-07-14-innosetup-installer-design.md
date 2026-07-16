# Inno Setup 安裝程式(Plan 3 第二階段)Design

**背景**:Plan 3 第一階段(PyInstaller onedir 打包)已完成並合併。spec v2 設計文件的「打包發佈」節規劃的第二塊——用 Inno Setup 把 `dist/ass_style_tool/` 包成正式安裝程式,含開始功能表捷徑、解除安裝,以及 ffmpeg/MKVToolNix 的可勾選元件(偵測系統已裝與否決定預設勾選)。

## 需求(使用者確認)

1. **外部二進位來源**:ffmpeg 與 MKVToolNix 的可勾選元件二進位檔**由使用者自行準備**(從官方管道下載 portable build),Claude 不負責下載/內嵌第三方執行檔。
2. **二進位放置位置**:repo 內新增 `installer_payload/ffmpeg/`、`installer_payload/mkvtoolnix/`(gitignore,不進版控),使用者把 portable exe + 官方 LICENSE 檔放進去;Inno Setup script 在這些資料夾存在時才把對應元件收錄進安裝程式。
3. **安裝位置**:`Program Files`(需要系統管理員權限提升,Inno Setup 預設 `PrivilegesRequired=admin`)。
4. **偵測邏輯**:Inno Setup Pascal Script **重新實作**(不與 `tools.py` 共用程式碼,語言不同無法共用)——概念上比照:PATH 查得到 `mkvmerge.exe`/`ffmpeg.exe` 即視為已裝;MKVToolNix 額外查常見安裝目錄(`C:\Program Files\MKVToolNix`、`C:\Program Files (x86)\MKVToolNix`);ffmpeg 沒有標準安裝目錄慣例,只查 PATH。偵測到 → 對應 Component 預設**不勾選**(避免重複下載);沒偵測到 → 預設**勾選**。
5. **第三方授權文字**:隨附官方 LICENSE 檔(使用者準備二進位時一併放入 `installer_payload/<工具>/LICENSE` 之類的檔案),安裝時複製進安裝目錄下的 `licenses/<工具>/` 子資料夾。
6. **驗證方式**:先用零位元組假 exe 測試 script 本身的邏輯(Components 勾選狀態、檔案複製路徑、偵測分支);待使用者放入真實二進位後,重新 build 一次驗證真實行為。**此任務由控制器親自執行**(比照 Plan 3 第一階段的 PyInstaller 打包任務),不外包 subagent——需要與已安裝的 Inno Setup、真實系統 registry/PATH 狀態互動,且涉及疊代除錯 Pascal Script。

## 架構

新增 `ass_style_tool.iss`(repo 根目錄,與 `ass_style_tool.spec` 同層,同樣的「手刻設定檔」定位):

- **`[Setup]`**:固定 `AppId`(GUID,讓重跑安裝程式視為升級而非全新安裝)、`DefaultDirName={autopf}\ASS 字幕樣式批次工具`、`PrivilegesRequired=admin`、輸出檔名 `ass-style-tool-setup.exe`、圖示引用 `assets/icon.ico`
- **`[Components]`**:
  - `core`(必要,`Types: fixed`):主程式本體,來源 `dist\ass_style_tool\*`
  - `ffmpeg`(選用):來源 `installer_payload\ffmpeg\*`,只在 `installer_payload\ffmpeg` 資料夾存在時才在 `[Components]` 段落出現(用 `Check:` 搭配一個「資料夾是否存在」的輔助函式,在 script 編譯/執行期判斷;若資料夾不存在,此 Component 完全不顯示,避免使用者看到勾了也沒東西裝的選項)
  - `mkvtoolnix`(選用):同上,來源 `installer_payload\mkvtoolnix\*`
- **`[Files]`**:`core` 元件的檔案目的地是安裝目錄根;`ffmpeg`/`mkvtoolnix` 元件的執行檔目的地是安裝目錄下的 `tools\` 子資料夾(對應 `ass_style_tool/tools.py` 的 `bundled_tools_dir()` 在 frozen 狀態下預期的 `<exe 所在目錄>\tools\`);兩者的 LICENSE 檔目的地是 `licenses\ffmpeg\`/`licenses\mkvtoolnix\`
- **`[Icons]`**:開始功能表捷徑(指向 `ass_style_tool.exe`)+解除安裝捷徑
- **`[UninstallDelete]`**:不刪除 `%APPDATA%\ass-style-tool`(保留使用者 profile 與設定,解除安裝只移除安裝的程式檔案)
- **`[Code]`**(Pascal Script):
  - `IsToolOnPath(exeName: String): Boolean`——split `GetEnvironmentVariable('PATH')` 依 `;`,對每段查 `FileExists(dir + '\' + exeName)`
  - `IsMkvToolNixInstalled: Boolean`——`IsToolOnPath('mkvmerge.exe')` 或常見安裝目錄存在 `mkvmerge.exe`
  - `IsFfmpegInstalled: Boolean`——`IsToolOnPath('ffmpeg.exe')`
  - `InitializeWizard`(或用 `[Components]` 的 `Check:` 參數)於精靈初始化時根據上述偵測結果設定對應 Component 的預設勾選狀態

## 測試計畫

- **Script 邏輯(假檔測試)**:在 `installer_payload/ffmpeg/`、`installer_payload/mkvtoolnix/` 放零位元組的假 `.exe`(檔名相符,如 `ffmpeg.exe`、`mkvmerge.exe`)+ 假 `LICENSE` 文字檔,執行 `iscc ass_style_tool.iss` 編譯,靜默安裝到一個測試專用資料夾(非真正 Program Files,如 `/DIR="C:\temp\ass-style-tool-test" /VERYSILENT`),檢查:
  - 安裝目錄結構正確(`ass_style_tool.exe`、`tools\ffmpeg.exe`、`tools\mkvmerge.exe`、`licenses\ffmpeg\LICENSE`、`licenses\mkvtoolnix\LICENSE`)
  - 兩個偵測函式在「系統已裝 MKVToolNix」(這台開發機真的有裝)的情況下,`mkvtoolnix` Component 預設**不勾選**;`ffmpeg`(這台機器沒裝)預設**勾選**——用 `/COMPONENTS=` 命令列參數搭配靜默安裝分別測試勾選/不勾選兩種路徑的檔案複製結果
  - 解除安裝後安裝目錄清空,但 `%APPDATA%\ass-style-tool` 不受影響
- **真實二進位驗證**(使用者放入真實檔案後):重新 build,人工確認 MKV/封裝分頁的「找不到 mkvmerge」提示消失、實際能執行 mkvmerge/ffmpeg

## 範圍外

- ffmpeg/MKVToolNix 二進位本身的取得/授權確認——使用者自行負責
- 程式簽章(code signing)
- 自動更新機制
- 桌面捷徑(只做開始功能表)
- MKVToolNix/ffmpeg 版本升級偵測(只判斷「有沒有裝」,不判斷版本是否過舊)
