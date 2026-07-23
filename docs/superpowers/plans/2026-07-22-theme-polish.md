# 主題樣式深化(方案 B)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓清單看得出列與列的分隔與選取狀態,並補上目前完全沒樣式的捲動條/群組框/進度條;深淺兩個主題視覺結構一致。

**Architecture:** 兩塊。`theme.py` 把兩份平行的 QSS 字串改成「一份共用 `string.Template` 樣板 + 每主題一組 `_Palette` 配色」,並把樣板擴充到涵蓋清單列、選取、hover、分頁強調線、強調按鈕、捲動條、群組框、進度條;另外在 8 個控件端各加一行樣式標記(交錯底色開關與強調按鈕屬性),因為這兩者無法只靠 QSS 生效。

**Tech Stack:** Python、PySide6(Qt Style Sheets、Fusion style)、`string.Template`、pytest。

## Global Constraints

- 一律用 `py`,不要用 `python`。測試從 repo root:`py -m pytest tests -q`。目前基線 **360 passed**,實作後維持全綠(新增測試使總數上升)。
- **不改任何控件位置、密度、字級或程式邏輯**。本次只加樣式與樣式標記。
- **用 `string.Template`(`$name` 佔位),不可用 `str.format`**:QSS 本身充滿 `{` `}`,`format` 會把樣式規則的大括號當佔位符而炸掉。
- **用 `Template.substitute`,不可用 `safe_substitute`**:配色表漏欄位時必須直接拋出,不可靜默產生殘留 `$border` 的壞 QSS。
- `qss_for(theme)` 的對外簽章與回傳型別維持不變(仍回傳 QSS 字串),`apply_theme`/`main_window`/既有測試不受影響。
- `apply_theme` 既有的「非 Fusion 就切成 Fusion」邏輯**必須保留**(Windows 原生樣式不完整遵守 QSS)。
- 不新增第三個主題,不動 `THEME_MODES`。
- 深色選取底色需白字、淺色選取底色需深字——因此 `selection_text` 是獨立的配色欄位,不可與 `accent_text` 共用。
- commit 訊息結尾加:`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- 環境:Bash 每次 `cd /c/Claude_code`。

---

## File Structure

- `ass_style_tool/qt/theme.py`(改寫上半部):`_Palette` dataclass、`_DARK`/`_LIGHT` 兩組配色、`_QSS_TEMPLATE`、`qss_for` 改為套版。下半部函式(`resolve_theme`/`system_is_dark`/`apply_theme`/`apply_titlebar_theme`)不動。
- `ass_style_tool/qt/mkv_tab.py:69,120`、`mux_tab.py:84,155`、`subtitle_tab.py:75,104`、`modify_tracks_dialog.py:35`、`readout_view.py:28`(各加一行樣式標記)。
- 測試:`tests/test_theme.py`(加)、`tests/test_mkv_tab.py`、`tests/test_mux_tab.py`、`tests/test_subtitle_tab.py`、`tests/test_modify_tracks_dialog.py`、`tests/test_readout_view.py`(各加)。

---

### Task 1: `theme.py` 配色表 + 共用樣板 + 擴充樣式

**Files:**
- Modify: `ass_style_tool/qt/theme.py:1-57`(第 60 行起的函式不動)
- Test: `tests/test_theme.py`

**Interfaces:**
- Produces:
  - `_Palette` frozen dataclass,欄位:`window_bg, text, text_dim, field_bg, row_alt, row_hover, border, border_light, surface, surface_hover, accent, accent_hover, accent_text, selection_bg, selection_text, disabled_text`(皆 `str`)
  - `_DARK: _Palette`、`_LIGHT: _Palette`
  - `_QSS_TEMPLATE: string.Template`
  - `qss_for(theme: str) -> str`(簽章不變)

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_theme.py` 末端加入:

