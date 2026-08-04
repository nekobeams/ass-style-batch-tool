# v2 Plan 2a — Qt 外殼 + 主題系統 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 v2 的 PySide6 應用外殼——深色/淺色/跟隨系統三種主題、分頁籤主視窗、log 區、QSettings 持久化——外加兩個可 TDD 的純邏輯輔助模組(主題決策、Profile 欄位轉換),為之後的樣式面板與分頁功能(Plan 2b/2c)鋪路。

**Architecture:** 非 Qt 的純邏輯(主題模式決策、Profile↔欄位字典轉換)抽成獨立可測模組;Qt 部分是薄外殼,以 import 檢查 + 啟動冒煙 + 手動清單驗證。v1 的 tkinter GUI 暫時保留(`py -m ass_style_tool` 仍是舊介面),新 Qt 介面用 `py -m ass_style_tool.qt` 啟動,待 Plan 2b/2c 達到功能對等後再切換進入點並移除舊 GUI。

**Tech Stack:** PySide6(Qt 6.6+)、pytest。本計畫不引入 mpv(留給 Plan 2c)。

**Spec:** `docs/superpowers/specs/2026-07-08-ass-style-tool-v2-design.md`

## Global Constraints

- 工作目錄/repo root:專案根目錄,git branch 由執行者依 subagent-driven 流程建立
- **環境重點**:這台機器 `python` 是壞的 Windows Store stub,一律用 `py`:`py -m pytest tests -v`、`py -m pip ...`、`py -m ass_style_tool.qt`
- Python 3.9+ 相容;每個新模組頂端加 `from __future__ import annotations`
- 依賴新增:`PySide6>=6.6`(Qt 6.5+ 才有 `QStyleHints.colorScheme()`,故下限 6.6)
- 不動 v1 核心模組(profile/resolution/ass_style/episode_match/batch_runner)與其測試
- **不動、不刪** v1 的 `ass_style_tool/gui.py` 與 `ass_style_tool/__main__.py`(舊 tkinter 介面暫時保留;移除留給後續計畫)
- 主題模式常數:`"system"`(預設)/ `"dark"` / `"light"`
- QSettings 組織/應用名稱固定:`QSettings("ass-style-tool", "ass-style-tool")`
- Qt 相關測試需能在無顯示器 CI 跑:pytest 時設環境變數 `QT_QPA_PLATFORM=offscreen`(見各任務)
- 測試指令:`py -m pytest tests -v`(從 repo root)
- Commit 訊息用 conventional commits

### 既有介面(本計畫會用到)

- `ass_style_tool.profile.Profile`(欄位 profile_name, target_style_names: list[str], base_width: int, base_height: int, style: TargetStyle)
- `ass_style_tool.profile.TargetStyle`(欄位 fontname, fontsize: float, bold: bool, italic: bool, primary_colour, outline_colour, back_colour, outline: float, shadow: float, alignment: int, margin_l/r/v: int)
- `ass_style_tool.profile.parse_ass_color(text) -> pysubs2.Color`(非法字串丟 ValueError)

## File Structure

```
ass_style_tool/
├── profile_fields.py     # 純邏輯:Profile <-> 欄位字典(移出 v1 tk GUI 的 _collect_profile 邏輯,可測)
└── qt/
    ├── __init__.py       # 空
    ├── __main__.py       # py -m ass_style_tool.qt 進入點
    ├── theme.py          # resolve_theme(純)、qss_for(純)、system_is_dark、apply_theme
    └── main_window.py    # 主視窗:分頁籤、主題切換控制、log 區、QSettings
tests/
├── test_profile_fields.py
└── test_theme.py
```

---

### Task 1: profile_fields.py — Profile ↔ 欄位字典(純邏輯)

**Files:**
- Create: `ass_style_tool/profile_fields.py`
- Test: `tests/test_profile_fields.py`

