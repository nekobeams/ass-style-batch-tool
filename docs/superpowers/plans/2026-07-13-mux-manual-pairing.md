# 封裝分頁——手動配對 Implementation Plan

**Goal:** 讓「封裝」分頁的配對表格每一列都能用下拉選單手動指定/更換字幕檔,手動指定後視同自動配對成功(可勾選封裝)。

**Architecture:** 純 UI 層改動,只碰 `ass_style_tool/qt/mux_tab.py`。新增 `set_row_subtitle` 模型變更 API(更新 `self._pairs[row]` 的 `subtitle_path`/`status`、同步狀態欄與勾選框),再把配對表格第 3 欄(字幕)從唯讀文字改成 `QComboBox`,選單 `activated` 訊號接到 `set_row_subtitle`。下游 `mkv_mux`/`batch_worker`/`process_mux` 完全不變。

**Tech Stack:** PySide6(QComboBox / QTableWidget setCellWidget)、pytest(offscreen Qt)、Python dataclasses.replace。

**Spec:** `docs/superpowers/specs/2026-07-13-mux-manual-pairing-design.md`

## Global Constraints

- 工作目錄/repo root:專案根目錄;git branch 由執行者自行建立(從 master HEAD 分出)
- **環境重點**:`python` 是壞的 Windows Store stub,一律用 `py`:`py -m pytest tests -v`
- Python 3.9+ 相容;`mux_tab.py` 已有 `from __future__ import annotations`
- Qt 測試用既有 `tests/conftest.py` 的 offscreen `qapp` fixture;絕不初始化真實 mkvmerge(測試用 monkeypatch `mkvmerge_path`/`mkvextract_path`)
- 測試指令:`py -m pytest tests -v`(從 repo root;目前基準 **256 passed**)
- **相容性硬約束**:既有 10 個 `test_mux_tab.py` 測試必須全數維持通過。第 3 欄改用 `setCellWidget` 後 `table.item(r, 2)` 會回 `None`——已確認無既有測試讀取第 2 欄的 `item()`(只讀第 0 欄勾選框)
- 下游模組(`mkv_mux.py`、`qt/batch_worker.py`、`process_mux`、`build_mux_command`)不得修改
- Commit 訊息用 conventional commits(英文)

### 既有介面(本計畫會用到,已實作)

- `ass_style_tool.mkv_mux.MuxPair`:`@dataclass`,欄位 `video_path: Path`、`subtitle_path: Optional[Path]`、`episode: Optional[int]`、`status: str`(matched|no_subtitle|ambiguous|no_episode)
- `ass_style_tool.episode_match.find_files(folder: Path) -> Tuple[List[Path], List[Path]]`:回 `(subs, videos)`
- `mux_tab.py` 現有:`self._pairs: List[MuxPair]`、`self.table`(5 欄:封裝/影片/字幕/集數/狀態)、`populate(pairs)`、`checked_pairs()`(硬性只回 `status == "matched"` 的勾選列)、`_on_scan_done(pairs)`、`_STATUS_LABELS` dict、`self.run_button`、`self.tools_available`、`self._thread`
- `populate()` 目前對每列:col 0 建勾選框 `QTableWidgetItem`、col 1 影片名、col 2 字幕名文字、col 3 集數、col 4 狀態文字

## File Structure

```
ass_style_tool/qt/
└── mux_tab.py          # (修改)新增 set_row_subtitle/_on_subtitle_selected;populate col2 改 QComboBox;_on_scan_done 掃字幕清單;新增 _available_subtitles 狀態 + import
tests/
└── test_mux_tab.py     # (修改)附加手動配對測試
```

---

### Task 1: set_row_subtitle 模型變更 API

**Files:**
- Modify: `ass_style_tool/qt/mux_tab.py`(加 `import dataclasses`;`__init__` 加 `self._available_subtitles`;新增 `set_row_subtitle` 方法)
- Test: `tests/test_mux_tab.py`(附加 3 個測試)

**Interfaces:**
- Consumes: 既有 `self._pairs`、`self.table`(col 0 勾選框 item、col 4 狀態 item)、`self.run_button`、`self.tools_available`、`self._thread`、`_STATUS_LABELS`、`MuxPair`
- Produces:
  - `set_row_subtitle(self, row: int, subtitle_path: Optional[Path]) -> None`:用 `dataclasses.replace` 覆蓋 `self._pairs[row]`——非 None 時 `subtitle_path=給定值, status="matched"`,None 時 `subtitle_path=None, status="no_subtitle"`;同步更新 col 4 狀態欄文字、col 0 勾選框(matched→Checked,否則 Unchecked)、`run_button` 啟用狀態(比照 `populate()` 末尾邏輯)
  - `self._available_subtitles: List[Path]`(Task 2 會用;此 Task 先初始化為空 list)