```python
def test_qss_has_no_unsubstituted_placeholders():
    # 殘留的 $name 代表配色表漏了欄位,產生的 QSS 會壞掉
    for theme in ("dark", "light"):
        assert "$" not in qss_for(theme), f"{theme} 主題有殘留佔位符"


def test_qss_covers_new_widgets():
    for theme in ("dark", "light"):
        qss = qss_for(theme)
        for selector in ("QTreeWidget", "QScrollBar", "QGroupBox",
                         "QProgressBar", 'QPushButton[accent="true"]'):
            assert selector in qss, f"{theme} 主題缺少 {selector}"


def test_qss_has_row_separator_and_selection():
    for theme in ("dark", "light"):
        qss = qss_for(theme)
        assert "alternate-background-color" in qss      # 交錯底色
        assert "::item:selected" in qss                 # 選取高亮
        assert "::item:hover" in qss                    # hover 提示


def test_incomplete_palette_raises_loudly():
    # 配色表缺欄位必須直接拋出,不可靜默產生壞 QSS
    from ass_style_tool.qt.theme import _QSS_TEMPLATE
    with pytest.raises(KeyError):
        _QSS_TEMPLATE.substitute({"window_bg": "#000000"})
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_theme.py -q`
Expected: FAIL(`cannot import name '_QSS_TEMPLATE'`,以及 `QTreeWidget` 不在目前的 QSS 內)

- [ ] **Step 3: 換掉 `theme.py` 第 1-57 行**

把 `ass_style_tool/qt/theme.py` 從檔首到 `qss_for` 函式結尾(即目前的第 1-57 行)整段換成下列內容。**第 60 行起的 `system_is_dark`/`apply_theme`/`apply_titlebar_theme` 保持原樣不動。**

