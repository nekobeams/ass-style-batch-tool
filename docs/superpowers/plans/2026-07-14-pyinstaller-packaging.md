# PyInstaller 打包(Plan 3 第一階段)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **注意:Task 3 是控制器親自執行的任務,不外包 subagent。** PyInstaller 打包產物依賴完整本機環境(libmpv DLL、PySide6 hook),subagent 環境不保證一致。Task 1、2 是一般 TDD subagent 任務。

**Goal:** 把程式改造成可用 PyInstaller onedir 打包成一個雙擊即啟動、功能正常的可執行資料夾。

**Architecture:** 兩處程式碼改造(工具目錄偵測 frozen-aware、profile 儲存改用 %APPDATA% 並首次自動搬移舊資料),外加一個手刻的 PyInstaller `.spec` 檔;打包/啟動驗證由控制器手動執行並依實際結果疊代 `.spec`。

**Tech Stack:** PyInstaller(onedir)、PySide6、python-mpv/libmpv、pytest。

**Spec:** `docs/superpowers/specs/2026-07-14-pyinstaller-packaging-design.md`

## Global Constraints

- 工作目錄/repo root:`C:\Claude_code`;git branch 由執行者依 subagent-driven 流程建立(從 master HEAD 分出)
- **環境重點**:`python` 是壞的 Windows Store stub,一律用 `py`:`py -m pytest tests -v`;打包用 `py -m PyInstaller`
- Python 3.9+ 相容;各檔案已有 `from __future__ import annotations`
- **測試絕不污染真實使用者環境**:profile 改用 `%APPDATA%` 後,測試必須用 conftest autouse fixture 把 `APPDATA` 重導到 tmp,絕不寫入真實 `%APPDATA%`(比照先前 QSettings 用 IniFormat tmp 檔避免污染 registry 的做法)
- profile 儲存位置:`%APPDATA%\ass-style-tool\profiles\`(不是 `Path.cwd()/profiles`)
- 首次搬移舊 profile:**複製不刪除**(保留舊檔避免資料遺失);target 已有 `*.json` 時不搬
- 打包 onedir(非 onefile);`console=False`;`icon="assets/icon.ico"`;排除 `ass_style_tool/tools/`
- PyInstaller **不進** `requirements.txt`(只有開發打包時需要,非執行期依賴)
- 測試指令:`py -m pytest tests -q`(從 repo root;目前基準 **276 passed**)
- Commit 訊息用 conventional commits(英文)

### 既有介面(本計畫會用到,已實作)

- `ass_style_tool/tools.py`:`bundled_tools_dir() -> Path`(現為 `Path(__file__).parent / "tools"`);`mkvmerge_path()`/`mkvextract_path()`/`ffprobe_path()` 都用到它
- `ass_style_tool/qt/style_editor.py`:`StyleEditor`,建構子尾端 `self.set_values(DEFAULT_VALUES)` 之後接 `self._refresh_profile_list()`;`profiles_dir(self) -> Path`(現為 `Path.cwd() / "profiles"`);`_refresh_profile_list()` 讀 `profiles_dir()` 內 `*.json`
- `assets/icon.ico`:已生成的自訂圖示(7 尺寸 16~256px)
- `tests/conftest.py`:既有 offscreen `qapp` fixture 與 autouse widget 清理 fixture

## File Structure

```
ass_style_tool/
├── tools.py              # (修改)bundled_tools_dir() 改 frozen-aware
└── qt/style_editor.py    # (修改)profiles_dir() 改 %APPDATA%;新增 migrate_legacy_profiles();__init__ 呼叫(guarded)
tests/
├── conftest.py           # (修改)新增 autouse fixture 把 APPDATA 重導到 tmp
├── test_tools.py         # (修改)附加 bundled_tools_dir frozen/dev 測試
└── test_style_editor.py  # (修改)附加 profiles_dir / migrate 測試
requirements.txt          # (修改)移除 tkinterdnd2
ass_style_tool.spec       # (新)PyInstaller onedir spec 檔
```

---

### Task 1: tools.py — bundled_tools_dir() frozen-aware

**Files:**
- Modify: `ass_style_tool/tools.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: 無(標準庫 `sys`)
- Produces: `bundled_tools_dir() -> Path`——打包後(`sys.frozen` 為真)回 `Path(sys.executable).parent / "tools"`;開發模式回 `Path(__file__).parent / "tools"`(不變)

