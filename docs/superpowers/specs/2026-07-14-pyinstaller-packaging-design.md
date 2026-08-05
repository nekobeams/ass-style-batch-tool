# PyInstaller 打包(Plan 3 第一階段)Design

**背景**:spec v2 設計文件的「打包發佈」節規劃 PyInstaller + Inno Setup。這份 design 只涵蓋**第一階段:PyInstaller onedir 打包**——做到「能把程式打包成一個可執行資料夾,雙擊 exe 正常啟動、各分頁功能正常」。Inno Setup 安裝程式(含 ffmpeg/MKVToolNix 可勾選元件、開始功能表捷徑)留給下一份獨立的 spec/plan,不在本次範圍內。

## 需求(使用者確認)

1. **範圍**:只做到 PyInstaller onedir 打包 + 啟動驗證,不含 Inno Setup 安裝程式(Inno Setup 目前未安裝於開發環境,且屬於獨立的下一階段工作)。
2. **profile 儲存位置**:從 `Path.cwd() / "profiles"` 改成 `%APPDATA%\ass-style-tool\profiles\`——不論安裝在哪裡都有寫入權限,不需要系統管理員權限。
3. **首次執行自動搬移舊 profile**:若 `%APPDATA%\ass-style-tool\profiles\` 是空的(代表尚未搬移過),且舊位置 `Path.cwd() / "profiles"` 有 `*.json` 檔案,自動複製過去(保留舊檔案,不刪除,避免資料遺失風險)。這主要照顧開發機上既有的使用者資料;全新安裝的機器上 `Path.cwd()/profiles` 通常不存在,此步驟自然是no-op。
4. **驗收方式**:在本機實際執行 `pyinstaller` 打包指令、啟動打包出來的 exe、逐分頁手動驗證。打包產物依賴完整的本機環境(libmpv DLL、PySide6 hook 等),隔離環境不保證一致,不適合在那裡驗證這一步。
5. **圖示**:自訂圖示,已生成放在 `assets/icon.ico`(深色圓角方塊 + 兩條字幕行橫條的簡單圖示,7 種尺寸 16~256px)。

## 改動點

### 1. `ass_style_tool/tools.py` — `bundled_tools_dir()`

目前:

```python
def bundled_tools_dir() -> Path:
    """安裝程式會把工具放在套件旁的 tools/ 目錄(不保證存在)。"""
    return Path(__file__).parent / "tools"
```

問題:PyInstaller onedir 打包後,`__file__` 指向的是打包內部的模組位置,不是使用者看到的 `dist/ass_style_tool/` 資料夾——這個路徑在打包後找不到使用者期望的 `tools/` 資料夾(應該跟 `ass_style_tool.exe` 同層)。

改成依 `sys.frozen` 判斷:

```python
import sys