```python
"""主題模式(跟隨系統/深色/淺色)決策與 QSS 套用。

深淺兩個主題共用同一份 QSS 樣板,只有配色不同——兩份平行的樣式字串很容易
在日後只改一邊而悄悄分岔。用 string.Template 而非 str.format,因為 QSS 本身
充滿大括號;用 substitute 而非 safe_substitute,配色漏欄位時要直接拋出。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from string import Template
from typing import Tuple

THEME_MODES: Tuple[str, ...] = ("system", "dark", "light")


@dataclass(frozen=True)
class _Palette:
    window_bg: str        # 視窗底色
    text: str             # 主要文字
    text_dim: str         # 次要文字(表頭、未選分頁)
    field_bg: str         # 輸入框/清單底色
    row_alt: str          # 交錯列底色
    row_hover: str        # hover 列底色
    border: str           # 一般邊框
    border_light: str     # 列分隔線(比一般邊框更淡)
    surface: str          # 按鈕/分頁/表頭底色
    surface_hover: str    # 按鈕 hover
    accent: str           # 強調色(主要按鈕、分頁上緣線、進度條)
    accent_hover: str
    accent_text: str      # 強調色底上的文字
    selection_bg: str     # 選取列底色
    selection_text: str   # 選取列文字(深淺主題不同,故獨立欄位)
    disabled_text: str


_DARK = _Palette(
    window_bg="#1e1e1e", text="#e6e6e6", text_dim="#b8b8b8",
    field_bg="#252525", row_alt="#232323", row_hover="#2f2f2f",
    border="#3d3d3d", border_light="#333333",
    surface="#2d2d2d", surface_hover="#3a3a3a",
    accent="#0e639c", accent_hover="#1177bb", accent_text="#ffffff",
    selection_bg="#264f78", selection_text="#ffffff",
    disabled_text="#707070",
)

_LIGHT = _Palette(
    window_bg="#f3f3f3", text="#202020", text_dim="#505050",
    field_bg="#ffffff", row_alt="#f7f7f7", row_hover="#eaeaea",
    border="#c8c8c8", border_light="#e0e0e0",
    surface="#e8e8e8", surface_hover="#dcdcdc",
    accent="#0a6ebd", accent_hover="#0d82db", accent_text="#ffffff",
    selection_bg="#cce4f7", selection_text="#202020",
    disabled_text="#a0a0a0",
)

_QSS_TEMPLATE = Template("""
QMainWindow, QWidget { background-color: $window_bg; color: $text; }

QTabWidget::pane { border: 1px solid $border; }
QTabBar::tab {
    background: $surface; color: $text_dim; padding: 6px 14px;
    border-top: 2px solid transparent;
}
QTabBar::tab:selected {
    background: $window_bg; color: $text; border-top: 2px solid $accent;
}

QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit {
    background-color: $field_bg; color: $text; border: 1px solid $border;
    selection-background-color: $selection_bg; selection-color: $selection_text;
}

QTreeWidget, QTableWidget {
    background-color: $field_bg; color: $text; border: 1px solid $border;
    alternate-background-color: $row_alt;
    gridline-color: $border_light;
    selection-background-color: $selection_bg;
    selection-color: $selection_text;
}
QTreeWidget::item, QTableWidget::item {
    border-bottom: 1px solid $border_light;
}
QTreeWidget::item:hover, QTableWidget::item:hover {
    background-color: $row_hover;
}
QTreeWidget::item:selected, QTableWidget::item:selected {
    background-color: $selection_bg; color: $selection_text;
}

QHeaderView::section {
    background-color: $surface; color: $text_dim;
    border: 1px solid $border; padding: 4px;
}

QPushButton {
    background-color: $surface; color: $text; border: 1px solid $border;
    padding: 5px 12px; border-radius: 3px;
}
QPushButton:hover { background-color: $surface_hover; }
QPushButton:disabled { color: $disabled_text; background-color: $field_bg; }
QPushButton[accent="true"] {
    background-color: $accent; color: $accent_text;
    border: 1px solid $accent_hover;
}
QPushButton[accent="true"]:hover { background-color: $accent_hover; }
QPushButton[accent="true"]:disabled {
    background-color: $field_bg; color: $disabled_text;
    border: 1px solid $border;
}

QScrollBar:vertical { background: $surface; width: 12px; margin: 0; }
QScrollBar::handle:vertical {
    background: $border; min-height: 24px; border-radius: 3px;
}
QScrollBar::handle:vertical:hover { background: $surface_hover; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: $surface; height: 12px; margin: 0; }
QScrollBar::handle:horizontal {
    background: $border; min-width: 24px; border-radius: 3px;
}
QScrollBar::handle:horizontal:hover { background: $surface_hover; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QGroupBox {
    border: 1px solid $border; border-radius: 3px;
    margin-top: 8px; padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 8px; padding: 0 4px; color: $text_dim;
}

QProgressBar {
    background-color: $field_bg; border: 1px solid $border;
    border-radius: 3px; text-align: center; color: $text;
}
QProgressBar::chunk { background-color: $accent; }
""")


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
    palette = _DARK if theme == "dark" else _LIGHT
    return _QSS_TEMPLATE.substitute(asdict(palette))
```

檔案頂部原有的 `from typing import Tuple` 已包含在上面的新內容中,不要重複匯入。

在 `tests/test_theme.py` 頂部確認有 `import pytest`(檔案原本就有)。

- [ ] **Step 4: 跑測試確認通過**

Run: `py -m pytest tests/test_theme.py -q`
Expected: PASS(既有 9 個 + 新增 4 個)

- [ ] **Step 5: 全套回歸**

Run: `py -m pytest tests -q`
Expected: PASS(360 + 4,全綠)

- [ ] **Step 6: Commit**

