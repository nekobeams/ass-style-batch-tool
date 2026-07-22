# 換算對照讀出移至左欄 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「換算對照」讀出從右側預覽面板搬到左側樣式編輯區底部,並把整個左欄包進捲動區,讓小視窗出捲軸而非裁切欄位。

**Architecture:** 三塊,顯示與資料來源解耦。新增純顯示元件 `ReadoutView`(收 `ReadoutData` 渲染);`PreviewPanel` 改成算好 `ReadoutData` 後用 `readout_changed` 訊號送出、不再自己放讀出 widget;`StyleEditor` 把全部內容包進 `QScrollArea` 並在底部嵌 `ReadoutView`;`main_window` 一行把訊號接到左欄。

**Tech Stack:** Python、PySide6(Qt Widgets/Signal)、pytest(offscreen,見 tests/conftest.py)。

## Global Constraints

- 一律用 `py`,不要用 `python`。測試從 repo root:`py -m pytest tests -q`。目前基線 **319 passed**,實作後維持全綠(新增測試會使總數上升)。
- 讀出的內容、文案、即時更新行為**不變**:機制說明、情境行 + 影片比例檢查、原字幕現值→套用後三欄表、目標樣式缺失訊息;跟著檔案載入與樣式編輯即時刷新。
- profile 無效(`get_profile()` 丟 `ValueError`)或未載入字幕時**不更新讀出**(維持上一次/佔位提示)——與現行語意一致。
- `PreviewPanel` 既有行為(視覺預覽、時間軸、防抖、shutdown 清理)不可退化。
- 使用者選定:整個左欄(profile 列 + 欄位 + 讀出)一起捲動,不做 profile 列固定。
- commit 訊息結尾加:`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- 環境:PowerShell/Bash 前先確認 CWD 在 `C:\Claude_code`(Bash 每次 `cd /c/Claude_code`)。

---

## File Structure

- `ass_style_tool/qt/readout_view.py`(新增):`ReadoutView(QGroupBox)` 純顯示元件 + `update_from`。
- `ass_style_tool/qt/preview_panel.py`(修改):移除內建讀出 widget,改 emit `readout_changed`。
- `ass_style_tool/qt/style_editor.py`(修改):內容包 `QScrollArea`,底部嵌 `ReadoutView`。
- `ass_style_tool/qt/main_window.py`(修改):接線 `preview_panel.readout_changed → style_editor.readout_view.update_from`。
- `tests/test_readout_view.py`(新增)、`tests/test_preview_panel.py`(改)、`tests/test_style_editor.py`(加)、`tests/test_main_window.py`(加)。

---

### Task 1: `ReadoutView` 純顯示元件

**Files:**
- Create: `ass_style_tool/qt/readout_view.py`
- Test: `tests/test_readout_view.py`

**Interfaces:**
- Consumes: `ass_style_tool.preview_readout.ReadoutData`(既有:欄位 `mechanism, context_subtitle, context_video, aspect_warning, rows, missing_message, note`;`rows` 為 `ReadoutRow(label, original, applied)`)。
- Produces:
  - `ReadoutView(QGroupBox)`,屬性 `mechanism, context_sub, context_video, missing`(皆 `QLabel`)、`table`(`QTableWidget`,3 欄)、`note`(`QLabel`)。
  - 方法 `update_from(data: Optional[ReadoutData]) -> None`。

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_readout_view.py`:

