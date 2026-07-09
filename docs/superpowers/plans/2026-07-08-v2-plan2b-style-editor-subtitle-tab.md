# v2 Plan 2b — 樣式面板 + 字幕檔分頁 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 v1 的散裝字幕批次流程完整搬進 PySide6 介面——樣式編輯面板(含色彩選擇器、profile 存讀、字型未安裝警告)與「字幕檔」分頁(選/拖資料夾、掃描預覽表格、背景執行緒批次 + 進度 + 取消、輸出模式、開啟輸出資料夾),達到 v1 功能對等後切換 `py -m ass_style_tool` 進入點到 Qt 並移除舊 tkinter GUI。

**Architecture:** 非 Qt 的純邏輯(預覽表格列建構、字型缺失判斷)抽成可測函式;Qt widget 用 offscreen QApplication 做自動化測試(取/設值、Profile 產生、表格填列),視覺與互動用手動清單。批次執行復用 v1 已測的 `batch_runner.process_file`,由 QThread worker 逐檔呼叫以支援「取消」,進度/log 經 Qt signal 回主執行緒。

**Tech Stack:** PySide6(Qt 6.6+)、pytest(offscreen Qt)。

**Spec:** `docs/superpowers/specs/2026-07-08-ass-style-tool-v2-design.md`

## Global Constraints

- 工作目錄/repo root:`C:\Claude_code`,git branch 由執行者依 subagent-driven 流程建立
- **環境重點**:`python` 是壞的 Windows Store stub,一律用 `py`:`py -m pytest tests -v`、`py -m ass_style_tool`
- Python 3.9+ 相容;每個新模組頂端加 `from __future__ import annotations`
- Qt 自動化測試一律用 offscreen 平台:測試透過 `tests/conftest.py` 在 import Qt 前設 `os.environ["QT_QPA_PLATFORM"]="offscreen"` 並提供共用 `qapp` fixture
- 不動 v1 核心模組(profile/resolution/ass_style/episode_match/batch_runner)與其測試
- 不動已合入的 v2 模組(tools/mkv_io/preview/profile_fields)與 qt/theme.py、qt/main_window.py 的既有行為,除非任務明確要求修改
- 批次執行**不修改** `batch_runner.py`;worker 逐檔呼叫公開的 `batch_runner.process_file(match, profile, output_dir)` 以支援取消
- 輸出模式沿用 v1 語意:原地覆蓋(先備份 `.bak`)或輸出到新資料夾;`process_file` 已實作,不重寫
- QSettings 沿用 `QSettings("ass-style-tool", "ass-style-tool")`
- 測試指令:`py -m pytest tests -v`(從 repo root)
- Commit 訊息用 conventional commits

### 既有介面(本計畫會用到,已實作且測試)

- `ass_style_tool.profile_fields`:`FIELD_KEYS: tuple[str,...]`、`DEFAULT_VALUES: dict`、`profile_from_values(values) -> Profile`(非法丟 ValueError)、`values_from_profile(profile) -> dict`
- `ass_style_tool.profile`:`Profile`、`load_profile(path) -> Profile`、`save_profile(profile, path)`、`parse_ass_color(text) -> pysubs2.Color`
- `ass_style_tool.batch_runner`:`scan_folder(folder) -> ScanResult`(欄位 `matches: list[MatchResult]`, `warnings: list[str]`)、`process_file(match, profile, output_dir) -> FileReport`(欄位 `sub_path: Path`, `status: str`(ok|skipped|error), `messages: list[str]`)
- `ass_style_tool.episode_match.MatchResult`:欄位 `sub_path: Path`, `episode: int|None`, `video_path: Path|None`, `video_resolution: tuple[int,int]|None`, `status: str`(matched|no_video|ambiguous|no_episode)
- `ass_style_tool.qt.main_window.MainWindow`:既有分頁佔位、`append_log(text)`、`self.tabs`(QTabWidget)、`current_mode()`

## File Structure

```
ass_style_tool/qt/
├── gui_helpers.py       # 純邏輯:preview_rows(scan)->list[Row]、font_is_missing(name, families)
├── style_editor.py      # StyleEditor(QWidget):欄位、色彩選擇器、profile 存讀、字型警告
├── batch_worker.py      # BatchWorker(QObject):QThread 逐檔跑 process_file,支援取消
├── subtitle_tab.py      # SubtitleFileTab(QWidget):資料夾、掃描表格、輸出模式、執行/取消
└── main_window.py       # (修改)把 StyleEditor 與 SubtitleFileTab 接進分頁;切換進入點
tests/
├── conftest.py          # offscreen QApplication fixture
├── test_gui_helpers.py
├── test_style_editor.py
└── test_subtitle_tab.py
```

