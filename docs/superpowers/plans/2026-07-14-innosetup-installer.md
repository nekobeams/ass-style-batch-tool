# Inno Setup 安裝程式(Plan 3 第二階段)Implementation Plan

> **注意:本計畫兩個 task 都必須在完整的本機環境執行。** 需要與已安裝的 Inno Setup(`ISCC.exe`)、真實 Windows registry/PATH 狀態互動,且 Pascal Script 的正確性已在撰寫本計畫前實際編譯/安裝驗證過(見下方「已驗證的技術細節」)。

**Goal:** 用 Inno Setup 把 `dist/ass_style_tool/`(Plan 3 第一階段的 PyInstaller onedir 產物)包成正式安裝程式,含開始功能表捷徑、解除安裝、ffmpeg/MKVToolNix 可勾選元件(依系統偵測結果決定預設勾選狀態)。

**Architecture:** 新增 `ass_style_tool.iss`(Inno Setup script)。`core` 元件(必要)裝主程式;`ffmpeg`/`mkvtoolnix` 元件(選用)只在對應的 `installer_payload/` 子資料夾存在時才出現在編譯出的安裝程式裡(ISPP 前處理器 `#if DirExists(...)` 編譯期判斷),執行檔複製進安裝目錄的 `tools/` 子資料夾(對應 `bundled_tools_dir()` 的 frozen 路徑),LICENSE 複製進 `licenses/<工具>/`。是否已裝的偵測(決定選用元件預設勾選/不勾選)由 Pascal Script 在精靈的元件選擇頁面時動態設定。