```python
from __future__ import annotations

from ass_style_tool.preview_readout import OriginalValues, build_readout
from ass_style_tool.qt.readout_view import ReadoutView
from tests.test_profile import make_profile


def _orig():
    return OriginalValues(fontsize=40.0, outline=2.0, shadow=1.0,
                          margin_l=10, margin_r=10, margin_v=10)


def test_update_from_data_fills_table(qapp):
    v = ReadoutView()
    data = build_readout(make_profile(), 640, 360, _orig(), "e.ass", None, None)
    v.update_from(data)
    labels = [v.table.item(r, 0).text() for r in range(v.table.rowCount())]
    assert "字級" in labels
    row = labels.index("字級")
    assert v.table.item(row, 1).text() == "40"     # 原字幕現值
    assert v.table.item(row, 2).text() == "24"     # 72 * 640/1920
    assert v.missing.isHidden()
    assert not v.table.isHidden()


def test_update_from_missing_shows_message_hides_table(qapp):
    v = ReadoutView()
    data = build_readout(make_profile(target_style_names=["字幕"]), 640, 360,
                         None, "e.ass", None, None)
    v.update_from(data)
    assert not v.missing.isHidden()
    assert "字幕" in v.missing.text()
    assert v.table.isHidden()


def test_update_from_none_shows_placeholder(qapp):
    v = ReadoutView()
    v.update_from(build_readout(make_profile(), 640, 360, _orig(),
                                "e.ass", None, None))
    v.update_from(None)
    assert "載入字幕檔" in v.mechanism.text()
    assert v.table.rowCount() == 0
    assert v.table.isHidden()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_readout_view.py -q`
Expected: FAIL(`No module named 'ass_style_tool.qt.readout_view'`)

- [ ] **Step 3: 實作 `readout_view.py`**

```python
"""換算對照讀出的純顯示元件:收 ReadoutData 渲染,不認識 profile/檔案/影片。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (QAbstractItemView, QGroupBox, QHeaderView,
                               QLabel, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from ..preview_readout import ReadoutData

_PLACEHOLDER = "載入字幕檔後顯示換算結果"


class ReadoutView(QGroupBox):
    def __init__(self) -> None:
        super().__init__("換算對照(套用後的實際數字)")
        layout = QVBoxLayout(self)
        self.mechanism = QLabel(_PLACEHOLDER)
        self.mechanism.setWordWrap(True)
        self.context_sub = QLabel("")
        self.context_sub.setWordWrap(True)
        self.context_video = QLabel("")
        self.context_video.setWordWrap(True)
        self.missing = QLabel("")
        self.missing.setWordWrap(True)
        self.missing.hide()
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["樣式", "原字幕現值", "套用後"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMaximumHeight(200)
        self.table.hide()
        self.note = QLabel("")
        for w in (self.mechanism, self.context_sub, self.context_video,
                  self.missing, self.table, self.note):
            layout.addWidget(w)

    def update_from(self, data: Optional[ReadoutData]) -> None:
        if data is None:
            self.mechanism.setText(_PLACEHOLDER)
            self.context_sub.setText("")
            self.context_video.setText("")
            self.note.setText("")
            self.missing.hide()
            self.table.setRowCount(0)
            self.table.hide()
            return
        self.mechanism.setText(data.mechanism)
        self.context_sub.setText(data.context_subtitle)
        self.context_video.setText(data.context_video)
        self.note.setText(data.note)
        if data.missing_message:
            self.missing.setText(data.missing_message)
            self.missing.show()
            self.table.hide()
        else:
            self.missing.hide()
            self.table.show()
            self.table.setRowCount(len(data.rows))
            for r, row in enumerate(data.rows):
                self.table.setItem(r, 0, QTableWidgetItem(row.label))
                self.table.setItem(r, 1, QTableWidgetItem(row.original))
                self.table.setItem(r, 2, QTableWidgetItem(row.applied))
```

- [ ] **Step 4: 跑測試確認通過**

Run: `py -m pytest tests/test_readout_view.py -q`
Expected: PASS(3 個測試)

- [ ] **Step 5: Commit**