def bundled_tools_dir() -> Path:
    """安裝程式會把工具放在套件旁的 tools/ 目錄(不保證存在)。
    打包後(sys.frozen)以執行檔所在目錄為準;開發模式維持原本相對於原始碼的位置。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "tools"
    return Path(__file__).parent / "tools"
```

`sys.frozen` 是 PyInstaller 打包後執行時會自動設定的屬性,開發模式下不存在(`getattr(..., False)` 安全處理)。

### 2. `ass_style_tool/qt/style_editor.py` — `profiles_dir()` + 首次搬移

目前:

```python
def profiles_dir(self) -> Path:
    return Path.cwd() / "profiles"
```

改成:

```python
import os

def profiles_dir(self) -> Path:
    return Path(os.environ["APPDATA"]) / "ass-style-tool" / "profiles"
```

新增一次性搬移函式(獨立函式,不綁在 `StyleEditor` 上,方便單元測試):

```python
def migrate_legacy_profiles(legacy_dir: Path, target_dir: Path) -> int:
    """若 target_dir 是空的(或不存在)且 legacy_dir 有 *.json,搬過去(複製,不刪原檔)。
    回傳搬移的檔案數。"""
    if target_dir.is_dir() and any(target_dir.glob("*.json")):
        return 0  # 已經有資料,不重複搬
    if not legacy_dir.is_dir():
        return 0
    legacy_files = list(legacy_dir.glob("*.json"))
    if not legacy_files:
        return 0
    target_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for f in legacy_files:
        shutil.copy2(f, target_dir / f.name)
        count += 1
    return count
```

`StyleEditor.__init__` 建構時(`_refresh_profile_list()` 呼叫之前)呼叫一次:

```python
migrate_legacy_profiles(Path.cwd() / "profiles", self.profiles_dir())
```

### 3. `requirements.txt` — 移除死依賴

```diff
 pysubs2>=1.6
 charset-normalizer>=3.0
-tkinterdnd2>=0.3
 pytest>=7.0
 PySide6>=6.6
```

`tkinterdnd2` 是 v1 tkinter GUI(`gui.py`,已刪除)的依賴,Qt 版從未用到。移除減少打包體積與潛在相容性問題(v2 final review 時已被列為「ACCEPT(N6)」的技術債,這次一併清掉)。

### 4. 新增 `ass_style_tool.spec`(repo 根目錄)

PyInstaller onedir spec 檔,手刻(而非純命令列參數),原因:需要精確控制哪些資料被打包、排除 `ass_style_tool/tools/`(那是使用者自己放外部工具的地方,不該打進安裝包)、指定自訂圖示。確切的 `hiddenimports`/`datas` 內容(PySide6 常有 PyInstaller hook 抓不全的動態載入模組,libmpv DLL 綁定方式待實測)留給 plan 階段實作時依實際打包結果疊代調整——這是實作細節,不是本次 design 要拍板的架構決策。

已知必要項目:
- `console=False`(GUI 程式,不開終端機視窗)
- `icon="assets/icon.ico"`
- 排除 `ass_style_tool/tools/`(即使該目錄存在於開發機,也不該被打包——它是執行期使用者自建的資料夾)
- libmpv DLL:需要作為 binary data 打包進去,讓 `python-mpv` 在 frozen 狀態下找得到(目前裝在 site-packages,打包後那個路徑消失了)——**這是打包階段最大的技術風險點**,需要在 plan 撰寫/執行時實際測試 `import mpv` 在 frozen exe 裡的 DLL 搜尋行為,找出正確的 `binaries=[...]` 寫法或執行期 `os.add_dll_directory` 呼叫。

## 打包產物結構

```
dist/ass_style_tool/
├── ass_style_tool.exe
├── (PySide6/Python runtime DLLs...)
├── libmpv-2.dll              # 打包進去,固定內建(既有決策)
└── tools/                     # 空資料夾,使用者/未來 Inno Setup 階段負責填入
    # (mkvmerge.exe / mkvextract.exe / ffprobe.exe 由使用者自行放入,
    #  或未來 Inno Setup 安裝程式的可勾選元件負責)
```

`%APPDATA%\ass-style-tool\profiles\` 不在打包產物內,是執行期才建立的使用者資料目錄。

## 驗收流程(本機手動執行)

1. `py -m pip install pyinstaller`(開發環境安裝,不進 `requirements.txt`——只有開發打包時需要,不是程式執行期依賴)
2. `py -m PyInstaller ass_style_tool.spec` 於 repo 根目錄執行
3. 確認 `dist/ass_style_tool/ass_style_tool.exe` 產生
4. 啟動 `dist/ass_style_tool/ass_style_tool.exe`(不透過 `py -m`,直接執行打包出來的 exe)
5. 逐項確認:
   - 視窗正常開啟,4 個分頁(字幕檔/MKV/封裝/樣式與預覽)都在
   - 樣式與預覽分頁:mpv 播放器有載入(不是「缺 libmpv」的降級提示)
   - 找不到 mkvmerge 時,MKV/封裝分頁應顯示停用提示(因為 `tools/` 資料夾預期是空的,這是預期行為,不是 bug)
   - 設定持久化仍正常運作(選個資料夾、關閉、重開,確認路徑還原)
   - 檢查 `%APPDATA%\ass-style-tool\profiles\` 是否正確建立且能存讀 profile
6. 若啟動失敗或功能缺漏,依實際錯誤訊息疊代調整 `.spec` 檔(常見:漏收 hiddenimport、DLL 路徑問題),重複步驟 2-5 直到通過

## 測試計畫(自動化的部分)

- `tools.py` 的 `bundled_tools_dir()`:monkeypatch `sys.frozen`/`sys.executable` 兩種情境各一個測試,確認回傳路徑正確切換
- `style_editor.py` 的 `profiles_dir()`:改回傳 `%APPDATA%` 路徑後,monkeypatch `os.environ["APPDATA"]` 驗證組合出的路徑正確
- `migrate_legacy_profiles()`:純函式,好測——(a) target 已有檔案時不搬、(b) legacy 沒有檔案時不搬、(c) legacy 有檔案且 target 是空的時正確複製且不刪原檔、(d) legacy 目錄不存在時不拋例外
- 實際打包/啟動驗證(上一節)不寫自動化測試——PyInstaller build 產物依賴本機環境,不適合 CI/pytest 化,改為手動驗證

## 範圍外(留給下一份 spec/plan)

- Inno Setup 安裝程式、開始功能表捷徑、解除安裝
- ffmpeg/MKVToolNix 可勾選元件(偵測系統已裝與否決定預設勾選狀態)
- onefile 模式(本次固定用 onedir)
- 程式簽章(code signing)
- 自動更新機制