- [ ] **Step 1: 附加失敗測試**

在 `tests/test_mux_tab.py` 末尾附加:

```python


# ---------- 手動配對:set_row_subtitle 模型變更 ----------

def test_set_row_subtitle_assigns_and_checks(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    # 第 1 列原本 no_subtitle → 手動指定字幕
    tab.set_row_subtitle(1, Path("manual [02].ass"))
    assert tab.table.item(1, 0).checkState() == Qt.CheckState.Checked
    checked = {p.video_path: p for p in tab.checked_pairs()}
    assert Path("b [02].mkv") in checked
    assert checked[Path("b [02].mkv")].subtitle_path == Path("manual [02].ass")


def test_set_row_subtitle_clear_unchecks(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    # 第 0 列原本 matched → 清除指定
    tab.set_row_subtitle(0, None)
    assert tab.table.item(0, 0).checkState() == Qt.CheckState.Unchecked
    assert Path("a [01].mkv") not in {p.video_path for p in tab.checked_pairs()}


def test_set_row_subtitle_reassign_matched(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    # 第 0 列原本 matched(a [01].ass)→ 改指定別的字幕
    tab.set_row_subtitle(0, Path("other [01].ass"))
    checked = {p.video_path: p for p in tab.checked_pairs()}
    assert checked[Path("a [01].mkv")].subtitle_path == Path("other [01].ass")
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_mux_tab.py -v -k set_row_subtitle`
Expected: FAIL — `AttributeError: 'MuxTab' object has no attribute 'set_row_subtitle'`

- [ ] **Step 3: 實作 set_row_subtitle**

在 `ass_style_tool/qt/mux_tab.py` 檔案頂端 import 區(`from pathlib import Path` 那行附近)加:

```python
import dataclasses
```

在 `__init__` 中 `self._pairs: List[MuxPair] = []` 那行之後加一行:

```python
        self._available_subtitles: List[Path] = []
```

在 `checked_pairs` 方法之後(`# ---------- 軌資訊 / 操作 ----------` 註解之前)新增方法:

```python
    def set_row_subtitle(self, row: int, subtitle_path: Optional[Path]) -> None:
        """手動指定(或清除)某列的字幕檔;同步 pair/狀態欄/勾選框。"""
        pair = self._pairs[row]
        if subtitle_path is not None:
            new_pair = dataclasses.replace(
                pair, subtitle_path=subtitle_path, status="matched")
        else:
            new_pair = dataclasses.replace(
                pair, subtitle_path=None, status="no_subtitle")
        self._pairs[row] = new_pair
        self.table.item(row, 4).setText(
            _STATUS_LABELS.get(new_pair.status, new_pair.status))
        check = self.table.item(row, 0)
        check.setCheckState(
            Qt.CheckState.Checked if new_pair.status == "matched"
            else Qt.CheckState.Unchecked)
        self.run_button.setEnabled(
            self.tools_available
            and any(p.status == "matched" for p in self._pairs)
            and self._thread is None)
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_mux_tab.py -v -k set_row_subtitle`
Expected: 3 passed

- [ ] **Step 5: 跑全套確認無回歸**

Run: `py -m pytest tests -q`
Expected: 259 passed(256 + 3)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/qt/mux_tab.py tests/test_mux_tab.py
git commit -m "feat: add set_row_subtitle to mux tab for manual pairing"
```

---

### Task 2: 字幕欄 QComboBox + 掃描時填字幕清單

**Files:**
- Modify: `ass_style_tool/qt/mux_tab.py`(import `find_files`;`populate` col 2 改 `setCellWidget(QComboBox)`;`_on_scan_done` 掃字幕清單;新增 `_on_subtitle_selected`)
- Test: `tests/test_mux_tab.py`(附加 2 個測試)

**Interfaces:**
- Consumes: Task 1 的 `set_row_subtitle`、`self._available_subtitles`;既有 `self.table`、`self._pairs`、`self.subtitle_edit`、`find_files`
- Produces:
  - `populate()` 第 3 欄(col 2)改用 `QComboBox`(`setCellWidget`),選項為「(無)」(data=None)+ `self._available_subtitles` ∪ {該列 `pair.subtitle_path`};初始選取對應該列現有字幕(無則選「(無)」);`combo.activated` 接 `_on_subtitle_selected`
  - `_on_subtitle_selected(self, row: int) -> None`:讀該列 combo 的 `currentData()` 呼叫 `set_row_subtitle`
  - `_on_scan_done` 在 `populate` 前,若字幕資料夾有效則 `find_files` 掃出 `.ass` 清單存入 `self._available_subtitles`

- [ ] **Step 1: 附加失敗測試**

在 `tests/test_mux_tab.py` 末尾附加:

```python