```bash
git add ass_style_tool/qt/theme.py tests/test_theme.py
git commit -m "Expand the theme QSS and share one template between modes

Lists now get row separators, alternating rows, hover and a selection
highlight; adds tab accent, accent primary buttons, and scrollbar/groupbox/
progressbar styling that did not exist at all. The two parallel QSS strings
become one string.Template plus a per-theme palette so they cannot drift;
substitute() (not safe_substitute) makes a missing colour fail loudly.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: 控件端樣式標記(交錯底色 + 強調按鈕)

**Files:**
- Modify: `ass_style_tool/qt/mkv_tab.py:69,120`、`ass_style_tool/qt/mux_tab.py:84,155`、`ass_style_tool/qt/subtitle_tab.py:75,104`、`ass_style_tool/qt/modify_tracks_dialog.py:35`、`ass_style_tool/qt/readout_view.py:28`
- Test: `tests/test_mkv_tab.py`、`tests/test_mux_tab.py`、`tests/test_subtitle_tab.py`、`tests/test_modify_tracks_dialog.py`、`tests/test_readout_view.py`

**Interfaces:**
- Consumes: Task 1 的 `QPushButton[accent="true"]` 選擇器與 `alternate-background-color` 規則。
- Produces: 5 個表格/樹狀控件 `alternatingRowColors()` 為 `True`;3 個主要按鈕 `property("accent")` 為 `True`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_mkv_tab.py` 末端加入(檔案已有 `_tab(monkeypatch)` helper):

```python
def test_tree_has_alternating_rows(qapp, monkeypatch):
    # QSS 的 alternate-background-color 只有在控件端開啟時才生效
    tab = _tab(monkeypatch)
    assert tab.tree.alternatingRowColors() is True


def test_run_button_tagged_accent(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.run_button.property("accent") is True
```

在 `tests/test_mux_tab.py` 末端加入(檔案已有 `_tab(monkeypatch)` helper):

```python
def test_table_has_alternating_rows(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.table.alternatingRowColors() is True


def test_run_button_tagged_accent(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.run_button.property("accent") is True
```

在 `tests/test_subtitle_tab.py` 末端加入:

```python
def test_table_has_alternating_rows(qapp):
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    assert tab.table.alternatingRowColors() is True


def test_run_button_tagged_accent(qapp):
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    assert tab.run_button.property("accent") is True
```

在 `tests/test_modify_tracks_dialog.py` 末端加入(檔案已有 `_tracks()` helper):

```python
def test_table_has_alternating_rows(qapp):
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_tracks())
    assert d.table.alternatingRowColors() is True
```

在 `tests/test_readout_view.py` 末端加入:

```python
def test_table_has_alternating_rows(qapp):
    from ass_style_tool.qt.readout_view import ReadoutView
    v = ReadoutView()
    assert v.table.alternatingRowColors() is True
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_mkv_tab.py tests/test_mux_tab.py tests/test_subtitle_tab.py tests/test_modify_tracks_dialog.py tests/test_readout_view.py -k "alternating or accent" -q`
Expected: FAIL(8 個測試,`assert False is True`)

- [ ] **Step 3: 加交錯底色開關(5 處)**

各在該控件建立的那一行**之後**插入一行:

`ass_style_tool/qt/mkv_tab.py`,`self.tree = QTreeWidget()` 之後:
```python
        self.tree.setAlternatingRowColors(True)
```

`ass_style_tool/qt/mux_tab.py`,`self.table = QTableWidget(0, len(_HEADERS))` 之後:
```python
        self.table.setAlternatingRowColors(True)
```

`ass_style_tool/qt/subtitle_tab.py`,`self.table = QTableWidget(0, len(_HEADERS))` 之後:
```python
        self.table.setAlternatingRowColors(True)
```

`ass_style_tool/qt/modify_tracks_dialog.py`,`self.table = QTableWidget(len(self._tracks), len(_COLS))` 之後:
```python
        self.table.setAlternatingRowColors(True)
```

`ass_style_tool/qt/readout_view.py`,`self.table = QTableWidget(0, 3)` 之後:
```python
        self.table.setAlternatingRowColors(True)
```

- [ ] **Step 4: 加強調按鈕標記(3 處)**

