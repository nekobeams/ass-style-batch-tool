# 設定持久化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重開程式時記住三個分頁的來源資料夾/輸出模式/輸出資料夾路徑,以及樣式編輯的上次選用 profile;還原時只填路徑文字,不觸發掃描。

**Architecture:** 每個分頁(`SubtitleFileTab`/`MkvTab`/`MuxTab`)與 `StyleEditor` 各自新增 `save_settings(settings)`/`restore_settings(settings)` 方法,用分頁專屬 key 前綴讀寫 `QSettings`。`MainWindow._restore_settings()`/`closeEvent()` 呼叫全部四個分頁的對應方法。還原用 `setText()`/`setChecked()`,不呼叫任何掃描方法,天然不觸發背景執行緒。

**Tech Stack:** PySide6 `QSettings`(`QSettings.Format.IniFormat` 測試用暫存檔,不碰真實 registry)、pytest(offscreen Qt)。

**Spec:** `docs/superpowers/specs/2026-07-13-settings-persistence-design.md`

## Global Constraints

- 工作目錄/repo root:`C:\Claude_code`;git branch 由執行者依 subagent-driven 流程建立(從 master HEAD 分出)
- **環境重點**:`python` 是壞的 Windows Store stub,一律用 `py`:`py -m pytest tests -v`
- Python 3.9+ 相容;各檔案已有 `from __future__ import annotations`
- 測試絕不寫真實使用者 QSettings(registry/使用者設定檔):一律用 `QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)` 注入暫存檔
- **不記錄**:處理模式(套用/縮放)、縮放倍率、封裝軌資訊(語言/軌名/default/forced)——維持每次預設值
- 還原**不觸發掃描**:只用 `setText()`/`setChecked()`,不呼叫 `_auto_scan`/`_on_scan`/`_folder_chosen` 等方法(`setText()` 不會觸發 `editingFinished`,天然滿足此約束)
- 測試指令:`py -m pytest tests -v`(從 repo root;目前基準 **263 passed**)
- Commit 訊息用 conventional commits(英文)

### 既有介面(本計畫會用到,已實作)

- `SubtitleFileTab`(`ass_style_tool/qt/subtitle_tab.py`):`self.folder_edit`(QLineEdit)、`self.inplace_radio`/`self.outdir_radio`(輸出模式二選一,inplace 預設勾選)、`self.outdir_edit`(QLineEdit)
- `MkvTab`(`ass_style_tool/qt/mkv_tab.py`):`self.folder_edit`、`self.outdir_radio`/`self.replace_radio`(輸出模式二選一,outdir 預設勾選)、`self.outdir_edit`
- `MuxTab`(`ass_style_tool/qt/mux_tab.py`):`self.video_edit`、`self.subtitle_edit`、`self.outdir_radio`/`self.replace_radio`(輸出模式二選一,outdir 預設勾選)、`self.outdir_edit`
- `StyleEditor`(`ass_style_tool/qt/style_editor.py`):`self.profile_combo`(QComboBox,`currentData()`/`findData()` 用 profile 檔案路徑字串)、`load_profile_from(path) -> None`、`profiles_dir(self) -> Path`(可 monkeypatch 覆蓋以測試,回傳 `Path.cwd() / "profiles"`)
- `MainWindow`(`ass_style_tool/qt/main_window.py`):`self.settings: QSettings`(建構子已建立,`_restore_settings()` 於 `__init__` 尾端呼叫;`closeEvent()` 已有 geometry/theme_mode 存檔)

## File Structure

```
ass_style_tool/qt/
├── subtitle_tab.py     # (修改)新增 save_settings/restore_settings
├── mkv_tab.py           # (修改)新增 save_settings/restore_settings
├── mux_tab.py           # (修改)新增 save_settings/restore_settings
├── style_editor.py      # (修改)新增 save_settings/restore_settings
└── main_window.py       # (修改)_restore_settings/closeEvent 接線四個分頁
tests/
├── test_subtitle_tab.py # (修改)附加測試
├── test_mkv_tab.py       # (修改)附加測試
├── test_mux_tab.py       # (修改)附加測試
└── test_style_editor.py # (修改)附加測試
```

---

### Task 1: SubtitleFileTab 設定持久化