移除(達成 v1 對等後):`ass_style_tool/gui.py`(舊 tkinter)、`ass_style_tool/__main__.py` 改為啟動 Qt、`tests/`（若有針對舊 tkinter gui 的測試則一併移除——實際上 v1 未對 tkinter gui 寫自動化測試,僅手動冒煙,故無測試檔要刪)。

---

### Task 1: gui_helpers.py — 純邏輯輔助(可測)

**Files:**
- Create: `ass_style_tool/qt/gui_helpers.py`
- Test: `tests/test_gui_helpers.py`

**Interfaces:**
- Consumes: `episode_match.MatchResult`、`batch_runner.ScanResult`
- Produces:
  - `STATUS_LABELS: dict[str,str]` — MatchResult.status → 中文(matched/no_video/ambiguous/no_episode)
  - `PreviewRow` dataclass:`episode: str, sub_name: str, video_name: str, status_label: str`
  - `preview_rows(scan) -> list[PreviewRow]` — 從 ScanResult.matches 建預覽表格列
  - `font_is_missing(fontname: str, available_families: list[str]) -> bool` — 大小寫不敏感比對;fontname 去空白後為空回 False

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_gui_helpers.py`:

```python
from __future__ import annotations

from pathlib import Path

from ass_style_tool.batch_runner import ScanResult
from ass_style_tool.episode_match import MatchResult
from ass_style_tool.qt.gui_helpers import (PreviewRow, font_is_missing,
                                           preview_rows)


def test_preview_rows_matched():
    scan = ScanResult(matches=[
        MatchResult(sub_path=Path("a [01].ass"), episode=1,
                    video_path=Path("v01.mkv"),
                    video_resolution=(1920, 1080), status="matched"),
    ], warnings=[])
    rows = preview_rows(scan)
    assert len(rows) == 1
    r = rows[0]
    assert r.episode == "01"
    assert r.sub_name == "a [01].ass"
    assert r.video_name == "v01.mkv"
    assert r.status_label == "已配對"


def test_preview_rows_no_video_and_no_episode():
    scan = ScanResult(matches=[
        MatchResult(sub_path=Path("x [03].ass"), episode=3,
                    video_path=None, status="no_video"),
        MatchResult(sub_path=Path("opening.ass"), episode=None,
                    status="no_episode"),
    ], warnings=[])
    rows = preview_rows(scan)
    assert rows[0].video_name == "-"
    assert rows[0].episode == "03"
    assert rows[0].status_label == "無對應影片"
    assert rows[1].episode == "?"
    assert rows[1].status_label == "無法判斷集數"


def test_preview_rows_ambiguous():
    scan = ScanResult(matches=[
        MatchResult(sub_path=Path("a [01].ass"), episode=1, status="ambiguous"),
    ], warnings=[])
    assert preview_rows(scan)[0].status_label == "配對模糊"


def test_font_missing_true():
    assert font_is_missing("思源黑體 CN", ["Arial", "Microsoft JhengHei"]) is True


def test_font_missing_false_case_insensitive():
    assert font_is_missing("arial", ["Arial", "MS Gothic"]) is False


def test_font_missing_empty_name_is_not_missing():
    assert font_is_missing("  ", ["Arial"]) is False
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_gui_helpers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.qt.gui_helpers'`

- [ ] **Step 3: 實作 gui_helpers.py**

建立 `ass_style_tool/qt/gui_helpers.py`:

```python
"""GUI 用的純邏輯輔助:預覽表格列建構、字型缺失判斷(不依賴 Qt)。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

STATUS_LABELS = {
    "matched": "已配對",
    "no_video": "無對應影片",
    "ambiguous": "配對模糊",
    "no_episode": "無法判斷集數",
}


@dataclass
class PreviewRow:
    episode: str
    sub_name: str
    video_name: str
    status_label: str


def preview_rows(scan) -> List[PreviewRow]:
    rows: List[PreviewRow] = []
    for m in scan.matches:
        episode = f"{m.episode:02d}" if m.episode is not None else "?"
        video = m.video_path.name if m.video_path is not None else "-"
        rows.append(PreviewRow(
            episode=episode,
            sub_name=m.sub_path.name,
            video_name=video,
            status_label=STATUS_LABELS.get(m.status, m.status),
        ))
    return rows


def font_is_missing(fontname: str, available_families: List[str]) -> bool:
    name = fontname.strip().lower()
    if not name:
        return False
    return name not in {fam.lower() for fam in available_families}
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_gui_helpers.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```powershell
git add ass_style_tool/qt/gui_helpers.py tests/test_gui_helpers.py
git commit -m "feat: add pure GUI helpers (preview rows, font-missing check)"
```

---

### Task 2: style_editor.py — 樣式編輯面板

**Files:**
- Create: `ass_style_tool/qt/style_editor.py`
- Create: `tests/conftest.py`
- Test: `tests/test_style_editor.py`

**Interfaces:**
- Consumes: `profile_fields.FIELD_KEYS/DEFAULT_VALUES/profile_from_values/values_from_profile`、`profile.Profile/load_profile/save_profile/parse_ass_color`、`gui_helpers.font_is_missing`
- Produces:
  - `StyleEditor(QWidget)`:
    - `set_values(values: dict) -> None` — 依欄位字典填入控件
    - `get_values() -> dict` — 從控件讀出欄位字典(bold/italic 為 bool,其餘字串)
    - `current_profile() -> Profile` — 用 `profile_from_values(self.get_values())`,非法丟 ValueError
    - `load_profile_from(path) -> None` — 讀 JSON 並填入
    - `font_warning_visible() -> bool` — 目前字型是否被標記為未安裝
    - `refresh_font_warning() -> None` — 依系統字型清單更新警告顯示

- [ ] **Step 1: 建立 offscreen conftest**

建立 `tests/conftest.py`:

```python
"""pytest 共用設定:讓 Qt 測試在無顯示器環境以 offscreen 平台執行。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
```

- [ ] **Step 2: 寫失敗測試**

建立 `tests/test_style_editor.py`:

```python
from __future__ import annotations

from ass_style_tool.profile import Profile
from ass_style_tool.profile_fields import DEFAULT_VALUES, values_from_profile


def test_get_values_roundtrip(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    editor.set_values(DEFAULT_VALUES)
    values = editor.get_values()
    # 關鍵欄位讀回一致
    assert values["fontname"] == DEFAULT_VALUES["fontname"]
    assert values["target_style_names"] == DEFAULT_VALUES["target_style_names"]
    assert str(values["fontsize"]) == str(DEFAULT_VALUES["fontsize"])
    assert bool(values["bold"]) == bool(DEFAULT_VALUES["bold"])
    assert values["alignment"] == DEFAULT_VALUES["alignment"]


def test_current_profile_from_defaults(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    editor.set_values(DEFAULT_VALUES)
    profile = editor.current_profile()
    assert isinstance(profile, Profile)
    assert profile.style.fontname == DEFAULT_VALUES["fontname"]
    assert profile.base_width == 1920


def test_set_values_from_profile_roundtrip(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    from ass_style_tool.profile_fields import profile_from_values
    editor = StyleEditor()
    p0 = profile_from_values(DEFAULT_VALUES)
    editor.set_values(values_from_profile(p0))
    assert editor.current_profile() == p0


def test_invalid_fontsize_raises(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    editor.set_values(DEFAULT_VALUES)
    editor.set_values({**DEFAULT_VALUES, "fontsize": "big"})
    import pytest
    with pytest.raises(ValueError):
        editor.current_profile()


def test_font_warning_toggles(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    # 一個幾乎不可能安裝的字型名 → 應標記未安裝
    editor.set_values({**DEFAULT_VALUES, "fontname": "NoSuchFont ZZZ 12345"})
    editor.refresh_font_warning()
    assert editor.font_warning_visible() is True
```

- [ ] **Step 3: 執行測試,確認失敗**

Run: `py -m pytest tests/test_style_editor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.qt.style_editor'`

- [ ] **Step 4: 實作 style_editor.py**

建立 `ass_style_tool/qt/style_editor.py`:

```python
"""樣式編輯面板:欄位、色彩選擇器、profile 存讀、字型未安裝警告。"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)
from PySide6.QtWidgets import QColorDialog
from PySide6.QtGui import QColor, QFontDatabase

from ..profile import (Profile, load_profile, parse_ass_color, save_profile)
from ..profile_fields import (DEFAULT_VALUES, profile_from_values,
                              values_from_profile)