```bash
git add ass_style_tool/qt/readout_view.py tests/test_readout_view.py
git commit -m "Add ReadoutView: pure display widget for the conversion readout

Renders a ReadoutData (mechanism line, subtitle/video context, 3-column
original-to-applied table, target-missing message). No knowledge of
profile/file/video -- update_from(data) is its whole contract.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `PreviewPanel` 改用 `readout_changed` 訊號

**Files:**
- Modify: `ass_style_tool/qt/preview_panel.py`
- Test: `tests/test_preview_panel.py`

**Interfaces:**
- Consumes: `build_readout`, `OriginalValues`(既有 import)、`get_play_res`。
- Produces:
  - `PreviewPanel.readout_changed = Signal(object)`(payload 為 `ReadoutData`)。
  - 移除面板內讀出 widget(`readout_*`)。`_update_readout` 改為 emit。

- [ ] **Step 1: 改寫既有讀出測試為訊號式(先讓它們失敗)**

在 `tests/test_preview_panel.py`,把「`# ---------- 換算對照讀出`」以下到檔尾的四個 `test_readout_*` 測試整段**取代**為:

```python
# ---------- 換算對照讀出(訊號式) ----------

def _capture(panel):
    got = []
    panel.readout_changed.connect(lambda d: got.append(d))
    return got


def test_readout_emits_rows_on_set_media(qapp, tmp_path, monkeypatch):
    import ass_style_tool.qt.preview_panel as pp
    monkeypatch.setattr(pp, "probe_video_resolution", lambda path: None)
    player = FakePlayer()
    panel = _panel(player)                       # DEFAULT_VALUES: 基準 1920x1080
    got = _capture(panel)
    panel.set_media(_write_sample(tmp_path))     # SAMPLE_ASS 畫布 1280x720
    assert got
    by_label = {r.label: (r.original, r.applied) for r in got[-1].rows}
    assert by_label["字級"] == ("40", "48")      # 72 * 1280/1920
    assert "1280×720" in got[-1].mechanism
    panel.shutdown()


def test_readout_no_video_emits_guidance(qapp, tmp_path, monkeypatch):
    import ass_style_tool.qt.preview_panel as pp
    monkeypatch.setattr(pp, "probe_video_resolution", lambda path: None)
    player = FakePlayer()
    panel = _panel(player)
    got = _capture(panel)
    panel.set_media(_write_sample(tmp_path))
    assert "載入影片" in got[-1].context_video
    panel.shutdown()


def test_readout_video_aspect_emitted(qapp, tmp_path, monkeypatch):
    import ass_style_tool.qt.preview_panel as pp
    monkeypatch.setattr(pp, "probe_video_resolution", lambda path: (1920, 1080))
    player = FakePlayer()
    panel = _panel(player)
    got = _capture(panel)
    panel.set_media(_write_sample(tmp_path), video_path=Path("v.mkv"))
    # 畫布 1280x720 (16:9) vs 1920x1080 (16:9) → 相符
    assert "比例相符" in got[-1].context_video
    panel.shutdown()


def test_readout_updates_on_style_change(qapp, tmp_path, monkeypatch):
    import ass_style_tool.qt.preview_panel as pp
    from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values
    from ass_style_tool.qt.preview_panel import PreviewPanel
    monkeypatch.setattr(pp, "probe_video_resolution", lambda path: None)
    values = dict(DEFAULT_VALUES)
    player = FakePlayer()
    panel = PreviewPanel(lambda: profile_from_values(values), player=player)
    got = _capture(panel)
    panel.set_media(_write_sample(tmp_path))     # 畫布 1280x720,scale 0.6667

    def applied_fontsize(data):
        return {r.label: r.applied for r in data.rows}["字級"]

    assert applied_fontsize(got[-1]) == "48"     # 72 * 0.6667
    values["fontsize"] = "90"                     # 使用者改字級
    panel._apply_preview()                        # 防抖到期會走的路徑
    assert applied_fontsize(got[-1]) == "60"     # 90 * 0.6667
    panel.shutdown()


def test_readout_not_emitted_on_invalid_profile(qapp, tmp_path, monkeypatch):
    import ass_style_tool.qt.preview_panel as pp
    from ass_style_tool.qt.preview_panel import PreviewPanel
    monkeypatch.setattr(pp, "probe_video_resolution", lambda path: None)

    def bad_profile():
        raise ValueError("欄位無效")

    player = FakePlayer()
    panel = PreviewPanel(bad_profile, player=player)
    got = _capture(panel)
    panel.set_media(_write_sample(tmp_path))
    assert got == []                              # 無效 profile 不 emit
    panel.shutdown()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_preview_panel.py -k readout -q`