**Interfaces:**
- Consumes: `profile.Profile`, `profile.TargetStyle`, `profile.parse_ass_color`
- Produces:
  - `FIELD_KEYS: tuple[str, ...]` — 欄位字典的鍵集合
  - `DEFAULT_VALUES: dict` — 一組合理預設欄位值(給 GUI 初始化用)
  - `profile_from_values(values: dict) -> Profile` — 把字串/原生值的欄位字典轉成 Profile;數值欄位非法或必填空白丟 `ValueError`
  - `values_from_profile(profile: Profile) -> dict` — 反向,回傳字串化的欄位字典(給 GUI 欄位填值)

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_profile_fields.py`:

```python
from __future__ import annotations

import pytest

from ass_style_tool.profile import Profile
from ass_style_tool.profile_fields import (DEFAULT_VALUES, FIELD_KEYS,
                                           profile_from_values,
                                           values_from_profile)


def test_default_values_have_all_keys():
    assert set(DEFAULT_VALUES) == set(FIELD_KEYS)


def test_defaults_build_valid_profile():
    p = profile_from_values(DEFAULT_VALUES)
    assert isinstance(p, Profile)
    assert p.base_width == 1920
    assert p.base_height == 1080


def test_profile_from_values_parses_types():
    values = dict(DEFAULT_VALUES)
    values.update({
        "profile_name": "我的",
        "target_style_names": "Default, OP",
        "fontname": "思源黑體 CN",
        "fontsize": "72",
        "bold": True,
        "italic": False,
        "outline": "3.6",
        "shadow": "1.0",
        "alignment": "2",
        "margin_l": "20", "margin_r": "20", "margin_v": "24",
        "base_width": "1920", "base_height": "1080",
        "primary_colour": "&H00FFFFFF",
        "outline_colour": "&H00000000",
        "back_colour": "&H00000000",
    })
    p = profile_from_values(values)
    assert p.target_style_names == ["Default", "OP"]   # 逗號分隔、去空白
    assert p.style.fontsize == 72.0
    assert p.style.bold is True
    assert p.style.alignment == 2
    assert p.style.margin_v == 24


def test_empty_fontname_raises():
    values = dict(DEFAULT_VALUES)
    values["fontname"] = "  "
    with pytest.raises(ValueError):
        profile_from_values(values)


def test_empty_target_styles_raises():
    values = dict(DEFAULT_VALUES)
    values["target_style_names"] = " , "
    with pytest.raises(ValueError):
        profile_from_values(values)


def test_bad_number_raises():
    values = dict(DEFAULT_VALUES)
    values["fontsize"] = "big"
    with pytest.raises(ValueError):
        profile_from_values(values)


def test_bad_color_raises():
    values = dict(DEFAULT_VALUES)
    values["primary_colour"] = "nope"
    with pytest.raises(ValueError):
        profile_from_values(values)


def test_nonpositive_base_resolution_raises():
    values = dict(DEFAULT_VALUES)
    values["base_width"] = "0"
    with pytest.raises(ValueError):
        profile_from_values(values)


def test_bad_alignment_raises():
    values = dict(DEFAULT_VALUES)
    values["alignment"] = "10"
    with pytest.raises(ValueError):
        profile_from_values(values)


def test_roundtrip_values_profile_values():
    p = profile_from_values(DEFAULT_VALUES)
    back = values_from_profile(p)
    p2 = profile_from_values(back)
    assert p == p2
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_profile_fields.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.profile_fields'`

- [ ] **Step 3: 實作 profile_fields.py**

建立 `ass_style_tool/profile_fields.py`:

```python
"""Profile 與 GUI 欄位字典之間的轉換與驗證(純邏輯,不依賴 Qt)。"""
from __future__ import annotations

from typing import Dict, Tuple

from .profile import Profile, TargetStyle, parse_ass_color

FIELD_KEYS: Tuple[str, ...] = (
    "profile_name", "target_style_names",
    "fontname", "fontsize", "bold", "italic",
    "primary_colour", "outline_colour", "back_colour",
    "outline", "shadow", "alignment",
    "margin_l", "margin_r", "margin_v",
    "base_width", "base_height",
)

DEFAULT_VALUES: Dict[str, object] = {
    "profile_name": "我的字幕標準",
    "target_style_names": "Default",
    "fontname": "思源黑體 CN",
    "fontsize": "72",
    "bold": False,
    "italic": False,
    "primary_colour": "&H00FFFFFF",
    "outline_colour": "&H00000000",
    "back_colour": "&H00000000",
    "outline": "3.6",
    "shadow": "1.0",
    "alignment": "2",
    "margin_l": "20",
    "margin_r": "20",
    "margin_v": "24",
    "base_width": "1920",
    "base_height": "1080",
}


def _num(values: dict, key: str, cast):
    try:
        return cast(values[key])
    except (TypeError, ValueError):
        raise ValueError(f"欄位 {key} 必須是數字,收到 {values.get(key)!r}")


def profile_from_values(values: dict) -> Profile:
    fontname = str(values["fontname"]).strip()
    if not fontname:
        raise ValueError("字型名稱不可為空")
    names = [n.strip() for n in str(values["target_style_names"]).split(",")
             if n.strip()]
    if not names:
        raise ValueError("目標 Style 名稱不可為空")
    alignment = _num(values, "alignment", int)
    if not 1 <= alignment <= 9:
        raise ValueError(f"alignment 必須是 1-9,收到 {alignment}")
    base_width = _num(values, "base_width", int)
    base_height = _num(values, "base_height", int)
    if base_width <= 0 or base_height <= 0:
        raise ValueError("基準解析度必須大於 0")
    for key in ("primary_colour", "outline_colour", "back_colour"):
        parse_ass_color(str(values[key]))  # 非法丟 ValueError
    style = TargetStyle(
        fontname=fontname,
        fontsize=_num(values, "fontsize", float),
        bold=bool(values["bold"]),
        italic=bool(values["italic"]),
        primary_colour=str(values["primary_colour"]).strip(),
        outline_colour=str(values["outline_colour"]).strip(),
        back_colour=str(values["back_colour"]).strip(),
        outline=_num(values, "outline", float),
        shadow=_num(values, "shadow", float),
        alignment=alignment,
        margin_l=_num(values, "margin_l", int),
        margin_r=_num(values, "margin_r", int),
        margin_v=_num(values, "margin_v", int),
    )
    return Profile(
        profile_name=str(values["profile_name"]).strip() or "未命名",
        target_style_names=names,
        base_width=base_width,
        base_height=base_height,
        style=style,
    )


def values_from_profile(profile: Profile) -> Dict[str, object]:
    s = profile.style
    return {
        "profile_name": profile.profile_name,
        "target_style_names": ", ".join(profile.target_style_names),
        "fontname": s.fontname,
        "fontsize": str(s.fontsize),
        "bold": s.bold,
        "italic": s.italic,
        "primary_colour": s.primary_colour,
        "outline_colour": s.outline_colour,
        "back_colour": s.back_colour,
        "outline": str(s.outline),
        "shadow": str(s.shadow),
        "alignment": str(s.alignment),
        "margin_l": str(s.margin_l),
        "margin_r": str(s.margin_r),
        "margin_v": str(s.margin_v),
        "base_width": str(profile.base_width),
        "base_height": str(profile.base_height),
    }
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_profile_fields.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```powershell
git add ass_style_tool/profile_fields.py tests/test_profile_fields.py
git commit -m "feat: add pure Profile<->fields conversion for GUI"
```

---

### Task 2: 安裝 PySide6 + theme.py(主題決策純邏輯 + 套用)

**Files:**
- Create: `ass_style_tool/qt/__init__.py`(空)
- Create: `ass_style_tool/qt/theme.py`
- Modify: `requirements.txt`(加 `PySide6>=6.6`)
- Test: `tests/test_theme.py`

**Interfaces:**
- Consumes: PySide6
- Produces:
  - `THEME_MODES: tuple[str, ...]` = `("system", "dark", "light")`
  - `resolve_theme(mode: str, system_is_dark: bool) -> str` — 純函式,回 `"dark"` 或 `"light"`
  - `qss_for(theme: str) -> str` — 回該主題的 QSS 字串(`theme` 為 `"dark"`/`"light"`)
  - `system_is_dark(app) -> bool` — 用 `QApplication.styleHints().colorScheme()` 判斷(Qt 6.5+)
  - `apply_theme(app, mode: str) -> str` — 依 mode + 系統狀態套用 QSS,回實際套用的 theme(`"dark"`/`"light"`)

- [ ] **Step 1: 安裝 PySide6 並更新 requirements**

```powershell
py -m pip install "PySide6>=6.6"
```

在 `requirements.txt` 末尾加一行:

```
PySide6>=6.6
```

- [ ] **Step 2: 寫失敗測試**

建立 `tests/test_theme.py`:

```python
from __future__ import annotations