from .gui_helpers import font_is_missing

# 欄位分組(標籤, 欄位鍵)
_TEXT_FIELDS = [
    ("設定檔名稱", "profile_name"),
    ("目標 Style(逗號分隔)", "target_style_names"),
    ("字型名稱", "fontname"),
    ("字體大小", "fontsize"),
    ("外框寬度", "outline"),
    ("陰影深度", "shadow"),
    ("對齊(1-9)", "alignment"),
    ("邊距 L", "margin_l"),
    ("邊距 R", "margin_r"),
    ("邊距 V", "margin_v"),
    ("基準寬", "base_width"),
    ("基準高", "base_height"),
]
_COLOR_FIELDS = [
    ("主色", "primary_colour"),
    ("外框色", "outline_colour"),
    ("陰影色", "back_colour"),
]


def _ass_to_qcolor(ass: str) -> QColor:
    c = parse_ass_color(ass)
    return QColor(c.r, c.g, c.b)


def _qcolor_to_ass(color: QColor, alpha_ass: str) -> str:
    try:
        a = parse_ass_color(alpha_ass).a
    except ValueError:
        a = 0
    return f"&H{a:02X}{color.blue():02X}{color.green():02X}{color.red():02X}"


class StyleEditor(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._edits: Dict[str, QLineEdit] = {}
        self._checks: Dict[str, QCheckBox] = {}

        root = QVBoxLayout(self)

        # profile 下拉 + 存讀
        profile_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setEditable(False)
        profile_row.addWidget(QLabel("設定檔:"))
        profile_row.addWidget(self.profile_combo, 1)
        load_btn = QPushButton("載入")
        load_btn.clicked.connect(self._on_load_selected)
        save_btn = QPushButton("另存")
        save_btn.clicked.connect(self._on_save_as)
        profile_row.addWidget(load_btn)
        profile_row.addWidget(save_btn)
        root.addLayout(profile_row)

        form = QFormLayout()
        for label, key in _TEXT_FIELDS:
            edit = QLineEdit()
            self._edits[key] = edit
            form.addRow(label, edit)
            if key == "fontname":
                edit.textChanged.connect(self.refresh_font_warning)

        # 字型未安裝警告(接在字型欄位之後顯示)
        self.font_warning = QLabel("⚠ 系統未安裝此字型,播放器會改用預設字型")
        self.font_warning.setStyleSheet("color: #d08a00;")
        self.font_warning.setVisible(False)
        form.addRow("", self.font_warning)

        # 粗體/斜體
        self._checks["bold"] = QCheckBox("粗體")
        self._checks["italic"] = QCheckBox("斜體")
        flags = QHBoxLayout()
        flags.addWidget(self._checks["bold"])
        flags.addWidget(self._checks["italic"])
        flags.addStretch(1)
        form.addRow("樣式", self._wrap(flags))

        # 色彩欄位:文字 + 選色按鈕
        for label, key in _COLOR_FIELDS:
            edit = QLineEdit()
            self._edits[key] = edit
            btn = QPushButton("選色…")
            btn.clicked.connect(lambda _=False, k=key: self._pick_color(k))
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            row.addWidget(btn)
            form.addRow(label, self._wrap(row))

        root.addLayout(form)
        root.addStretch(1)

        self.set_values(DEFAULT_VALUES)
        self._refresh_profile_list()

    # ---------- 小工具 ----------
    def _wrap(self, layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def profiles_dir(self) -> Path:
        return Path.cwd() / "profiles"

    # ---------- 取/設值 ----------
    def set_values(self, values: dict) -> None:
        for key, edit in self._edits.items():
            if key in values:
                edit.setText(str(values[key]))
        for key, check in self._checks.items():
            if key in values:
                check.setChecked(bool(values[key]))
        self.refresh_font_warning()

    def get_values(self) -> dict:
        values: dict = {}
        for key, edit in self._edits.items():
            values[key] = edit.text()
        for key, check in self._checks.items():
            values[key] = check.isChecked()
        return values

    def current_profile(self) -> Profile:
        return profile_from_values(self.get_values())

    # ---------- 色彩 ----------
    def _pick_color(self, key: str) -> None:
        edit = self._edits[key]
        try:
            initial = _ass_to_qcolor(edit.text())
        except ValueError:
            initial = QColor(255, 255, 255)
        chosen = QColorDialog.getColor(initial, self, "選擇顏色")
        if chosen.isValid():
            edit.setText(_qcolor_to_ass(chosen, edit.text()))

    # ---------- 字型警告 ----------
    def refresh_font_warning(self) -> None:
        families = QFontDatabase.families()
        missing = font_is_missing(self._edits["fontname"].text(), list(families))
        self.font_warning.setVisible(missing)

    def font_warning_visible(self) -> bool:
        # 用 isHidden 反映「意圖顯示」狀態:isVisible() 在 widget 尚未 show 時
        # (含 offscreen 測試)即使 setVisible(True) 也回傳 False。
        return not self.font_warning.isHidden()

    # ---------- profile 存讀 ----------
    def _refresh_profile_list(self) -> None:
        self.profile_combo.clear()
        d = self.profiles_dir()
        if d.is_dir():
            for p in sorted(d.glob("*.json")):
                self.profile_combo.addItem(p.name, str(p))

    def load_profile_from(self, path) -> None:
        self.set_values(values_from_profile(load_profile(Path(path))))

    def _on_load_selected(self) -> None:
        path = self.profile_combo.currentData()
        if not path:
            return
        try:
            self.load_profile_from(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "載入失敗", str(exc))

    def _on_save_as(self) -> None:
        try:
            profile = self.current_profile()
        except ValueError as exc:
            QMessageBox.critical(self, "欄位錯誤", str(exc))
            return
        self.profiles_dir().mkdir(parents=True, exist_ok=True)
        default = str(self.profiles_dir() / f"{profile.profile_name}.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "另存設定檔", default, "JSON (*.json)")
        if not path:
            return
        try:
            save_profile(profile, Path(path))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "儲存失敗", str(exc))
            return
        self._refresh_profile_list()
```

- [ ] **Step 5: 執行測試,確認通過**

Run: `py -m pytest tests/test_style_editor.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/qt/style_editor.py tests/conftest.py tests/test_style_editor.py
git commit -m "feat: add Qt style editor panel with color picker, profile I/O, font warning"
```

---

### Task 3: batch_worker.py + subtitle_tab.py — 字幕檔分頁

**Files:**
- Create: `ass_style_tool/qt/batch_worker.py`
- Create: `ass_style_tool/qt/subtitle_tab.py`
- Test: `tests/test_subtitle_tab.py`

**Interfaces:**
- Consumes: `batch_runner.scan_folder/process_file`、`gui_helpers.preview_rows`、`style_editor.StyleEditor`、`episode_match.MatchResult`
- Produces:
  - `BatchWorker(QObject)`:signals `progress(int, int)`(已完成數, 總數)、`file_done(str, str)`(檔名, 狀態)、`finished(int, int, int)`(ok, skipped, error);method `run()`(逐檔跑 process_file,檢查 `self._cancelled`);method `cancel()`
  - `SubtitleFileTab(QWidget)`:建構子收一個 `get_profile: Callable[[], Profile]`;內含資料夾輸入、掃描按鈕、預覽表格、輸出模式、執行/取消按鈕;method `populate_preview(scan)`(把 preview_rows 填入表格,回傳填入列數)

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_subtitle_tab.py`:

```python
from __future__ import annotations

from pathlib import Path

from ass_style_tool.batch_runner import ScanResult
from ass_style_tool.episode_match import MatchResult
from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values


def _scan():
    return ScanResult(matches=[
        MatchResult(sub_path=Path("a [01].ass"), episode=1,
                    video_path=Path("v01.mkv"), status="matched"),
        MatchResult(sub_path=Path("b [02].ass"), episode=2,
                    video_path=None, status="no_video"),
    ], warnings=[])


def test_populate_preview_fills_table(qapp):
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    n = tab.populate_preview(_scan())
    assert n == 2
    assert tab.table.rowCount() == 2
    # 第一列的字幕檔名欄位
    assert tab.table.item(0, 1).text() == "a [01].ass"


def test_run_button_disabled_until_scan(qapp):
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    assert tab.run_button.isEnabled() is False
    tab.populate_preview(_scan())
    assert tab.run_button.isEnabled() is True


def test_batch_worker_runs_and_reports(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import BatchWorker
    from tests.test_ass_style import SAMPLE_ASS
    sub = tmp_path / "a [01].ass"
    sub.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    scan = ScanResult(matches=[
        MatchResult(sub_path=sub, episode=1, status="no_video"),
    ], warnings=[])
    profile = profile_from_values(DEFAULT_VALUES)
    worker = BatchWorker(scan, profile, output_dir=tmp_path / "out")
    seen = []
    worker.file_done.connect(lambda name, status: seen.append((name, status)))
    results = {}
    worker.finished.connect(
        lambda ok, sk, er: results.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert results == {"ok": 1, "skipped": 0, "error": 0}
    assert seen == [("a [01].ass", "ok")]
    assert (tmp_path / "out" / "a [01].ass").exists()


def test_batch_worker_cancel_stops_early(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import BatchWorker
    from tests.test_ass_style import SAMPLE_ASS
    matches = []
    for i in (1, 2, 3):
        sub = tmp_path / f"a [{i:02d}].ass"
        sub.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
        matches.append(MatchResult(sub_path=sub, episode=i, status="no_video"))
    scan = ScanResult(matches=matches, warnings=[])
    profile = profile_from_values(DEFAULT_VALUES)
    worker = BatchWorker(scan, profile, output_dir=tmp_path / "out")
    # 第一個檔完成後就取消
    worker.file_done.connect(lambda name, status: worker.cancel())
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    # 取消後總處理數應少於 3
    assert done["ok"] < 3
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_subtitle_tab.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.qt.batch_worker'`

- [ ] **Step 3: 實作 batch_worker.py**

建立 `ass_style_tool/qt/batch_worker.py`:

```python
"""批次執行 worker:在 QThread 中逐檔呼叫 process_file,支援取消。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from ..batch_runner import process_file
from ..profile import Profile


class BatchWorker(QObject):
    progress = Signal(int, int)        # 已完成, 總數
    file_done = Signal(str, str)       # 檔名, 狀態(ok|skipped|error)
    message = Signal(str)              # 單行 log
    finished = Signal(int, int, int)   # ok, skipped, error

    def __init__(self, scan, profile: Profile,
                 output_dir: Optional[Path]) -> None:
        super().__init__()
        self._matches = list(scan.matches)
        self._profile = profile
        self._output_dir = output_dir
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._matches)
        ok = skipped = error = 0
        for i, match in enumerate(self._matches, start=1):
            if self._cancelled:
                self.message.emit("已取消,停止後續檔案")
                break
            report = process_file(match, self._profile, self._output_dir)
            if report.status == "ok":
                ok += 1
            elif report.status == "skipped":
                skipped += 1
            else:
                error += 1
            self.file_done.emit(report.sub_path.name, report.status)
            for msg in report.messages:
                self.message.emit(f"    {msg}")
            self.progress.emit(i, total)
        self.finished.emit(ok, skipped, error)
```

- [ ] **Step 4: 實作 subtitle_tab.py**

建立 `ass_style_tool/qt/subtitle_tab.py`:

```python
"""「字幕檔」分頁:選/拖資料夾、掃描預覽、批次執行(執行緒)+ 進度 + 取消。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QRadioButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..batch_runner import scan_folder
from ..profile import Profile
from .batch_worker import BatchWorker
from .gui_helpers import preview_rows

_HEADERS = ["集數", "字幕檔", "影片檔", "狀態"]


class SubtitleFileTab(QWidget):
    log = Signal(str)

    def __init__(self, get_profile: Callable[[], Profile]) -> None:
        super().__init__()
        self._get_profile = get_profile
        self._scan = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[BatchWorker] = None
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("資料夾:"))
        self.folder_edit = QLineEdit()
        folder_row.addWidget(self.folder_edit, 1)
        browse = QPushButton("瀏覽…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(browse)
        root.addLayout(folder_row)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        # 輸出模式
        out_row = QHBoxLayout()
        self.inplace_radio = QRadioButton("原地覆蓋(備份 .bak)")
        self.inplace_radio.setChecked(True)
        self.outdir_radio = QRadioButton("輸出到資料夾:")
        self.outdir_edit = QLineEdit()
        out_browse = QPushButton("…")
        out_browse.clicked.connect(self._browse_out)
        out_row.addWidget(self.inplace_radio)
        out_row.addWidget(self.outdir_radio)
        out_row.addWidget(self.outdir_edit, 1)
        out_row.addWidget(out_browse)
        root.addLayout(out_row)

        action_row = QHBoxLayout()
        self.scan_button = QPushButton("掃描並預覽配對")
        self.scan_button.clicked.connect(self._on_scan)
        self.run_button = QPushButton("開始套用樣式")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._on_run)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        self.open_out_button = QPushButton("開啟輸出資料夾")
        self.open_out_button.clicked.connect(self._open_output)
        action_row.addWidget(self.scan_button)
        action_row.addWidget(self.run_button)
        action_row.addWidget(self.cancel_button)
        action_row.addWidget(self.open_out_button)
        action_row.addStretch(1)
        root.addLayout(action_row)

        self.progress = QProgressBar()
        root.addWidget(self.progress)

    # ---------- 拖放 ----------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and Path(path).is_dir():
                self.folder_edit.setText(path)
                break

    # ---------- 檔案選擇 ----------
    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇字幕資料夾")
        if path:
            self.folder_edit.setText(path)

    def _browse_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇輸出資料夾")
        if path:
            self.outdir_edit.setText(path)
            self.outdir_radio.setChecked(True)

    def _output_dir(self) -> Optional[Path]:
        if self.outdir_radio.isChecked():
            text = self.outdir_edit.text().strip()
            return Path(text) if text else None
        return None

    # ---------- 掃描 ----------
    def _on_scan(self) -> None:
        folder = self.folder_edit.text().strip()
        if not folder or not Path(folder).is_dir():
            self.log.emit("請先選擇有效的資料夾")
            return
        scan = scan_folder(Path(folder))
        self._scan = scan
        for w in scan.warnings:
            self.log.emit(f"警告: {w}")
        count = self.populate_preview(scan)
        self.log.emit(f"掃描完成:共 {count} 個字幕檔")

    def populate_preview(self, scan) -> int:
        rows = preview_rows(scan)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(
                    (row.episode, row.sub_name, row.video_name,
                     row.status_label)):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.run_button.setEnabled(len(rows) > 0)
        return len(rows)

    # ---------- 執行 ----------
    def _on_run(self) -> None:
        if self._scan is None:
            return
        try:
            profile = self._get_profile()
        except ValueError as exc:
            self.log.emit(f"欄位錯誤: {exc}")
            return
        if self.outdir_radio.isChecked() and self._output_dir() is None:
            self.log.emit("請先選擇輸出資料夾")
            return

        self.progress.setValue(0)
        self.scan_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        self._thread = QThread()
        self._worker = BatchWorker(self._scan, profile, self._output_dir())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_done.connect(
            lambda name, status: self.log.emit(f"[{status}] {name}"))
        self._worker.message.connect(self.log.emit)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(done)

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)

    def _on_finished(self, ok: int, skipped: int, error: int) -> None:
        self.log.emit(f"完成:成功 {ok},跳過 {skipped},錯誤 {error}")
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self.scan_button.setEnabled(True)
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    # ---------- 開啟輸出資料夾 ----------
    def _open_output(self) -> None:
        target = self._output_dir()
        if target is None:
            target = Path(self.folder_edit.text().strip() or ".")
        if target.is_dir():
            if sys.platform.startswith("win"):
                os.startfile(str(target))  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(target)])
```

- [ ] **Step 5: 執行測試,確認通過**

Run: `py -m pytest tests/test_subtitle_tab.py -v`
Expected: 4 passed
(說明:`BatchWorker.run()` 在測試中直接呼叫,不進 QThread,所以 signals 同步觸發,斷言可直接檢查。)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/qt/batch_worker.py ass_style_tool/qt/subtitle_tab.py tests/test_subtitle_tab.py
git commit -m "feat: add subtitle-file tab with threaded batch, progress, cancel"
```

---

### Task 4: 整合進主視窗 + 切換進入點 + 移除舊 tkinter

**Files:**
- Modify: `ass_style_tool/qt/main_window.py`
- Modify: `ass_style_tool/__main__.py`
- Delete: `ass_style_tool/gui.py`

**Interfaces:**
- Consumes: `style_editor.StyleEditor`、`subtitle_tab.SubtitleFileTab`
- Produces: 主視窗「字幕檔」分頁放 SubtitleFileTab、「樣式與預覽」分頁放 StyleEditor(左側;右側預覽 Plan 2c);`py -m ass_style_tool` 啟動 Qt 版

- [ ] **Step 1: 修改 main_window.py 接入分頁**

把 `ass_style_tool/qt/main_window.py` 中「分頁籤(本計畫先放佔位)」那段(建立三個佔位 page 的迴圈)替換為下列內容,並在檔案 import 區加入對應 import。

在 import 區(`from .theme import ...` 之後)加:

```python
from .style_editor import StyleEditor
from .subtitle_tab import SubtitleFileTab
```

把原本這段:

```python
        # 分頁籤(本計畫先放佔位)
        self.tabs = QTabWidget()
        for name in ("字幕檔", "MKV", "樣式與預覽"):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.addWidget(QLabel(f"（{name} 功能於後續計畫實作）"))
            page_layout.addStretch(1)
            self.tabs.addTab(page, name)
        layout.addWidget(self.tabs, 1)
```

替換為:

```python
        # 分頁籤
        self.tabs = QTabWidget()
        self.style_editor = StyleEditor()
        self.subtitle_tab = SubtitleFileTab(self.style_editor.current_profile)
        self.subtitle_tab.log.connect(self.append_log)

        self.tabs.addTab(self.subtitle_tab, "字幕檔")

        mkv_page = QWidget()
        mkv_layout = QVBoxLayout(mkv_page)
        mkv_layout.addWidget(QLabel("（MKV 功能於後續計畫實作）"))
        mkv_layout.addStretch(1)
        self.tabs.addTab(mkv_page, "MKV")

        self.tabs.addTab(self.style_editor, "樣式與預覽")
        layout.addWidget(self.tabs, 1)
```

- [ ] **Step 2: 切換進入點到 Qt**

把 `ass_style_tool/__main__.py` 整檔內容替換為:

```python
from .qt.main_window import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 移除舊 tkinter GUI**

```powershell
git rm ass_style_tool/gui.py
```

（v1 未對 tkinter gui 寫自動化測試,無測試檔需移除。）

- [ ] **Step 4: import 檢查**

Run: `py -c "import ass_style_tool.qt.main_window; import ass_style_tool.__main__; print('ok')"`
Expected: 輸出 `ok`,無例外

- [ ] **Step 5: 啟動冒煙(兩個進入點都測)**

```powershell
foreach ($mod in @("ass_style_tool", "ass_style_tool.qt")) {
  $p = Start-Process -FilePath "py" -ArgumentList "-m",$mod -WorkingDirectory "C:\Claude_code" -PassThru
  Start-Sleep -Seconds 3
  if ($p.HasExited) { Write-Output "FAIL $mod exit=$($p.ExitCode)" } else { Write-Output "OK $mod"; Stop-Process -Id $p.Id }
}
```

Expected: 兩行都是 `OK ...`

- [ ] **Step 6: 全部自動化測試**

Run: `py -m pytest tests -v`
Expected: 125 passed(先前 110 + gui_helpers 6 + style_editor 5 + subtitle_tab 4)

- [ ] **Step 7: 手動冒煙清單(由使用者執行,記於報告)**

Run: `py -m ass_style_tool`
人工確認:
1. 開啟即 Qt 介面(不再是舊 tkinter);主題切換仍正常(含標題列)
2. 「樣式與預覽」分頁:欄位有預設值;改字型名為系統沒有的字型 → 出現黃色未安裝警告;「選色…」能改主色/外框/陰影;「另存」存出 JSON、下拉選單出現該檔、「載入」讀回欄位還原
3. 「字幕檔」分頁:拖或選一個含 .ass 的資料夾(可用 demo_subs)→「掃描並預覽配對」→ 表格列出集數/字幕/影片/狀態;「開始套用樣式」變可按
4. 「原地覆蓋」跑一次 → 進度條動、log 顯示每檔結果與總結、.bak 產生、Default style 已改
5. 「輸出到資料夾」跑一次 → 新資料夾有輸出、原檔未動;「開啟輸出資料夾」能開檔案總管
6. 檔案多時按「取消」→ 當前檔跑完後停止,log 顯示已取消

- [ ] **Step 8: Commit**

```powershell
git add ass_style_tool/qt/main_window.py ass_style_tool/__main__.py
git commit -m "feat: wire style editor + subtitle tab into Qt window, switch entry point, remove tkinter GUI"
```

---

## 本計畫完成後

新 Qt 介面達到 v1 功能對等(散裝字幕批次改樣式),且預設進入點已切換、舊 tkinter 移除。接著:

- **Plan 2c — mpv 預覽 + MKV 分頁**:「樣式與預覽」右側接內嵌 mpv 播放器(改樣式即時重載、字幕行跳轉);「MKV」分頁接 mkv_io(列字幕軌、勾選、一鍵選整季、重封裝、取消)。
- **Plan 3 — 打包**:PyInstaller + Inno Setup。