Expected: FAIL(`AttributeError: 'PreviewPanel' object has no attribute 'readout_changed'`)

- [ ] **Step 3: 加訊號、改 import**

在 `ass_style_tool/qt/preview_panel.py`:

把 QtCore import 改為(加 `Signal`):
```python
from PySide6.QtCore import Qt, QTimer, Signal
```

把 QtWidgets import 改為(移除只給讀出用的 `QGroupBox/QTableWidget/QTableWidgetItem/QAbstractItemView/QHeaderView`):
```python
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QSlider,
                               QSplitter, QVBoxLayout, QWidget)
```

在 `class PreviewPanel(QWidget):` 下、`def __init__` 之前加類別屬性:
```python
class PreviewPanel(QWidget):
    readout_changed = Signal(object)

    def __init__(self, get_profile: Callable[[], Profile],
```

- [ ] **Step 4: 移除面板內讀出 widget 區塊**

刪除 `__init__` 中建立 `readout_box` 的整段(從 `readout_box = QGroupBox(...)` 到 `root.addWidget(readout_box)`,即目前的:

```python
        readout_box = QGroupBox("換算對照(套用後的實際數字)")
        readout_layout = QVBoxLayout(readout_box)
        self.readout_mechanism = QLabel("載入字幕檔後顯示換算結果")
        self.readout_mechanism.setWordWrap(True)
        self.readout_context_sub = QLabel("")
        self.readout_context_video = QLabel("")
        self.readout_context_video.setWordWrap(True)
        self.readout_missing = QLabel("")
        self.readout_missing.setWordWrap(True)
        self.readout_missing.hide()
        self.readout_table = QTableWidget(0, 3)
        self.readout_table.setHorizontalHeaderLabels(["樣式", "原字幕現值", "套用後"])
        self.readout_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.readout_table.verticalHeader().setVisible(False)
        self.readout_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.readout_table.setMaximumHeight(200)
        self.readout_note = QLabel("字型、顏色、對齊 直接採用 profile 設定(不縮放)")
        for w in (self.readout_mechanism, self.readout_context_sub,
                  self.readout_context_video, self.readout_missing,
                  self.readout_table, self.readout_note):
            readout_layout.addWidget(w)
        root.addWidget(readout_box)
```

整段刪掉。刪除後,`__init__` 版面順序為:`bar` → `split`(root.addWidget(split, 1))→ 直接接 `self.status = QLabel("尚未載入字幕")` / `root.addWidget(self.status)`。

- [ ] **Step 5: 改寫 `_update_readout` 為 emit**

把 `_update_readout` 整個方法(目前從 `self.readout_mechanism.setText(...)` 起的填 widget 版本)換成:

```python
    def _update_readout(self) -> None:
        if self._source_sub is None or self._source_subs is None:
            return
        try:
            profile = self._get_profile()
        except ValueError:
            return  # 欄位打到一半暫時無效,保留上一次讀出
        play_res_x, play_res_y = get_play_res(self._source_subs)
        original = self._lookup_original(profile)
        video_name = self._video_path.name if self._video_path else None
        data = build_readout(
            profile, play_res_x, play_res_y, original,
            self._source_sub.name, video_name, self._video_res)
        self.readout_changed.emit(data)
```

`_lookup_original`、`_set_video`、`_apply_preview`(末端仍呼叫 `self._update_readout()`)等其餘不動。

- [ ] **Step 6: 跑讀出測試 + 既有 preview 全套**

Run: `py -m pytest tests/test_preview_panel.py -q`
Expected: PASS(既有非讀出測試 + 5 個新訊號式讀出測試全綠)

- [ ] **Step 7: Commit**

```bash
git add ass_style_tool/qt/preview_panel.py tests/test_preview_panel.py
git commit -m "PreviewPanel emits readout_changed instead of hosting the readout

The readout widgets move out; PreviewPanel now builds the ReadoutData and
emits it via a readout_changed signal (no emit when the profile is invalid
or no subtitle is loaded, preserving the last shown value). Readout display
moves to the left column in the next task.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `StyleEditor` 捲動區 + 嵌 `ReadoutView`,`main_window` 接線

**Files:**
- Modify: `ass_style_tool/qt/style_editor.py`
- Modify: `ass_style_tool/qt/main_window.py`
- Test: `tests/test_style_editor.py`, `tests/test_main_window.py`

**Interfaces:**
- Consumes: `ReadoutView`(Task 1)、`PreviewPanel.readout_changed`(Task 2)。
- Produces: `StyleEditor.readout_view`(`ReadoutView` 實例);`main_window` 接線。

- [ ] **Step 1: 寫失敗測試(StyleEditor + main_window)**

在 `tests/test_style_editor.py` 末端加:

```python
def test_style_editor_wraps_content_in_scrollarea_with_readout(qapp):
    from PySide6.QtWidgets import QScrollArea
    from ass_style_tool.qt.style_editor import StyleEditor
    from ass_style_tool.qt.readout_view import ReadoutView
    editor = StyleEditor()
    assert editor.findChild(QScrollArea) is not None      # 內容包在捲動區
    assert isinstance(editor.readout_view, ReadoutView)    # 底部有讀出元件


def test_style_editor_readout_view_renders(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    from ass_style_tool.preview_readout import OriginalValues, build_readout
    from tests.test_profile import make_profile
    editor = StyleEditor()
    data = build_readout(make_profile(), 640, 360,
                         OriginalValues(40.0, 2.0, 1.0, 10, 10, 10),
                         "e.ass", None, None)
    editor.readout_view.update_from(data)
    labels = [editor.readout_view.table.item(r, 0).text()
              for r in range(editor.readout_view.table.rowCount())]
    assert "字級" in labels
```

在 `tests/test_main_window.py` 末端加:

```python
def test_preview_readout_wired_to_style_editor(qapp, monkeypatch, tmp_path):
    """在 preview_panel 觸發一次讀出更新,左欄 style_editor.readout_view
    表格應被填(驗證 main_window 的訊號接線)。用空的暫存 QSettings 避免
    載入使用者真實設定或 profile。"""
    from PySide6.QtCore import QSettings
    import ass_style_tool.qt.main_window as mw
    from tests.test_ass_style import SAMPLE_ASS

    ini = tmp_path / "s.ini"
    monkeypatch.setattr(
        mw, "QSettings",
        lambda *a, **k: QSettings(str(ini), QSettings.Format.IniFormat))

    window = mw.MainWindow()
    try:
        sub = tmp_path / "e.ass"
        sub.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
        window.preview_panel.set_media(sub)       # 無影片,offscreen 安全
        table = window.style_editor.readout_view.table
        labels = [table.item(r, 0).text() for r in range(table.rowCount())]
        assert "字級" in labels
    finally:
        window.deleteLater()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_style_editor.py::test_style_editor_wraps_content_in_scrollarea_with_readout tests/test_main_window.py::test_preview_readout_wired_to_style_editor -q`
Expected: FAIL(`AttributeError: 'StyleEditor' object has no attribute 'readout_view'`)

- [ ] **Step 3: StyleEditor 包捲動區 + 嵌 ReadoutView**

在 `ass_style_tool/qt/style_editor.py`:

QtWidgets import 加入 `QScrollArea` 與 `QFrame`(併進既有那行):
```python
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)
```

新增 import:
```python
from .readout_view import ReadoutView
```

把 `__init__` 內從 `root = QVBoxLayout(self)` 到 `root.addStretch(1)` 的版面組裝改為:把 `profile_row` 與 `form` 加進一個 inner widget,inner 內加 `readout_view` 與 stretch,再用 `QScrollArea` 包起來當 `self` 唯一內容。具體:

- 把原本的 `root = QVBoxLayout(self)` 改成建立 inner:
```python
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
```
- 原本 `root.addLayout(profile_row)` → `inner_layout.addLayout(profile_row)`。
- 原本 `root.addLayout(form)` → `inner_layout.addLayout(form)`。
- 原本 `root.addStretch(1)` 改成先加讀出再 stretch:
```python
        self.readout_view = ReadoutView()
        inner_layout.addWidget(self.readout_view)
        inner_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)

        root = QVBoxLayout(self)
        root.addWidget(scroll)