import pytest

from ass_style_tool.qt.theme import (THEME_MODES, qss_for, resolve_theme)


def test_theme_modes():
    assert THEME_MODES == ("system", "dark", "light")


def test_resolve_explicit_dark():
    assert resolve_theme("dark", system_is_dark=False) == "dark"


def test_resolve_explicit_light():
    assert resolve_theme("light", system_is_dark=True) == "light"


def test_resolve_system_follows_dark():
    assert resolve_theme("system", system_is_dark=True) == "dark"


def test_resolve_system_follows_light():
    assert resolve_theme("system", system_is_dark=False) == "light"


def test_resolve_unknown_mode_defaults_light():
    assert resolve_theme("bogus", system_is_dark=False) == "light"


def test_qss_for_dark_nonempty():
    assert "QMainWindow" in qss_for("dark")


def test_qss_for_light_differs_from_dark():
    assert qss_for("light") != qss_for("dark")
```

- [ ] **Step 3: 執行測試,確認失敗**

Run: `py -m pytest tests/test_theme.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.qt'`

- [ ] **Step 4: 實作 qt 套件與 theme.py**

建立空檔 `ass_style_tool/qt/__init__.py`。

建立 `ass_style_tool/qt/theme.py`:

```python
"""主題模式(跟隨系統/深色/淺色)決策與 QSS 套用。"""
from __future__ import annotations

from typing import Tuple

THEME_MODES: Tuple[str, ...] = ("system", "dark", "light")

_DARK_QSS = """
QMainWindow, QWidget { background-color: #1e1e1e; color: #e0e0e0; }
QTabWidget::pane { border: 1px solid #3a3a3a; }
QTabBar::tab { background: #2a2a2a; color: #c0c0c0; padding: 6px 14px; }
QTabBar::tab:selected { background: #3a3a3a; color: #ffffff; }
QLineEdit, QComboBox, QSpinBox, QTextEdit, QTableWidget {
    background-color: #2a2a2a; color: #e0e0e0; border: 1px solid #3a3a3a;
    selection-background-color: #4a6a8a;
}
QPushButton {
    background-color: #333333; color: #e0e0e0; border: 1px solid #4a4a4a;
    padding: 5px 12px;
}
QPushButton:hover { background-color: #3f3f3f; }
QPushButton:disabled { color: #707070; background-color: #2a2a2a; }
QHeaderView::section { background-color: #2a2a2a; color: #c0c0c0; border: 1px solid #3a3a3a; }
"""

_LIGHT_QSS = """
QMainWindow, QWidget { background-color: #f3f3f3; color: #202020; }
QTabWidget::pane { border: 1px solid #c8c8c8; }
QTabBar::tab { background: #e4e4e4; color: #404040; padding: 6px 14px; }
QTabBar::tab:selected { background: #ffffff; color: #000000; }
QLineEdit, QComboBox, QSpinBox, QTextEdit, QTableWidget {
    background-color: #ffffff; color: #202020; border: 1px solid #c8c8c8;
    selection-background-color: #b0d0f0;
}
QPushButton {
    background-color: #e8e8e8; color: #202020; border: 1px solid #c0c0c0;
    padding: 5px 12px;
}
QPushButton:hover { background-color: #dcdcdc; }
QPushButton:disabled { color: #a0a0a0; background-color: #eeeeee; }
QHeaderView::section { background-color: #e4e4e4; color: #404040; border: 1px solid #c8c8c8; }
"""


def resolve_theme(mode: str, system_is_dark: bool) -> str:
    """把 mode + 系統狀態解析成實際主題 'dark' 或 'light'。"""
    if mode == "dark":
        return "dark"
    if mode == "light":
        return "light"
    if mode == "system":
        return "dark" if system_is_dark else "light"
    return "light"  # 未知 mode 保底淺色


def qss_for(theme: str) -> str:
    return _DARK_QSS if theme == "dark" else _LIGHT_QSS


def system_is_dark(app) -> bool:
    """用 Qt 6.5+ 的 colorScheme 判斷系統是否深色;取不到則視為淺色。"""
    from PySide6.QtCore import Qt
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except (AttributeError, TypeError):
        return False


def apply_theme(app, mode: str) -> str:
    theme = resolve_theme(mode, system_is_dark(app))
    app.setStyleSheet(qss_for(theme))
    return theme
```