# ---------- 手動配對:字幕欄下拉選單 ----------

def test_populate_builds_subtitle_combos(qapp, monkeypatch):
    from PySide6.QtWidgets import QComboBox
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    combo0 = tab.table.cellWidget(0, 2)
    assert isinstance(combo0, QComboBox)
    # matched 列:初始選取為其字幕
    assert combo0.currentData() == Path("a [01].ass")
    # no_subtitle 列:初始選取「(無)」→ None
    combo1 = tab.table.cellWidget(1, 2)
    assert combo1.currentData() is None


def test_combo_options_include_available_and_current(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab._available_subtitles = [Path("x [01].ass"), Path("y [02].ass")]
    tab.populate(PAIRS)
    combo0 = tab.table.cellWidget(0, 2)
    datas = [combo0.itemData(i) for i in range(combo0.count())]
    assert None in datas                       # 「(無)」選項
    assert Path("x [01].ass") in datas          # 掃描到的可用字幕
    assert Path("y [02].ass") in datas
    assert Path("a [01].ass") in datas          # 該列現有字幕(即使不在掃描清單也保留)
    assert combo0.currentData() == Path("a [01].ass")
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_mux_tab.py -v -k combo`
Expected: FAIL — `test_populate_builds_subtitle_combos` 斷言失敗(`cellWidget(0, 2)` 回 `None`,非 `QComboBox`)

- [ ] **Step 3: 實作**

(a)在 `ass_style_tool/qt/mux_tab.py` import 區(`from .scale_panel import ScalePanel` 那行附近)加:

```python
from ..episode_match import find_files
```

(b)把 `populate()` 中第 2 欄的這段(原本用 `setItem` 放字幕名文字):

```python
            self.table.setItem(
                r, 2, QTableWidgetItem(
                    pair.subtitle_path.name if pair.subtitle_path else "-"))
```

改成建立下拉選單:

```python
            combo = QComboBox()
            combo.addItem("(無)", None)
            options = list(self._available_subtitles)
            if (pair.subtitle_path is not None
                    and pair.subtitle_path not in options):
                options.append(pair.subtitle_path)
            selected_index = 0
            for i, sub in enumerate(options, start=1):
                combo.addItem(sub.name, sub)
                if sub == pair.subtitle_path:
                    selected_index = i
            combo.setCurrentIndex(selected_index)
            combo.activated.connect(
                lambda _idx, row=r: self._on_subtitle_selected(row))
            self.table.setCellWidget(r, 2, combo)
```

(c)把 `_on_scan_done` 中 `self.populate(pairs)` 那行**之前**插入字幕清單掃描:

原本:

```python
        self.scan_button.setEnabled(True)
        self.populate(pairs)
```

改成:

```python
        self.scan_button.setEnabled(True)
        s = self.subtitle_edit.text().strip()
        if s and Path(s).is_dir():
            subs, _ = find_files(Path(s))
            self._available_subtitles = sorted(subs)
        self.populate(pairs)
```

(d)在 `set_row_subtitle` 方法之後新增:

```python
    def _on_subtitle_selected(self, row: int) -> None:
        combo = self.table.cellWidget(row, 2)
        self.set_row_subtitle(row, combo.currentData())
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_mux_tab.py -v -k combo`
Expected: 2 passed

- [ ] **Step 5: 跑全套確認無回歸(含既有 10 個相容性測試)**

Run: `py -m pytest tests -q`
Expected: 261 passed(259 + 2)

若既有測試(如 `test_populate_checks_matched_only`)失敗,表示 col 2 改 `setCellWidget` 影響了勾選框讀取以外的路徑——停下來回報,不要硬改既有測試。

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/qt/mux_tab.py tests/test_mux_tab.py
git commit -m "feat: subtitle-column dropdown for manual pairing in mux tab"
```

---

## 本計畫完成後

「封裝」分頁的每一列都能手動指定字幕,自動配對失敗(ambiguous/no_subtitle/no_episode)的列也有了封裝退路。之後仍是使用者手動冒煙測試(含此手動配對流程)+ Plan 3 打包。