```

其餘(`self.set_values(DEFAULT_VALUES)`、`migrate_legacy_profiles`、`_refresh_profile_list`、`values_changed` 接線等)維持在 `__init__` 內、順序不變。`form` 與 `profile_row` 的建立程式碼原樣保留,只是改加到 `inner_layout`。

- [ ] **Step 4: main_window 接線**

在 `ass_style_tool/qt/main_window.py`,`self.preview_panel = PreviewPanel(...)` 建立之後(`self.style_editor` 已於前面建立),加一行接線。找到:

```python
        self.preview_panel = PreviewPanel(self.style_editor.current_profile)
```

在其後加:

```python
        self.preview_panel.readout_changed.connect(
            self.style_editor.readout_view.update_from)
```

- [ ] **Step 5: 跑新測試 + 相關全套**

Run: `py -m pytest tests/test_style_editor.py tests/test_main_window.py tests/test_preview_panel.py tests/test_readout_view.py -q`
Expected: PASS(全綠)

- [ ] **Step 6: 全套回歸**

Run: `py -m pytest tests -q`
Expected: PASS(319 + 新增測試,全綠)

- [ ] **Step 7: Commit**

```bash
git add ass_style_tool/qt/style_editor.py ass_style_tool/qt/main_window.py tests/test_style_editor.py tests/test_main_window.py
git commit -m "Move readout into the left editor column inside a scroll area