**Files:**
- Modify: `ass_style_tool/qt/subtitle_tab.py`
- Test: `tests/test_subtitle_tab.py`

**Interfaces:**
- Consumes: `PySide6.QtCore.QSettings`;既有 `self.folder_edit`、`self.inplace_radio`、`self.outdir_radio`、`self.outdir_edit`
- Produces:
  - `save_settings(self, settings: QSettings) -> None`
  - `restore_settings(self, settings: QSettings) -> None`

- [ ] **Step 1: 附加失敗測試**

在 `tests/test_subtitle_tab.py` 末尾附加:

```python


# ---------- 設定持久化 ----------

def test_save_and_restore_settings_roundtrip(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab_a = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    tab_a.folder_edit.setText(r"C:\videos\show")
    tab_a.outdir_radio.setChecked(True)
    tab_a.outdir_edit.setText(r"C:\videos\out")
    tab_a.save_settings(settings)

    tab_b = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    tab_b.restore_settings(settings)
    assert tab_b.folder_edit.text() == r"C:\videos\show"
    assert tab_b.outdir_radio.isChecked() is True
    assert tab_b.outdir_edit.text() == r"C:\videos\out"


def test_restore_settings_does_not_trigger_scan(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    settings.setValue("subtitle/folder", str(tmp_path))
    settings.setValue("subtitle/output_mode", "inplace")
    settings.setValue("subtitle/outdir", "")

    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    tab.restore_settings(settings)
    assert tab._scanned_folder is None
    assert tab.table.rowCount() == 0


def test_restore_settings_defaults_inplace_when_unset(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    tab.restore_settings(settings)
    assert tab.folder_edit.text() == ""
    assert tab.inplace_radio.isChecked() is True
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_subtitle_tab.py -v -k settings`
Expected: FAIL — `AttributeError: 'SubtitleFileTab' object has no attribute 'save_settings'`

- [ ] **Step 3: 實作**

在 `ass_style_tool/qt/subtitle_tab.py` 的 import 區把:

```python
from PySide6.QtCore import Qt, QThread, Signal
```

改成:

```python
from PySide6.QtCore import Qt, QSettings, QThread, Signal
```

在 `shutdown()` 方法之後新增:

```python
    # ---------- 設定持久化 ----------
    def save_settings(self, settings: QSettings) -> None:
        settings.setValue("subtitle/folder", self.folder_edit.text())
        settings.setValue(
            "subtitle/output_mode",
            "outdir" if self.outdir_radio.isChecked() else "inplace")
        settings.setValue("subtitle/outdir", self.outdir_edit.text())

    def restore_settings(self, settings: QSettings) -> None:
        self.folder_edit.setText(settings.value("subtitle/folder", ""))
        self.outdir_edit.setText(settings.value("subtitle/outdir", ""))
        if settings.value("subtitle/output_mode", "inplace") == "outdir":
            self.outdir_radio.setChecked(True)
        else:
            self.inplace_radio.setChecked(True)
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_subtitle_tab.py -v -k settings`
Expected: 3 passed

- [ ] **Step 5: 跑全套確認無回歸**

Run: `py -m pytest tests -q`
Expected: 266 passed(263 + 3)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/qt/subtitle_tab.py tests/test_subtitle_tab.py
git commit -m "feat: persist subtitle tab folder/output settings"
```

---

### Task 2: MkvTab 設定持久化

**Files:**
- Modify: `ass_style_tool/qt/mkv_tab.py`
- Test: `tests/test_mkv_tab.py`

**Interfaces:**
- Consumes: `PySide6.QtCore.QSettings`;既有 `self.folder_edit`、`self.outdir_radio`、`self.replace_radio`、`self.outdir_edit`
- Produces:
  - `save_settings(self, settings: QSettings) -> None`
  - `restore_settings(self, settings: QSettings) -> None`

- [ ] **Step 1: 附加失敗測試**

在 `tests/test_mkv_tab.py` 末尾附加(檔案已有 `_tab(monkeypatch, available=True)` helper,沿用):

```python


# ---------- 設定持久化 ----------