- [ ] **Step 5: 執行測試,確認通過**

Run: `py -m pytest tests/test_theme.py -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/qt/__init__.py ass_style_tool/qt/theme.py tests/test_theme.py requirements.txt
git commit -m "feat: add theme system (system/dark/light) with QSS"
```

---

### Task 3: Qt 主視窗外殼 + 進入點

**Files:**
- Create: `ass_style_tool/qt/main_window.py`
- Create: `ass_style_tool/qt/__main__.py`

**Interfaces:**
- Consumes: `qt.theme.THEME_MODES / apply_theme / system_is_dark`
- Produces:
  - `MainWindow(QMainWindow)` — 分頁籤(字幕檔/MKV/樣式與預覽,本計畫先放佔位標籤)、右上角主題模式下拉、底部 log 區;`append_log(text: str)`;主題與視窗幾何用 QSettings 持久化
  - `main() -> None` — 建立 QApplication、套用上次主題、開視窗、進 event loop

本任務無自動化測試(需 Qt 視窗),以 import 檢查 + 啟動冒煙 + 手動清單驗證。

- [ ] **Step 1: 實作 main_window.py**

建立 `ass_style_tool/qt/main_window.py`:

```python
"""v2 Qt 主視窗外殼:分頁籤、主題切換、log、QSettings 持久化。"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel,
                               QMainWindow, QPlainTextEdit, QTabWidget,
                               QVBoxLayout, QWidget)

from .theme import THEME_MODES, apply_theme, system_is_dark

_MODE_LABELS = {"system": "跟隨系統", "dark": "深色", "light": "淺色"}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ASS 字幕樣式批次工具")
        self.settings = QSettings("ass-style-tool", "ass-style-tool")

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # 頂列:主題切換(靠右)
        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(QLabel("主題:"))
        self.theme_combo = QComboBox()
        for mode in THEME_MODES:
            self.theme_combo.addItem(_MODE_LABELS[mode], mode)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        top.addWidget(self.theme_combo)
        layout.addLayout(top)

        # 分頁籤(本計畫先放佔位)
        self.tabs = QTabWidget()
        for name in ("字幕檔", "MKV", "樣式與預覽"):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.addWidget(QLabel(f"（{name} 功能於後續計畫實作）"))
            page_layout.addStretch(1)
            self.tabs.addTab(page, name)
        layout.addWidget(self.tabs, 1)

        # log 區
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        layout.addWidget(self.log_view, 1)

        self._restore_settings()
        # 跟隨系統模式下,監聽系統主題變更即時重套
        QApplication.instance().styleHints().colorSchemeChanged.connect(
            self._on_system_scheme_changed)

    # ---------- 主題 ----------
    def current_mode(self) -> str:
        return self.theme_combo.currentData()

    def _apply_current_theme(self) -> None:
        apply_theme(QApplication.instance(), self.current_mode())

    def _on_theme_changed(self) -> None:
        mode = self.current_mode()
        self.settings.setValue("theme_mode", mode)
        self._apply_current_theme()
        self.append_log(f"主題切換為:{_MODE_LABELS.get(mode, mode)}")

    def _on_system_scheme_changed(self, _scheme) -> None:
        if self.current_mode() == "system":
            self._apply_current_theme()

    # ---------- log ----------
    def append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    # ---------- 設定持久化 ----------
    def _restore_settings(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1000, 700)
        mode = self.settings.value("theme_mode", "system")
        index = self.theme_combo.findData(mode)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        self._apply_current_theme()

    def closeEvent(self, event) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("theme_mode", self.current_mode())
        super().closeEvent(event)


def main() -> None:
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec()
```