StyleEditor wraps all its content (profile row, fields, readout) in a
QScrollArea so small windows scroll instead of clipping; the ReadoutView
sits at the bottom of the fields. main_window wires preview_panel's
readout_changed signal to the left-column ReadoutView.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- 讀出搬到左欄底部(選項 1)→ Task 1 元件 + Task 3 嵌入 ✓
- 整個左欄包 QScrollArea、全部一起捲動 → Task 3 Step 3 ✓
- 右側預覽不再放讀出 → Task 2 Step 4 移除 ✓
- 讀出內容/即時更新不變 → build_readout 不動,`_apply_preview` 末端仍呼叫 `_update_readout`(改 emit);ReadoutView 渲染邏輯搬自原 widget 填法 ✓
- profile 無效/未載入不更新 → Task 2 `_update_readout` 早退不 emit;`test_readout_not_emitted_on_invalid_profile` ✓
- ReadoutView 純顯示、不認識 profile/檔案 → Task 1 ✓
- 訊號接線 → Task 3 Step 4 + `test_preview_readout_wired_to_style_editor` ✓
- 測試:ReadoutView 顯示、preview 改訊號式、style_editor 捲動+嵌入、main_window 整合、全套回歸 → 各 Task 涵蓋 ✓

**2. Placeholder scan:** 無 TBD/TODO;每個 code step 均含完整程式碼與可執行指令。

**3. Type consistency:** `ReadoutView.update_from(Optional[ReadoutData])`、屬性名 `mechanism/context_sub/context_video/missing/table/note`(Task 1)在 Task 3 測試以 `readout_view.table` 使用一致;`readout_changed = Signal(object)`(Task 2)在 Task 3 `main_window` 與整合測試以 `.connect(... .update_from)` 使用一致;`build_readout`/`OriginalValues` 簽章沿用既有。

## 範圍外(本計畫不做)

- 不動 `compute_applied_values`、`build_readout`、視覺預覽(mpv)。
- 不做 profile 列固定在頂部。
- 不改讀出文案/欄位。