def test_save_and_restore_settings_roundtrip(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab_a = _tab(monkeypatch)
    tab_a.folder_edit.setText(r"C:\mkv\show")
    tab_a.replace_radio.setChecked(True)
    tab_a.outdir_edit.setText(r"C:\mkv\out")
    tab_a.save_settings(settings)

    tab_b = _tab(monkeypatch)
    tab_b.restore_settings(settings)
    assert tab_b.folder_edit.text() == r"C:\mkv\show"
    assert tab_b.replace_radio.isChecked() is True
    assert tab_b.outdir_edit.text() == r"C:\mkv\out"


def test_restore_settings_does_not_trigger_scan(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    settings.setValue("mkv/folder", str(tmp_path))
    settings.setValue("mkv/output_mode", "outdir")
    settings.setValue("mkv/outdir", "")

    tab = _tab(monkeypatch)
    tab.restore_settings(settings)
    assert tab._scanned_folder is None


def test_restore_settings_defaults_outdir_when_unset(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab = _tab(monkeypatch)
    tab.restore_settings(settings)
    assert tab.folder_edit.text() == ""
    assert tab.outdir_radio.isChecked() is True
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_mkv_tab.py -v -k settings`
Expected: FAIL — `AttributeError: 'MkvTab' object has no attribute 'save_settings'`

- [ ] **Step 3: 實作**

在 `ass_style_tool/qt/mkv_tab.py` 的 import 區把:

```python
from PySide6.QtCore import Qt, QThread, Signal
```

改成:

```python
from PySide6.QtCore import Qt, QSettings, QThread, Signal
```

在 `shutdown()` 方法之後新增:

```python
    # ---------- 設定持久化 ----------
    def save_settings(self, settings: QSettings) -> None:
        settings.setValue("mkv/folder", self.folder_edit.text())
        settings.setValue(
            "mkv/output_mode",
            "replace" if self.replace_radio.isChecked() else "outdir")
        settings.setValue("mkv/outdir", self.outdir_edit.text())

    def restore_settings(self, settings: QSettings) -> None:
        self.folder_edit.setText(settings.value("mkv/folder", ""))
        self.outdir_edit.setText(settings.value("mkv/outdir", ""))
        if settings.value("mkv/output_mode", "outdir") == "replace":
            self.replace_radio.setChecked(True)
        else:
            self.outdir_radio.setChecked(True)
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_mkv_tab.py -v -k settings`
Expected: 3 passed

- [ ] **Step 5: 跑全套確認無回歸**

Run: `py -m pytest tests -q`
Expected: 269 passed(266 + 3)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/qt/mkv_tab.py tests/test_mkv_tab.py
git commit -m "feat: persist mkv tab folder/output settings"
```

---

### Task 3: MuxTab 設定持久化

**Files:**
- Modify: `ass_style_tool/qt/mux_tab.py`
- Test: `tests/test_mux_tab.py`

**Interfaces:**
- Consumes: `PySide6.QtCore.QSettings`;既有 `self.video_edit`、`self.subtitle_edit`、`self.outdir_radio`、`self.replace_radio`、`self.outdir_edit`
- Produces:
  - `save_settings(self, settings: QSettings) -> None`
  - `restore_settings(self, settings: QSettings) -> None`

- [ ] **Step 1: 附加失敗測試**

在 `tests/test_mux_tab.py` 末尾附加(檔案已有 `_tab(monkeypatch, available=True)` helper,沿用):

```python


# ---------- 設定持久化 ----------

def test_save_and_restore_settings_roundtrip(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab_a = _tab(monkeypatch)
    tab_a.video_edit.setText(r"C:\mux\video")
    tab_a.subtitle_edit.setText(r"C:\mux\sub")
    tab_a.replace_radio.setChecked(True)
    tab_a.outdir_edit.setText(r"C:\mux\out")
    tab_a.save_settings(settings)

    tab_b = _tab(monkeypatch)
    tab_b.restore_settings(settings)
    assert tab_b.video_edit.text() == r"C:\mux\video"
    assert tab_b.subtitle_edit.text() == r"C:\mux\sub"
    assert tab_b.replace_radio.isChecked() is True
    assert tab_b.outdir_edit.text() == r"C:\mux\out"


def test_restore_settings_does_not_trigger_scan(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    settings.setValue("mux/video_folder", str(tmp_path))
    settings.setValue("mux/subtitle_folder", str(tmp_path))
    settings.setValue("mux/output_mode", "outdir")
    settings.setValue("mux/outdir", "")

    tab = _tab(monkeypatch)
    tab.restore_settings(settings)
    assert tab._scanned_key is None
    assert tab.table.rowCount() == 0


def test_restore_settings_defaults_outdir_when_unset(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab = _tab(monkeypatch)
    tab.restore_settings(settings)
    assert tab.video_edit.text() == ""
    assert tab.subtitle_edit.text() == ""
    assert tab.outdir_radio.isChecked() is True
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_mux_tab.py -v -k settings`
Expected: FAIL — `AttributeError: 'MuxTab' object has no attribute 'save_settings'`

- [ ] **Step 3: 實作**

在 `ass_style_tool/qt/mux_tab.py` 的 import 區把:

```python
from PySide6.QtCore import Qt, QThread, Signal
```

改成:

```python
from PySide6.QtCore import Qt, QSettings, QThread, Signal
```

在 `shutdown()` 方法之後新增:

```python
    # ---------- 設定持久化 ----------
    def save_settings(self, settings: QSettings) -> None:
        settings.setValue("mux/video_folder", self.video_edit.text())
        settings.setValue("mux/subtitle_folder", self.subtitle_edit.text())
        settings.setValue(
            "mux/output_mode",
            "replace" if self.replace_radio.isChecked() else "outdir")
        settings.setValue("mux/outdir", self.outdir_edit.text())

    def restore_settings(self, settings: QSettings) -> None:
        self.video_edit.setText(settings.value("mux/video_folder", ""))
        self.subtitle_edit.setText(settings.value("mux/subtitle_folder", ""))
        self.outdir_edit.setText(settings.value("mux/outdir", ""))
        if settings.value("mux/output_mode", "outdir") == "replace":
            self.replace_radio.setChecked(True)
        else:
            self.outdir_radio.setChecked(True)
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_mux_tab.py -v -k settings`
Expected: 3 passed

- [ ] **Step 5: 跑全套確認無回歸**

Run: `py -m pytest tests -q`
Expected: 272 passed(269 + 3)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/qt/mux_tab.py tests/test_mux_tab.py
git commit -m "feat: persist mux tab folder/output settings"
```

---

### Task 4: StyleEditor 設定持久化 + 接線 MainWindow

**Files:**
- Modify: `ass_style_tool/qt/style_editor.py`
- Modify: `ass_style_tool/qt/main_window.py`
- Test: `tests/test_style_editor.py`

**Interfaces:**
- Consumes: `PySide6.QtCore.QSettings`;既有 `self.profile_combo`、`load_profile_from(path)`、`profiles_dir()`;Task 1-3 的 `save_settings`/`restore_settings`(在 `SubtitleFileTab`/`MkvTab`/`MuxTab` 上,本 task 直接呼叫,不重新定義)
- Produces:
  - `StyleEditor.save_settings(self, settings: QSettings) -> None`
  - `StyleEditor.restore_settings(self, settings: QSettings) -> None`
  - `MainWindow._restore_settings()` 呼叫全部四個分頁的 `restore_settings`
  - `MainWindow.closeEvent()` 呼叫全部四個分頁的 `save_settings`

- [ ] **Step 1: 附加失敗測試**

在 `tests/test_style_editor.py` 末尾附加:

```python


# ---------- 設定持久化 ----------

def test_save_and_restore_profile_setting(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from ass_style_tool.profile import save_profile
    from ass_style_tool.qt.style_editor import StyleEditor

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    editor_a = StyleEditor()
    monkeypatch.setattr(editor_a, "profiles_dir", lambda: profiles_dir)
    editor_a.set_values(DEFAULT_VALUES)
    profile = editor_a.current_profile()
    save_profile(profile, profiles_dir / "mine.json")
    editor_a._refresh_profile_list()
    idx = editor_a.profile_combo.findData(str(profiles_dir / "mine.json"))
    editor_a.profile_combo.setCurrentIndex(idx)

    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    editor_a.save_settings(settings)

    editor_b = StyleEditor()
    monkeypatch.setattr(editor_b, "profiles_dir", lambda: profiles_dir)
    editor_b._refresh_profile_list()
    editor_b.restore_settings(settings)
    assert editor_b.profile_combo.currentData() == str(profiles_dir / "mine.json")


def test_restore_profile_setting_missing_file_is_silent(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from ass_style_tool.qt.style_editor import StyleEditor

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    settings.setValue("style/profile", str(profiles_dir / "gone.json"))

    editor = StyleEditor()
    monkeypatch.setattr(editor, "profiles_dir", lambda: profiles_dir)
    editor._refresh_profile_list()
    editor.restore_settings(settings)  # 不應拋例外
    assert editor.profile_combo.currentData() is None
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_style_editor.py -v -k settings`
Expected: FAIL — `AttributeError: 'StyleEditor' object has no attribute 'save_settings'`

- [ ] **Step 3: 實作 StyleEditor**

在 `ass_style_tool/qt/style_editor.py` 的 import 區把:

```python
from PySide6.QtCore import Signal
```

改成:

```python
from PySide6.QtCore import QSettings, Signal
```

在 `_on_save_as` 方法之後(或檔案內任何既有方法之後)新增:

```python
    # ---------- 設定持久化 ----------
    def save_settings(self, settings: QSettings) -> None:
        path = self.profile_combo.currentData()
        if path:
            settings.setValue("style/profile", path)

    def restore_settings(self, settings: QSettings) -> None:
        path = settings.value("style/profile", "")
        if not path:
            return
        idx = self.profile_combo.findData(path)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
            self.load_profile_from(path)
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_style_editor.py -v -k settings`
Expected: 2 passed

- [ ] **Step 5: 接線 MainWindow**

在 `ass_style_tool/qt/main_window.py` 的 `_restore_settings()` 方法結尾(`self._apply_current_theme()` 那行之前,因為主題套用應在其他控件都還原完後仍可最後套用──實際上兩者互不影響,放在 `self._apply_current_theme()` 之後也可以,這裡選擇放在方法最後一行之前以維持既有結構最小變動)加:

```python
        self.style_editor.restore_settings(self.settings)
        self.subtitle_tab.restore_settings(self.settings)
        self.mkv_tab.restore_settings(self.settings)
        self.mux_tab.restore_settings(self.settings)
```

在 `closeEvent()` 中,`self.mux_tab.shutdown()` 那行之後、`self.settings.setValue("geometry", ...)` 之前加:

```python
        self.style_editor.save_settings(self.settings)
        self.subtitle_tab.save_settings(self.settings)
        self.mkv_tab.save_settings(self.settings)
        self.mux_tab.save_settings(self.settings)
```

- [ ] **Step 6: 全套測試 + import + 啟動冒煙**

Run: `py -m pytest tests -q`
Expected: 274 passed(272 + 2)

Run: `py -c "import ass_style_tool.qt.main_window; print('ok')"`
Expected: `ok`

```powershell
$p = Start-Process -FilePath "py" -ArgumentList "-m","ass_style_tool" -WorkingDirectory "C:\Claude_code" -PassThru
Start-Sleep -Seconds 3
if ($p.HasExited) { Write-Output "FAIL exit=$($p.ExitCode)" } else { Write-Output "OK"; Stop-Process -Id $p.Id }
```

Expected: `OK`

- [ ] **Step 7: Commit**

```powershell
git add ass_style_tool/qt/style_editor.py ass_style_tool/qt/main_window.py tests/test_style_editor.py
git commit -m "feat: persist last-used profile and wire settings restore/save into main window"
```

- [ ] **Step 8: 手動冒煙清單(由使用者執行,記於報告)**

Run: `py -m ass_style_tool`
1. 各分頁選好資料夾、輸出模式、profile → 關閉視窗
2. 重新開啟 → 三個分頁的資料夾/輸出模式路徑都還原,但表格是空的(沒有自動掃描)、樣式編輯顯示上次選的 profile
3. 按「重新掃描」確認手動觸發掃描仍正常運作

---

## 本計畫完成後

spec UX-1(設定持久化)完成。UX-2(profile 刪除按鈕)與其他小 UX 瑕疵留待之後視情況處理,或直接進 Plan 3(打包)。