- [ ] **Step 1: 附加失敗測試**

在 `tests/test_tools.py` 頂端 import 區把:

```python
from pathlib import Path
```

改成:

```python
import sys
from pathlib import Path
```

在檔案末尾附加:

```python


# ---------- bundled_tools_dir frozen 感知 ----------

def test_bundled_tools_dir_dev_mode(monkeypatch):
    import ass_style_tool.tools as tools_mod
    monkeypatch.delattr(sys, "frozen", raising=False)
    expected = Path(tools_mod.__file__).parent / "tools"
    assert tools_mod.bundled_tools_dir() == expected


def test_bundled_tools_dir_frozen(monkeypatch, tmp_path):
    import ass_style_tool.tools as tools_mod
    fake_exe = tmp_path / "ass_style_tool.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    assert tools_mod.bundled_tools_dir() == tmp_path / "tools"
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_tools.py -v -k bundled_tools_dir`
Expected: FAIL — `test_bundled_tools_dir_frozen` 失敗(目前實作忽略 `sys.frozen`,回傳的是原始碼旁的 tools 目錄,不是 `tmp_path / "tools"`)

- [ ] **Step 3: 實作**

在 `ass_style_tool/tools.py` 頂端 import 區把:

```python
import shutil
```

改成:

```python
import shutil
import sys
```

把 `bundled_tools_dir` 函式:

```python
def bundled_tools_dir() -> Path:
    """安裝程式會把工具放在套件旁的 tools/ 目錄(不保證存在)。"""
    return Path(__file__).parent / "tools"
```

改成:

```python
def bundled_tools_dir() -> Path:
    """安裝程式會把工具放在套件旁的 tools/ 目錄(不保證存在)。
    打包後(sys.frozen)以執行檔所在目錄為準;開發模式維持相對於原始碼的位置。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "tools"
    return Path(__file__).parent / "tools"
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_tools.py -v -k bundled_tools_dir`
Expected: 2 passed

- [ ] **Step 5: 跑全套確認無回歸**

Run: `py -m pytest tests -q`
Expected: 278 passed(276 + 2)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/tools.py tests/test_tools.py
git commit -m "feat: make bundled_tools_dir frozen-aware for packaged builds"
```

---

### Task 2: style_editor.py — profiles_dir 改 %APPDATA% + 首次搬移舊 profile

**Files:**
- Modify: `ass_style_tool/qt/style_editor.py`
- Modify: `tests/conftest.py`(新增 autouse APPDATA 隔離 fixture)
- Test: `tests/test_style_editor.py`

**Interfaces:**
- Consumes: Task 1 無關;標準庫 `os`、`shutil`
- Produces:
  - `StyleEditor.profiles_dir(self) -> Path`——回 `Path(os.environ["APPDATA"]) / "ass-style-tool" / "profiles"`
  - `migrate_legacy_profiles(legacy_dir: Path, target_dir: Path) -> int`(module-level 純函式)——target 已有 `*.json` 時回 0;legacy 不存在或無 `*.json` 時回 0;否則 `shutil.copy2` 每個 `*.json` 到 target(不刪原檔),回複製檔數
  - `StyleEditor.__init__` 在 `_refresh_profile_list()` 前呼叫 `migrate_legacy_profiles(Path.cwd() / "profiles", self.profiles_dir())`,包 try/except 不阻擋啟動

- [ ] **Step 1: 新增 conftest APPDATA 隔離 fixture(先做,避免後續測試污染真實 %APPDATA%)**

在 `tests/conftest.py` 末尾附加(檔案頂端若無 `import pytest` 需補上;先確認):

```python
@pytest.fixture(autouse=True)
def _isolate_appdata(tmp_path, monkeypatch):
    """把 APPDATA 重導到 tmp,確保任何測試(含 StyleEditor 建構時的 profile
    搬移/讀寫)都不會碰到真實使用者的 %APPDATA%。"""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