**Tech Stack:** Inno Setup 6(`ISCC.exe` 命令列編譯器,已安裝於 `%LOCALAPPDATA%\Programs\Inno Setup 6\`)、Pascal Script(Inno Setup 內建)、ISPP(Inno Setup Preprocessor,內建)。

**Spec:** `docs/superpowers/specs/2026-07-14-innosetup-installer-design.md`

## 已驗證的技術細節(寫這份計畫前已實際編譯/安裝測試過,非憑空假設)

1. **選用元件依系統偵測動態預設勾選/不勾選**:用 `CurPageChanged(CurPageID)` 事件,在 `CurPageID = wpSelectComponents` 時走訪 `WizardForm.ComponentsList.Items`,用 `ItemCaption[I]` 比對元件描述文字,對命中的項目設 `Checked[I] := False`(或維持預設 `True`)。實測:設 `Checked[I] := False` 後,靜默安裝(`/VERYSILENT`)確實不會複製該元件的檔案;不設則確實會複製——雙向都驗證過。
2. **選用元件在來源資料夾不存在時完全不出現**:用 ISPP 前處理器 `#if DirExists("installer_payload\ffmpeg")` 包住對應的 `[Components]` 與 `[Files]` 行。實測:資料夾不存在且**沒有** `#if` 保護時,`ISCC.exe` 會噴 `Error ... No files found matching "...\installer_payload\ffmpeg\*.exe"` 並中止編譯;包上 `#if` 保護後編譯正常成功、略過該區塊。
3. **命令列旗標務必用 PowerShell 執行,不要用 Git Bash**:Git Bash(MSYS)會把 `/VERYSILENT` 這類單斜線命令列旗標誤判成 POSIX 路徑並亂轉換,導致安裝程式沒吃到靜默旗標、跑成互動精靈模式空等。本計畫所有「執行編譯出的安裝程式」步驟一律用 PowerShell 執行。

## Global Constraints

- 工作目錄/repo root:專案根目錄;直接在 `master` 上做(此計畫兩個 task 都需在本機環境執行;若要遵照專案慣例走分支流程,可先 `git checkout -b feature/innosetup-installer`)
- `ISCC.exe` 路徑:`%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`
- **執行編譯出的安裝程式一律用 PowerShell,不要用 Bash/Git Bash**(見上方已驗證細節 3)
- AppId 固定:`{{A6F1AE07-C85D-4E18-B33C-08AA18A17BF4}`(已產生,寫死進 script,讓重跑安裝程式視為升級而非全新安裝——之後任何版本都不可以再改這個值)
- `installer_payload/ffmpeg/`、`installer_payload/mkvtoolnix/` 由使用者自行放入官方 portable 執行檔 + LICENSE 檔,Claude 不下載/內嵌第三方二進位
- 解除安裝**不刪除** `%APPDATA%\ass-style-tool`
- 測試安裝一律裝到非 Program Files 的暫存路徑(避免留下測試垃圾、避免需要真的 UAC 提升),用 `/DIR=` 指定
- 測試指令(單元測試,不受本計畫影響,僅供回歸確認):`py -m pytest tests -q`(目前基準 **284 passed**,本計畫不改動任何 Python 程式碼,預期維持 284)
- Commit 訊息用 conventional commits(英文)

### 既有介面(本計畫會用到,已實作)

- `dist/ass_style_tool/`:Plan 3 第一階段的 PyInstaller onedir 產物,含 `ass_style_tool.exe` 與所有依賴(已驗證可正常啟動)
- `assets/icon.ico`:已生成的自訂圖示
- `ass_style_tool/tools.py` 的 `bundled_tools_dir()`:frozen 狀態下回傳 `Path(sys.executable).parent / "tools"`——也就是安裝目錄下的 `tools\` 子資料夾,這是選用元件執行檔的目的地
- `.gitignore` 已有 `build/`、`dist/`(PyInstaller 產物)

## File Structure

```
ass_style_tool.iss          # (新)Inno Setup script
installer_payload/          # (新,gitignore)使用者自行放入 ffmpeg/mkvtoolnix portable 執行檔+LICENSE
├── ffmpeg/                 #   使用者放:ffmpeg.exe、ffprobe.exe、LICENSE
└── mkvtoolnix/              #   使用者放:mkvmerge.exe、mkvextract.exe、LICENSE
installer_dist/              # (新,gitignore)ISCC 編譯輸出的安裝程式 .exe
.gitignore                   # (修改)加 installer_payload/、installer_dist/
```

---

### Task 1: 撰寫 `ass_style_tool.iss` + 假檔測試驗證邏輯

**Files:**
- Create: `ass_style_tool.iss`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `dist/ass_style_tool/*`(Plan 3 第一階段產物)、`assets/icon.ico`、`installer_payload/ffmpeg/*`(選用,可不存在)、`installer_payload/mkvtoolnix/*`(選用,可不存在)
- Produces: `installer_dist/ass-style-tool-setup.exe`(編譯出的安裝程式)

- [ ] **Step 1: `.gitignore` 加入新目錄**

在 `.gitignore` 末尾附加:

```
# Inno Setup:使用者自備的第三方二進位來源、編譯輸出
installer_payload/
installer_dist/
```

- [ ] **Step 2: 撰寫 `ass_style_tool.iss`**

在 repo 根目錄建立 `ass_style_tool.iss`:

```ini
; -- ASS 字幕樣式批次工具 Inno Setup Script --
; AppId 一經發佈絕不可再更改(否則使用者升級會被視為全新安裝,留下舊版殘留)

#define MyAppName "ASS 字幕樣式批次工具"
#define MyAppVersion "1.0"
#define MyAppExeName "ass_style_tool.exe"

[Setup]
AppId={{A6F1AE07-C85D-4E18-B33C-08AA18A17BF4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer_dist
OutputBaseFilename=ass-style-tool-setup
SetupIconFile=assets\icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "chinesetraditional"; MessagesFile: "compiler:Languages\ChineseTraditional.isl"

[Types]
Name: "full"; Description: "完整安裝"
Name: "custom"; Description: "自訂安裝"; Flags: iscustom

[Components]
Name: "core"; Description: "主程式(必要)"; Types: full custom; Flags: fixed
#if DirExists("installer_payload\ffmpeg")
Name: "ffmpeg"; Description: "ffmpeg(影片解析度偵測用)"; Types: full custom
#endif
#if DirExists("installer_payload\mkvtoolnix")
Name: "mkvtoolnix"; Description: "MKVToolNix(MKV 字幕封裝/處理用)"; Types: full custom
#endif

[Files]
Source: "dist\ass_style_tool\*"; DestDir: "{app}"; Components: core; Flags: recursesubdirs ignoreversion
#if DirExists("installer_payload\ffmpeg")
Source: "installer_payload\ffmpeg\*.exe"; DestDir: "{app}\tools"; Components: ffmpeg; Flags: ignoreversion
Source: "installer_payload\ffmpeg\LICENSE*"; DestDir: "{app}\licenses\ffmpeg"; Components: ffmpeg; Flags: ignoreversion; DestName: "LICENSE.txt"
#endif
#if DirExists("installer_payload\mkvtoolnix")
Source: "installer_payload\mkvtoolnix\*.exe"; DestDir: "{app}\tools"; Components: mkvtoolnix; Flags: ignoreversion
Source: "installer_payload\mkvtoolnix\LICENSE*"; DestDir: "{app}\licenses\mkvtoolnix"; Components: mkvtoolnix; Flags: ignoreversion; DestName: "LICENSE.txt"
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\解除安裝 {#MyAppName}"; Filename: "{uninstallexe}"

[Code]
function IsToolOnPath(const ExeName: String): Boolean;
var
  PathEnv, Dir: String;
  P: Integer;
begin
  Result := False;
  PathEnv := GetEnv('PATH') + ';';
  while Length(PathEnv) > 0 do
  begin
    P := Pos(';', PathEnv);
    if P = 0 then
      P := Length(PathEnv) + 1;
    Dir := Copy(PathEnv, 1, P - 1);
    PathEnv := Copy(PathEnv, P + 1, Length(PathEnv));
    if (Dir <> '') and FileExists(AddBackslash(Dir) + ExeName) then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function IsMkvToolNixInstalled: Boolean;
begin
  Result := IsToolOnPath('mkvmerge.exe')
    or DirExists(ExpandConstant('{commonpf}\MKVToolNix'))
    or DirExists(ExpandConstant('{commonpf32}\MKVToolNix'));
end;

function IsFfmpegInstalled: Boolean;
begin
  Result := IsToolOnPath('ffmpeg.exe');
end;

procedure UncheckComponentIfDetected(const Caption: String; Detected: Boolean);
var
  I: Integer;
begin
  if not Detected then
    Exit;
  for I := 0 to WizardForm.ComponentsList.Items.Count - 1 do
  begin
    if WizardForm.ComponentsList.ItemCaption[I] = Caption then
      WizardForm.ComponentsList.Checked[I] := False;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpSelectComponents then
  begin
    UncheckComponentIfDetected('ffmpeg(影片解析度偵測用)', IsFfmpegInstalled);
    UncheckComponentIfDetected('MKVToolNix(MKV 字幕封裝/處理用)', IsMkvToolNixInstalled);
  end;
end;
```

**注意 `PrivilegesRequired=lowest`(暫時,非最終值)**:spec 決定正式安裝程式要 `admin`(裝進 Program Files)。但 `admin` 會讓 Windows 在執行安裝程式當下跳出 UAC 提升對話框——這是原生系統對話框,無法用任何命令列靜默旗標繞過,自動化流程沒有辦法互動點擊。所以 Task 1 全程用 `lowest` 编譯測試(邏輯驗證不受權限層級影響,`/DIR=` 覆蓋到 `%TEMP%` 底下用 `lowest` 就能正常靜默安裝);Step 10 commit 前才切回 `admin` 作為最終正式版本,並在計畫最後提醒使用者親自做一次真正的雙擊安裝手動確認(見 Task 1 末尾備註)。

- [ ] **Step 3: 建立假檔測試 payload**

用 PowerShell 建立零位元組假執行檔(模擬使用者尚未放入真實二進位前的測試):

```powershell
New-Item -ItemType Directory -Force -Path ".\installer_payload\ffmpeg" | Out-Null
New-Item -ItemType Directory -Force -Path ".\installer_payload\mkvtoolnix" | Out-Null
New-Item -ItemType File -Force -Path ".\installer_payload\ffmpeg\ffmpeg.exe" | Out-Null
New-Item -ItemType File -Force -Path ".\installer_payload\ffmpeg\ffprobe.exe" | Out-Null
"fake ffmpeg license for testing" | Set-Content ".\installer_payload\ffmpeg\LICENSE"
New-Item -ItemType File -Force -Path ".\installer_payload\mkvtoolnix\mkvmerge.exe" | Out-Null
New-Item -ItemType File -Force -Path ".\installer_payload\mkvtoolnix\mkvextract.exe" | Out-Null
"fake mkvtoolnix license for testing" | Set-Content ".\installer_payload\mkvtoolnix\LICENSE"
```

- [ ] **Step 4: 編譯**

Run: `& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" "ass_style_tool.iss"`
Expected: `Successful compile`,產生 `installer_dist\ass-style-tool-setup.exe`

- [ ] **Step 5: 靜默安裝測試(這台機器已裝 MKVToolNix,沒裝 ffmpeg——驗證預設勾選狀態符合偵測結果)**

用 PowerShell(**不要用 Bash**,見上方已驗證細節 3):

```powershell
$testDir = "$env:TEMP\ass-style-tool-test"
Remove-Item -Path $testDir -Recurse -Force -ErrorAction SilentlyContinue
& ".\installer_dist\ass-style-tool-setup.exe" /VERYSILENT "/DIR=$testDir" "/LOG=$env:TEMP\ass-style-tool-test-install.log" /SUPPRESSMSGBOXES
Start-Sleep -Seconds 3
Get-ChildItem -Path $testDir -Recurse | Select-Object FullName
```

Expected:
- `$testDir\ass_style_tool.exe` 存在(core 元件一定裝)
- `$testDir\tools\mkvmerge.exe`、`$testDir\tools\mkvextract.exe` **不存在**(這台機器系統已裝 MKVToolNix,偵測到後預設不勾選)
- `$testDir\tools\ffmpeg.exe`、`$testDir\tools\ffprobe.exe` **存在**(這台機器沒裝 ffmpeg,預設勾選)
- `$testDir\licenses\ffmpeg\LICENSE.txt` 存在;`$testDir\licenses\mkvtoolnix\` 不存在(因為 mkvtoolnix 元件被跳過,連 LICENSE 都不會裝——這是預期行為,元件跳過等於該元件底下所有檔案都不裝)

若结果與預期不符,檢查 `$env:TEMP\ass-style-tool-test-install.log` 找出實際勾選狀態,回 Step 2 調整 Pascal Script。

- [ ] **Step 6: 用 `/COMPONENTS=` 明確覆蓋測試兩種路徑都正確**

```powershell
$testDir2 = "$env:TEMP\ass-style-tool-test-all"
Remove-Item -Path $testDir2 -Recurse -Force -ErrorAction SilentlyContinue
& ".\installer_dist\ass-style-tool-setup.exe" /VERYSILENT "/DIR=$testDir2" "/COMPONENTS=core,ffmpeg,mkvtoolnix" /SUPPRESSMSGBOXES
Start-Sleep -Seconds 3
Get-ChildItem -Path $testDir2 -Recurse -Filter "*.exe" | Select-Object Name
```

Expected:`ass_style_tool.exe`、`tools\ffmpeg.exe`、`tools\ffprobe.exe`、`tools\mkvmerge.exe`、`tools\mkvextract.exe` 全部存在(明確用 `/COMPONENTS=` 指定全裝時,不受預設勾選邏輯影響,全部確實裝得進去)。

- [ ] **Step 7: 解除安裝測試,確認不動 `%APPDATA%\ass-style-tool`**

```powershell
# 先確認測試機的 %APPDATA%\ass-style-tool 現狀(可能已存在,來自先前手動測試)
$appdataMarker = Test-Path "$env:APPDATA\ass-style-tool"
Write-Output "APPDATA marker exists before uninstall: $appdataMarker"

& "$testDir\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES
Start-Sleep -Seconds 3
Write-Output "install dir exists after uninstall: $(Test-Path $testDir)"
Write-Output "APPDATA still exists after uninstall: $(Test-Path "$env:APPDATA\ass-style-tool")"
```

Expected:安裝目錄的檔案被移除(`unins000.exe` 自身會留到下一輪清理,這是 Inno Setup 標準行為);`%APPDATA%\ass-style-tool` 存在與否**不受解除安裝影響**(若安裝前存在,解除安裝後應仍存在)。

- [ ] **Step 8: 清理測試殘留**

```powershell
Remove-Item -Path "$env:TEMP\ass-style-tool-test" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path "$env:TEMP\ass-style-tool-test-all" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path "$env:TEMP\ass-style-tool-test-install.log" -Force -ErrorAction SilentlyContinue
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{A6F1AE07-C85D-4E18-B33C-08AA18A17BF4}_is1"
if (Test-Path $uninstallKey) { Remove-Item -Path $uninstallKey -Recurse -Force }
```

同時刪除假 payload(下個 task 前使用者要放真實二進位進同一批資料夾,先清空):

```powershell
Remove-Item -Path ".\installer_payload" -Recurse -Force
```

- [ ] **Step 9: 全套單元測試確認無回歸(本計畫未改動 Python 程式碼,純確認基準未變動)**

Run: `py -m pytest tests -q`(從專案根目錄)
Expected: `284 passed`(與本計畫開始前相同——這個 task 完全沒有碰任何 Python 檔案)

- [ ] **Step 10: 切回正式的 `PrivilegesRequired=admin`**

自動化驗證都跑完了,把 `ass_style_tool.iss` 的 `[Setup]` 段落:

```ini
PrivilegesRequired=lowest
```

改回:

```ini
PrivilegesRequired=admin
```

**這一步之後不要再自動編譯/靜默安裝測試**(會卡在 UAC 對話框)。改用 Step 11 只做編譯確認語法沒錯,不執行安裝。

- [ ] **Step 11: 最終編譯確認(只編譯,不安裝)**

Run: `& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" "ass_style_tool.iss"`
Expected: `Successful compile`(改回 `admin` 純粹是 manifest 旗標,不影響編譯本身能不能過)

- [ ] **Step 12: Commit**

```powershell
cd <repo-root>
git add ass_style_tool.iss .gitignore
git commit -m "build: add Inno Setup installer script with detected-component defaults"
```

- [ ] **Step 13: 交給使用者的手動驗證(Claude 無法自行完成)**

雙擊 `installer_dist\ass-style-tool-setup.exe`(不加任何命令列參數),確認:
1. 出現 UAC 提升對話框,同意後精靈正常出現
2. 元件選擇頁面:MKVToolNix(這台機器系統已裝)預設**沒勾**;ffmpeg(這台機器沒裝)預設**有勾**
3. 走完安裝精靈,開始功能表出現捷徑,雙擊能開啟程式
4. 從開始功能表或控制台解除安裝,確認乾淨移除(且 `%APPDATA%\ass-style-tool` 沒被動到)

---

### Task 2: 真實二進位驗證(等使用者放入 ffmpeg/MKVToolNix 檔案後執行)

**這個 task 依賴使用者的外部動作(放入真實檔案),在使用者完成前無法開始。**

**Files:**
- 無程式碼改動,純驗證

**Interfaces:**
- Consumes: Task 1 的 `ass_style_tool.iss`;使用者放入的 `installer_payload/ffmpeg/*`、`installer_payload/mkvtoolnix/*` 真實二進位 + LICENSE

- [ ] **Step 1: 確認使用者已放入真實檔案**

```powershell
Get-ChildItem ".\installer_payload\ffmpeg" -ErrorAction SilentlyContinue
Get-ChildItem ".\installer_payload\mkvtoolnix" -ErrorAction SilentlyContinue
```

若任一資料夾不存在或是空的,停下來提醒使用者先放檔案,不要用假檔硬跑這個 task(Task 1 的假檔測試已經證明邏輯正確,這個 task 的目的是驗證真實二進位能不能正常運作,不是重複邏輯測試)。

- [ ] **Step 2: 暫時切回 `PrivilegesRequired=lowest` 才能自動化測試**

Task 1 Step 10 已把 `ass_style_tool.iss` 切回正式的 `PrivilegesRequired=admin`。跟 Task 1 一樣的原因(UAC 對話框無法自動化互動),這裡先暫時改回:

```ini
PrivilegesRequired=lowest
```

編譯測試完(本 task Step 2-6)結束後,**再切回 `admin` 並重新編譯一次**,但不要重新跑自動化安裝(直接進 Step 7)。

- [ ] **Step 3: 編譯(lowest 測試版)**

Run: `& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" "ass_style_tool.iss"`
Expected: `Successful compile`

- [ ] **Step 4: 安裝到測試目錄,啟動程式,確認工具可用**

```powershell
$testDir = "$env:TEMP\ass-style-tool-realcheck"
Remove-Item -Path $testDir -Recurse -Force -ErrorAction SilentlyContinue
& ".\installer_dist\ass-style-tool-setup.exe" /VERYSILENT "/DIR=$testDir" /SUPPRESSMSGBOXES
Start-Sleep -Seconds 3
$p = Start-Process -FilePath "$testDir\ass_style_tool.exe" -PassThru
Start-Sleep -Seconds 5
if ($p.HasExited) { Write-Output "FAIL exit=$($p.ExitCode)" } else { Write-Output "OK pid=$($p.Id)" }
```

- [ ] **Step 5: 用 UI Automation 確認 MKV/封裝分頁不再顯示「找不到 mkvmerge」**

（比照先前 Plan 3 第一階段驗證用過的非視覺 UI Automation 讀取控制項文字方式,不截圖)

Expected:分頁正常,若這台機器本來就系統裝有 MKVToolNix(預設不勾選、不裝進 `tools\`),則工具偵測仍走系統 PATH 那條路,程式本身照樣可用——這個測試主要是確認「勾選了選用元件、tools\ 資料夾有真實可執行檔」本身不會導致程式啟動失敗或路徑衝突。

- [ ] **Step 6: 關閉程式、解除安裝、清理**

```powershell
$p | Stop-Process -Force -ErrorAction SilentlyContinue
& "$testDir\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES
Start-Sleep -Seconds 2
Remove-Item -Path $testDir -Recurse -Force -ErrorAction SilentlyContinue
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{A6F1AE07-C85D-4E18-B33C-08AA18A17BF4}_is1"
if (Test-Path $uninstallKey) { Remove-Item -Path $uninstallKey -Recurse -Force }
```

- [ ] **Step 7: 切回正式的 `PrivilegesRequired=admin`,最終編譯確認**

把 `ass_style_tool.iss` 的 `PrivilegesRequired=lowest` 改回 `PrivilegesRequired=admin`。

Run: `& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" "ass_style_tool.iss"`
Expected: `Successful compile`(**不要**再自動靜默安裝——會卡 UAC)

- [ ] **Step 8: 全套單元測試複驗**

Run: `py -m pytest tests -q`
Expected: `284 passed`

- [ ] **Step 9: 交給使用者的最終手動驗證(Claude 無法自行完成)**

重複 Task 1 Step 13 的完整手動驗證清單,但這次用**真實的 ffmpeg/MKVToolNix 二進位**:雙擊 `installer_dist\ass-style-tool-setup.exe`,走完 UAC 提升 + 安裝精靈,確認選用元件裝進去的是真的能執行的 ffmpeg/mkvmerge(不是零位元組假檔),程式各分頁功能正常,解除安裝乾淨。

- [ ] **Step 10: Commit(若 `.iss` 因偵測邏輯調整而有變動才需要;若跟 Task 1 commit 後完全相同則跳過)**

```powershell
cd <repo-root>
git status --short ass_style_tool.iss
```

若有變動:

```powershell
git add ass_style_tool.iss
git commit -m "build: adjust Inno Setup script after real-binary verification"
```

---

## 本計畫完成後

Plan 3(打包)全部完成:PyInstaller onedir 打包 + Inno Setup 安裝程式(含 ffmpeg/MKVToolNix 可勾選元件、偵測預設勾選、開始功能表捷徑、解除安裝)。專案主要功能開發告一段落。