各在該按鈕建立的那一行**之後**插入一行(QSS 用 `QPushButton[accent="true"]` 選取):

`ass_style_tool/qt/mkv_tab.py`,`self.run_button = QPushButton("開始處理")` 之後:
```python
        self.run_button.setProperty("accent", True)
```

`ass_style_tool/qt/mux_tab.py`,`self.run_button = QPushButton("開始封裝")` 之後:
```python
        self.run_button.setProperty("accent", True)
```

`ass_style_tool/qt/subtitle_tab.py`,`self.run_button = QPushButton("開始套用樣式")` 之後:
```python
        self.run_button.setProperty("accent", True)
```

- [ ] **Step 5: 跑新測試確認通過**

Run: `py -m pytest tests/test_mkv_tab.py tests/test_mux_tab.py tests/test_subtitle_tab.py tests/test_modify_tracks_dialog.py tests/test_readout_view.py -q`
Expected: PASS(全綠)

- [ ] **Step 6: 全套回歸**

Run: `py -m pytest tests -q`
Expected: PASS(364 + 8 = 372,全綠)

- [ ] **Step 7: Commit**

```bash
git add ass_style_tool/qt/mkv_tab.py ass_style_tool/qt/mux_tab.py ass_style_tool/qt/subtitle_tab.py ass_style_tool/qt/modify_tracks_dialog.py ass_style_tool/qt/readout_view.py tests/test_mkv_tab.py tests/test_mux_tab.py tests/test_subtitle_tab.py tests/test_modify_tracks_dialog.py tests/test_readout_view.py
git commit -m "Tag widgets so the new theme rules actually apply

alternate-background-color only takes effect when the widget has
alternatingRowColors enabled, and QSS cannot tell which button is the
primary action -- both need a marker on the widget itself. Enables
alternating rows on the five lists and tags the three run buttons.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- 表格/樹狀清單:列分隔、交錯底色、hover、選取高亮 → Task 1 樣板 + Task 2 交錯開關 ✓
- 分頁籤上緣強調線(含未選中用透明邊框保持等高)→ Task 1 ✓
- 主要按鈕強調色 → Task 1 選擇器 + Task 2 屬性標記 ✓
- 補捲動條/群組框/進度條 → Task 1 ✓
- 淺色對應版本 → Task 1 `_LIGHT` ✓
- 共用樣板 + 配色表(防止兩主題分岔)→ Task 1 ✓
- `Template` 而非 `format`、`substitute` 而非 `safe_substitute` → Task 1 Step 3 + `test_incomplete_palette_raises_loudly` ✓
- `qss_for` 簽章不變、`apply_theme` Fusion 邏輯保留 → Task 1 Step 3 明示只換第 1-57 行 ✓
- `selection_text` 獨立欄位(深淺主題選取文字色不同)→ Task 1 `_Palette` ✓
- 不改位置/密度/邏輯 → 兩個 Task 都只加樣式與單行標記 ✓
- 測試計畫各項 → 各 Task 涵蓋 ✓

**2. Placeholder scan:** 無 TBD/TODO;每個 code step 均含完整程式碼與可執行指令。

**3. Type consistency:** `_Palette` 的 16 個欄位名與 `_QSS_TEMPLATE` 內的 `$name` 佔位符一一對應(window_bg, text, text_dim, field_bg, row_alt, row_hover, border, border_light, surface, surface_hover, accent, accent_hover, accent_text, selection_bg, selection_text, disabled_text 全數在樣板中出現且無多餘佔位符);`qss_for` 簽章與既有呼叫端一致;Task 2 的 `property("accent")` 與 Task 1 的 `QPushButton[accent="true"]` 選擇器一致。

## 範圍外(本計畫不做)

- 控件位置調整、分頁重新排版、密度/字級/字型變更。
- 參考工具的「Information About Tracks」每檔軌道資訊面板(獨立新功能)。