```

先跑一次確認沒弄壞既有測試:

Run: `py -m pytest tests -q`
Expected: 278 passed(與 Task 1 後相同;此 fixture 目前不影響任何既有行為,因為現在還沒有程式讀 APPDATA)

- [ ] **Step 2: 附加失敗測試**

在 `tests/test_style_editor.py` 末尾附加:

```python


# ---------- profiles_dir 改用 %APPDATA% ----------

def test_profiles_dir_uses_appdata(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    assert editor.profiles_dir() == tmp_path / "ass-style-tool" / "profiles"


# ---------- migrate_legacy_profiles ----------

def test_migrate_copies_when_target_empty(tmp_path):
    from ass_style_tool.qt.style_editor import migrate_legacy_profiles
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "a.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "target"
    n = migrate_legacy_profiles(legacy, target)
    assert n == 1
    assert (target / "a.json").exists()
    assert (legacy / "a.json").exists()          # 不刪原檔


def test_migrate_skips_when_target_has_json(tmp_path):
    from ass_style_tool.qt.style_editor import migrate_legacy_profiles
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "a.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    (target / "existing.json").write_text("{}", encoding="utf-8")
    assert migrate_legacy_profiles(legacy, target) == 0
    assert not (target / "a.json").exists()      # 沒覆蓋/沒搬


def test_migrate_noop_when_legacy_absent(tmp_path):
    from ass_style_tool.qt.style_editor import migrate_legacy_profiles
    assert migrate_legacy_profiles(tmp_path / "nope", tmp_path / "target") == 0


def test_migrate_noop_when_legacy_empty(tmp_path):
    from ass_style_tool.qt.style_editor import migrate_legacy_profiles
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    target = tmp_path / "target"
    assert migrate_legacy_profiles(legacy, target) == 0
```

- [ ] **Step 3: 執行測試,確認失敗**

Run: `py -m pytest tests/test_style_editor.py -v -k "profiles_dir or migrate"`
Expected: FAIL — `test_profiles_dir_uses_appdata` 斷言失敗(目前回 `Path.cwd()/profiles`);`migrate_*` 全部 `ImportError: cannot import name 'migrate_legacy_profiles'`

- [ ] **Step 4: 實作**

在 `ass_style_tool/qt/style_editor.py` 頂端 import 區把:

```python
from pathlib import Path
from typing import Dict
```

改成:

```python
import os
import shutil
from pathlib import Path
from typing import Dict
```

在 `_ass_to_qcolor` 函式**之前**(module-level,`class StyleEditor` 之前)新增:

```python
def migrate_legacy_profiles(legacy_dir: Path, target_dir: Path) -> int:
    """首次啟動時把舊位置的 profile 搬到新位置(複製,不刪原檔)。
    target 已有 *.json → 不搬(回 0);legacy 不存在或無 *.json → 不搬(回 0)。
    回傳複製的檔案數。"""
    if target_dir.is_dir() and any(target_dir.glob("*.json")):
        return 0
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

把 `profiles_dir` 方法:

```python
    def profiles_dir(self) -> Path:
        return Path.cwd() / "profiles"
```

改成:

```python
    def profiles_dir(self) -> Path:
        return Path(os.environ["APPDATA"]) / "ass-style-tool" / "profiles"
```

在 `__init__` 中把:

```python
        self.set_values(DEFAULT_VALUES)
        self._refresh_profile_list()
```

改成:

```python
        self.set_values(DEFAULT_VALUES)
        try:
            migrate_legacy_profiles(Path.cwd() / "profiles", self.profiles_dir())
        except Exception:
            pass  # 搬移失敗不阻擋啟動;profile 清單以現有內容開始
        self._refresh_profile_list()
```

- [ ] **Step 5: 執行測試,確認通過**

Run: `py -m pytest tests/test_style_editor.py -v -k "profiles_dir or migrate"`
Expected: 5 passed

- [ ] **Step 6: 跑全套確認無回歸(重點:既有 StyleEditor 測試在 APPDATA 重導下仍通過且不污染真實環境)**

Run: `py -m pytest tests -q`
Expected: 283 passed(278 + 5)

若既有測試失敗,常見原因:某測試建構 `StyleEditor()` 後對 `profile_combo` 內容有斷言——因為建構時的搬移把 `repo/profiles/*.json` 複製進 tmp APPDATA 再被 `_refresh_profile_list()` 讀入。停下來回報,不要硬改既有測試。

- [ ] **Step 7: Commit**

```powershell
git add ass_style_tool/qt/style_editor.py tests/conftest.py tests/test_style_editor.py
git commit -m "feat: store profiles under %APPDATA% with one-time legacy migration"
```

---

### Task 3: PyInstaller spec + 打包/啟動驗證(控制器親自執行,不外包 subagent)

**Files:**
- Modify: `requirements.txt`(移除 tkinterdnd2)
- Create: `ass_style_tool.spec`
- (產物:`build/`、`dist/`——git 忽略,見下)

**Interfaces:**
- Consumes: Task 1 的 `bundled_tools_dir()`(frozen 時 = `dist/ass_style_tool/tools/`)、Task 2 的 `%APPDATA%` profile
- Produces: `dist/ass_style_tool/ass_style_tool.exe`(可雙擊啟動的 onedir 產物)

> **執行方式**:此任務由控制器(你)親自執行,不派 subagent——打包依賴完整本機環境(libmpv DLL、PySide6 hook),且需要實際啟動 GUI 逐項驗證。步驟為疊代式(build → 啟動 → 若失敗調 spec → 重 build),非固定 TDD。

- [ ] **Step 1: 移除死依賴 tkinterdnd2**

`requirements.txt` 把 `tkinterdnd2>=0.3` 那行刪除(v1 tkinter GUI 已移除,Qt 版未用到)。

- [ ] **Step 2: 確認 build/dist 已被 git 忽略**

檢查 `.gitignore` 是否含 `build/` 與 `dist/`;若無,附加:

```
build/
dist/
*.spec.bak
```

(`ass_style_tool.spec` 本身要進版控,不要忽略。)

- [ ] **Step 3: 安裝 PyInstaller(開發環境,不進 requirements.txt)**

Run: `py -m pip install pyinstaller`

- [ ] **Step 4: 調查 libmpv DLL 位置(打包最大風險點)**

python-mpv(`mpv` 套件)用 ctypes 載入 `libmpv-2.dll`。打包後那個 DLL 必須被收進產物且 frozen 執行時找得到。先定位開發機上的 DLL:

Run:
```powershell
py -c "import mpv, os, ctypes.util; print('mpv module:', mpv.__file__)"
Get-ChildItem -Path (Split-Path (py -c "import mpv; print(mpv.__file__)")) -Filter "*mpv*.dll" -ErrorAction SilentlyContinue
Get-ChildItem -Path "C:\Users\CAT\AppData\Local\Programs\Python\Python313\Lib\site-packages" -Filter "libmpv*.dll" -ErrorAction SilentlyContinue
```

記下 `libmpv-2.dll` 的絕對路徑(記為 `<LIBMPV_PATH>`),Step 5 的 spec 會用到。

- [ ] **Step 5: 寫 `ass_style_tool.spec`**

在 repo 根目錄建立 `ass_style_tool.spec`(onedir)。以下為起始版本,`binaries` 的 libmpv 路徑用 Step 4 找到的實際路徑;`console=False`、`icon` 已設好:

```python
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec:ASS 字幕樣式批次工具。"""
from pathlib import Path

# Step 4 找到的 libmpv-2.dll 絕對路徑(用實際值取代)
LIBMPV = r"<LIBMPV_PATH>"

block_cipher = None

a = Analysis(
    ["ass_style_tool/__main__.py"],
    pathex=[],
    binaries=[(LIBMPV, ".")],          # libmpv-2.dll 收進產物根
    datas=[],
    hiddenimports=["mpv"],             # python-mpv 動態載入,顯式收進
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "tkinterdnd2"],  # v1 tkinter GUI 已移除,排除
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ass_style_tool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                     # GUI 程式,不開終端機視窗
    icon="assets/icon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ass_style_tool",
)
```

- [ ] **Step 6: 打包**

Run: `py -m PyInstaller ass_style_tool.spec --noconfirm`
Expected: 成功,產生 `dist/ass_style_tool/ass_style_tool.exe`

若失敗,依錯誤訊息調整 spec(常見:PySide6 缺 hiddenimport → 加進 `hiddenimports`;或需 `--collect-all PySide6`——可改用 `collect_all` 在 spec 內處理)。重跑本步驟。

- [ ] **Step 7: 啟動並逐項驗證**

Run(直接執行打包出的 exe,不透過 `py -m`):
```powershell
$exe = "C:\Claude_code\dist\ass_style_tool\ass_style_tool.exe"
$p = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 5
if ($p.HasExited) { Write-Output "FAIL exit=$($p.ExitCode)" } else { Write-Output "OK pid=$($p.Id)" }
```

若 `HasExited`(啟動即崩潰),常見原因與對策:
- libmpv 找不到 → 確認 Step 4 路徑正確、`binaries` 有收;必要時改 `binaries=[(LIBMPV, ".")]` 讓 DLL 落在 exe 同層而非 `_internal`
- PySide6 缺 plugin(platforms/qwindows.dll)→ spec 頂端加 `from PyInstaller.utils.hooks import collect_all` 並 `datas, binaries, hiddenimports = collect_all("PySide6")` 併入
- 其他 ModuleNotFoundError → 對應模組加進 `hiddenimports`

啟動成功後,人工確認(可請使用者一起看):
1. 視窗開啟,4 分頁(字幕檔/MKV/封裝/樣式與預覽)都在
2. 「樣式與預覽」分頁 mpv 播放器正常(不是「缺 libmpv」降級提示)—— libmpv 綁定成功的關鍵指標
3. `tools/` 資料夾預期為空 → MKV/封裝分頁顯示「找不到 mkvmerge」停用提示(這是預期行為)
4. 設定持久化:選資料夾 → 關閉 → 重開 exe → 路徑還原
5. `%APPDATA%\ass-style-tool\profiles\` 正確建立;若開發機舊 `C:\Claude_code\profiles` 有檔案,首次啟動應已複製過去

- [ ] **Step 8: 疊代直到通過**

若 Step 7 任何項目失敗,回 Step 5 調 spec,重跑 6-7,直到啟動成功且 1-5 全數通過。把最終可用的 spec 定案。

- [ ] **Step 9: Commit**

```powershell
git add ass_style_tool.spec requirements.txt .gitignore
git commit -m "build: add PyInstaller onedir spec; drop dead tkinterdnd2 dependency"
```

- [ ] **Step 10: 全套測試複驗(確認打包改動未影響單元測試)**

Run: `py -m pytest tests -q`
Expected: 283 passed(與 Task 2 後相同——Task 3 只加 spec/改 requirements,不動被測程式碼)

---

## 本計畫完成後

程式可打包成 onedir 可執行資料夾。剩 **Plan 3 第二階段:Inno Setup 安裝程式**(開始功能表捷徑、解除安裝、ffmpeg/MKVToolNix 可勾選元件+系統偵測決定預設勾選)——需先安裝 Inno Setup,另開 spec/plan。