- [ ] **Step 2: 實作進入點**

建立 `ass_style_tool/qt/__main__.py`:

```python
from .main_window import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: import 檢查(不開視窗)**

Run: `py -c "import ass_style_tool.qt.main_window; print('qt import ok')"`
Expected: 輸出 `qt import ok`,無例外

- [ ] **Step 4: 啟動冒煙(自動,不做互動)**

在背景啟動視窗約 3 秒後關閉,確認啟動不崩潰:

```powershell
$p = Start-Process -FilePath "py" -ArgumentList "-m","ass_style_tool.qt" -WorkingDirectory $PWD -PassThru
Start-Sleep -Seconds 3
if ($p.HasExited) { Write-Output "FAIL: 啟動即退出,exit=$($p.ExitCode)" } else { Write-Output "OK: 視窗持續執行"; Stop-Process -Id $p.Id }
```

Expected: 輸出 `OK: 視窗持續執行`

- [ ] **Step 5: 跑全部自動化測試確認無回歸**

Run: `py -m pytest tests -v`
Expected: 110 passed(先前 92 + profile_fields 10 + theme 8)

- [ ] **Step 6: 手動冒煙清單(由使用者執行,記於報告)**

Run: `py -m ass_style_tool.qt`
人工確認:
1. 視窗開啟,標題「ASS 字幕樣式批次工具」,三個分頁籤(字幕檔/MKV/樣式與預覽)都在
2. 右上角「主題」下拉有「跟隨系統/深色/淺色」三項;預設為「跟隨系統」且外觀符合目前 Windows 深/淺色設定
3. 切「深色」→ 整個視窗變深色;切「淺色」→ 變淺色;log 區出現主題切換訊息
4. 選「跟隨系統」後,去 Windows 設定切換深/淺色,視窗即時跟著變
5. 關閉視窗再開,主題選擇與視窗大小/位置有被記住

- [ ] **Step 7: Commit**

```powershell
git add ass_style_tool/qt/main_window.py ass_style_tool/qt/__main__.py
git commit -m "feat: add Qt main window shell with theme switching and QSettings"
```

---

## 本計畫完成後

Qt 外殼就緒:深色/淺色/跟隨系統主題、分頁籤、log、設定持久化,外加兩個可測純邏輯模組。舊 tkinter 介面仍保留(`py -m ass_style_tool`)。接著:

- **Plan 2b — 樣式面板 + 字幕檔分頁**:把 v1 的散裝字幕批次流程搬進 Qt(用 profile_fields 建樣式面板、profile 下拉、字型未安裝警告、掃描預覽表格、背景執行緒批次 + 進度 + 開啟輸出資料夾),達到 v1 功能對等後,切換 `__main__` 進入點到 Qt 並移除 tkinter gui.py。
- **Plan 2c — mpv 預覽 + MKV 分頁**:內嵌 mpv 播放器、字幕行跳轉、MKV 字幕軌表格與重封裝(用 Plan 1 的 mkv_io)、取消。
- **Plan 3 — 打包**:PyInstaller + Inno Setup。
