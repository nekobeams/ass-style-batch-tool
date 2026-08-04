# 套用樣式「換算對照」讀出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在「樣式與預覽」分頁加一個即時「換算對照」讀出區,讓使用者一眼看懂 profile 基準值如何依檔案畫布縮放成實際套用值,並看到與影片的比例關係。

**Architecture:** 三層。(1) 把縮放數學抽成純函式 `compute_applied_values`,`apply_profile` 改用它,保證預覽數字與寫檔數字一致。(2) 新增純資料組裝函式 `build_readout`,把 profile + 檔案 PlayRes + 原字幕值 + 影片解析度組成一份可直接呈現的 `ReadoutData`(含白話說明、比例檢查、三欄對照)。(3) `PreviewPanel` 接上 UI,沿用既有 300ms 防抖訊號即時刷新。

**Tech Stack:** Python 3、PySide6(Qt Widgets)、pysubs2(既有,讀樣式)、pytest。GUI 測試在 offscreen 模式(見 `tests/conftest.py`)。

## Global Constraints

- 一律用 `py`,不要用 `python`(python 是壞的 WindowsApps stub)。測試從 repo root 跑:`py -m pytest tests -q`。
- 目前測試基線 **297 passed**,實作後必須維持全綠(新增測試會使總數上升)。
- 回覆使用者用繁體中文;commit 訊息用英文。
- 縮放/四捨五入規則必須與現有 `apply_profile` 逐欄位一致:`fontsize=round(x*scale_y)`(整數)、`outline=round(x*scale_y, 2)`、`shadow=round(x*scale_y, 2)`、`margin_l/r=round(x*scale_x)`、`margin_v=round(x*scale_y)`。
- `PreviewPanel` 既有行為(視覺預覽、時間軸、防抖、關閉清理)不可退化;`MkvWorker`/其他分頁不受本次影響。
- commit 訊息結尾加:`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- **環境坑**:PowerShell/subprocess 前先確認 CWD 在專案根目錄(見 HANDOFF)。

---

## File Structure

- `ass_style_tool/ass_style.py`(修改):新增 `AppliedValues` dataclass + `compute_applied_values()`;`apply_profile` 改用之。
- `ass_style_tool/preview_readout.py`(新增,純邏輯、無 Qt):`OriginalValues`、`ReadoutRow`、`ReadoutData` dataclass + `build_readout()`。
- `ass_style_tool/qt/preview_panel.py`(修改):新增讀出 UI 元件與更新邏輯,追蹤影片路徑並探測解析度。
- `tests/test_ass_style.py`(修改):`compute_applied_values` 單元測試 + `apply_profile` 對齊回歸。
- `tests/test_preview_readout.py`(新增):`build_readout` 純函式測試。
- `tests/test_preview_panel.py`(修改):讀出 UI 接線測試。

---

### Task 1: `compute_applied_values` 純函式 + `apply_profile` 改用

**Files:**
- Modify: `ass_style_tool/ass_style.py`(新增 dataclass + 函式;改寫 `apply_profile` 內部,對外簽章不變)
- Test: `tests/test_ass_style.py`

**Interfaces:**
- Consumes: `Profile`(`ass_style_tool.profile`)、`reference_resolution`/`compute_scale`(`ass_style_tool.resolution`,已 import)、`get_play_res`(本檔既有)。
- Produces:
  - `AppliedValues` dataclass,欄位:`scale_x: float, scale_y: float, ref_w: int, ref_h: int, fontsize: int, outline: float, shadow: float, margin_l: int, margin_r: int, margin_v: int`
  - `compute_applied_values(profile: Profile, play_res_x: int, play_res_y: int) -> AppliedValues`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_ass_style.py` 末端加入(檔案頂部 import 增加 `compute_applied_values`, `AppliedValues`):

```python
from ass_style_tool.ass_style import (apply_profile, compute_applied_values,
                                      AppliedValues, detect_and_decode,
                                      get_play_res, get_scaled_border_shadow,
                                      load_subs, save_subs)


def test_compute_applied_values_half_scale():
    # 基準 1920x1080,畫布 640x360 → scale 0.3333
    profile = make_profile()  # fontsize 72, outline 3.6, shadow 1.0, margin 20/20/24
    av = compute_applied_values(profile, 640, 360)
    assert av.ref_w == 640 and av.ref_h == 360
    assert round(av.scale_y, 3) == 0.333
    assert av.fontsize == 24          # round(72 * 1/3)
    assert av.outline == 1.2          # round(3.6 * 1/3, 2)
    assert av.shadow == 0.33          # round(1.0 * 1/3, 2)
    assert av.margin_l == 7           # round(20 * 1/3)
    assert av.margin_r == 7
    assert av.margin_v == 8           # round(24 * 1/3)


def test_compute_applied_values_identity_when_same_res():
    profile = make_profile()
    av = compute_applied_values(profile, 1920, 1080)
    assert av.scale_x == 1.0 and av.scale_y == 1.0
    assert av.fontsize == 72
    assert av.outline == 3.6
    assert av.margin_v == 24


def test_compute_applied_values_missing_playres_uses_reference():
    # 兩者皆 0 → reference_resolution 回 384x288(規範預設)
    profile = make_profile()
    av = compute_applied_values(profile, 0, 0)
    assert (av.ref_w, av.ref_h) == (384, 288)


def test_apply_profile_matches_compute_applied_values():
    # 寫檔結果必須與 compute_applied_values 完全一致
    path_subs = load_subs_from_sample()
    profile = make_profile()
    av = compute_applied_values(profile, *get_play_res(path_subs))
    apply_profile(path_subs, profile)
    style = path_subs.styles["Default"]
    assert style.fontsize == av.fontsize
    assert style.outline == av.outline
    assert style.shadow == av.shadow
    assert style.marginl == av.margin_l
    assert style.marginr == av.margin_r
    assert style.marginv == av.margin_v
```

在測試檔內加一個小工具(若尚不存在)把 SAMPLE_ASS 解析成 subs 物件:

```python
def load_subs_from_sample():
    return pysubs2.SSAFile.from_string(SAMPLE_ASS)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_ass_style.py -k "compute_applied_values or matches_compute" -q`
Expected: FAIL(`cannot import name 'compute_applied_values'`)

- [ ] **Step 3: 實作 `AppliedValues` + `compute_applied_values`**

在 `ass_style_tool/ass_style.py`:頂部 import 區加入 `from dataclasses import dataclass`(若無)。在 `apply_profile` 之前插入:

```python
@dataclass
class AppliedValues:
    """profile 套用到某 PlayRes 後,各數值欄位的換算結果。"""
    scale_x: float
    scale_y: float
    ref_w: int
    ref_h: int
    fontsize: int
    outline: float
    shadow: float
    margin_l: int
    margin_r: int
    margin_v: int


def compute_applied_values(
    profile: Profile, play_res_x: int, play_res_y: int
) -> AppliedValues:
    """依 PlayRes 規則換算 profile 目標樣式的各數值欄位。

    縮放與四捨五入規則必須與 apply_profile 寫檔時逐欄位一致,兩者共用本函式。
    """
    ref_w, ref_h = reference_resolution(play_res_x, play_res_y)
    scale_x, scale_y = compute_scale(
        ref_w, ref_h, profile.base_width, profile.base_height
    )
    t = profile.style
    return AppliedValues(
        scale_x=scale_x,
        scale_y=scale_y,
        ref_w=ref_w,
        ref_h=ref_h,
        fontsize=round(t.fontsize * scale_y),
        outline=round(t.outline * scale_y, 2),
        shadow=round(t.shadow * scale_y, 2),
        margin_l=round(t.margin_l * scale_x),
        margin_r=round(t.margin_r * scale_x),
        margin_v=round(t.margin_v * scale_y),
    )
```

- [ ] **Step 4: 改寫 `apply_profile` 內部改用 `compute_applied_values`**

把 `apply_profile` 內原本計算 `ref_w/ref_h/scale_x/scale_y` 與逐欄位 `round(...)` 的部分,換成呼叫 `compute_applied_values`(對外簽章、回傳、行為完全不變):

```python
def apply_profile(
    subs: pysubs2.SSAFile,
    profile: Profile,
    *,
    apply_to_all_styles: bool = False,
) -> List[str]:
    """把 profile 的目標樣式套用到指定名稱的 Style(依 PlayRes 規則縮放)。

    只修改 [V4+ Styles] 中對應的行;絕不改寫 Script Info 標頭、
    不新增 Style。回傳實際修改到的 Style 名稱。

    apply_to_all_styles=True 時,忽略 profile.target_style_names,改為套用到
    subs 目前實際擁有的所有 Style(供轉檔而來、無原生樣式名稱可比對的來源,
    例如 SRT 轉換後只會有單一 "Default" 樣式)。預設 False 維持既有
    依名稱精確比對的行為。
    """
    av = compute_applied_values(profile, *get_play_res(subs))
    target = profile.style
    modified: List[str] = []
    names = (
        list(subs.styles.keys()) if apply_to_all_styles
        else profile.target_style_names
    )
    for name in names:
        style = subs.styles.get(name)
        if style is None:
            continue
        style.fontname = target.fontname
        style.fontsize = av.fontsize
        style.bold = target.bold
        style.italic = target.italic
        style.primarycolor = parse_ass_color(target.primary_colour)
        style.outlinecolor = parse_ass_color(target.outline_colour)
        style.backcolor = parse_ass_color(target.back_colour)
        style.outline = av.outline
        style.shadow = av.shadow
        style.alignment = pysubs2.Alignment(target.alignment)
        style.marginl = av.margin_l
        style.marginr = av.margin_r
        style.marginv = av.margin_v
        modified.append(name)
    return modified
```

- [ ] **Step 5: 跑新測試 + 既有 apply_profile 測試,全數通過**

Run: `py -m pytest tests/test_ass_style.py -q`
Expected: PASS(含新測試與所有既有 apply_profile 回歸)

- [ ] **Step 6: Commit**

```bash
git add ass_style_tool/ass_style.py tests/test_ass_style.py
git commit -m "Extract compute_applied_values; apply_profile reuses it

Single source of truth for the PlayRes-based scaling math so the upcoming
preview readout shows exactly what apply_profile writes.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `build_readout` 純資料組裝

**Files:**
- Create: `ass_style_tool/preview_readout.py`
- Test: `tests/test_preview_readout.py`

**Interfaces:**
- Consumes: `compute_applied_values`(Task 1)、`Profile`、`resolution.aspect_mismatch`。
- Produces:
  - `OriginalValues` dataclass:`fontsize: float, outline: float, shadow: float, margin_l: int, margin_r: int, margin_v: int`
  - `ReadoutRow` dataclass:`label: str, original: str, applied: str`
  - `ReadoutData` dataclass:`mechanism: str, context_subtitle: str, context_video: str, aspect_warning: bool, rows: list[ReadoutRow], missing_message: str, note: str`
  - `build_readout(profile, play_res_x, play_res_y, original, subtitle_name, video_name, video_res) -> ReadoutData`
    - `original: Optional[OriginalValues]`(None 表示此檔案沒有目標樣式)
    - `video_name: Optional[str]`、`video_res: Optional[tuple[int, int]]`(None 表示無影片/探測失敗)

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_preview_readout.py`:

```python
from __future__ import annotations

from ass_style_tool.preview_readout import (OriginalValues, ReadoutData,
                                            build_readout)
from tests.test_profile import make_profile


def _orig():
    # 對應 SAMPLE_ASS 的 Default: fontsize 40, outline 2, shadow 1, margin 10/10/10
    return OriginalValues(fontsize=40.0, outline=2.0, shadow=1.0,
                          margin_l=10, margin_r=10, margin_v=10)


def test_build_readout_rows_original_and_applied():
    # 基準 1920x1080,畫布 640x360 → scale 0.3333
    data = build_readout(make_profile(), 640, 360, _orig(),
                         "e01.ass", None, None)
    assert data.missing_message == ""
    by_label = {r.label: (r.original, r.applied) for r in data.rows}
    assert by_label["字級"] == ("40", "24")
    assert by_label["外框"] == ("2", "1.2")
    assert by_label["陰影"] == ("1", "0.33")
    assert by_label["邊界 V"] == ("10", "8")


def test_build_readout_mechanism_mentions_base_canvas_scale():
    data = build_readout(make_profile(), 640, 360, _orig(),
                         "e01.ass", None, None)
    assert "1920×1080" in data.mechanism
    assert "640×360" in data.mechanism
    assert "0.333" in data.mechanism


def test_build_readout_no_video_shows_guidance():
    data = build_readout(make_profile(), 640, 360, _orig(),
                         "e01.ass", None, None)
    assert "載入影片" in data.context_video
    assert data.aspect_warning is False


def test_build_readout_video_aspect_match():
    # 畫布 1280x720 (16:9),影片 1920x1080 (16:9) → 相符
    data = build_readout(make_profile(), 1280, 720, _orig(),
                         "e01.ass", "e01.mkv", (1920, 1080))
    assert "比例相符" in data.context_video
    assert data.aspect_warning is False


def test_build_readout_video_aspect_mismatch():
    # 畫布 1280x720 (16:9),影片 1440x1080 (4:3) → 不符
    data = build_readout(make_profile(), 1280, 720, _orig(),
                         "e01.ass", "e01.mkv", (1440, 1080))
    assert data.aspect_warning is True
    assert "比例不符" in data.context_video


def test_build_readout_target_style_missing():
    data = build_readout(make_profile(target_style_names=["字幕"]),
                         640, 360, None, "e01.ass", None, None)
    assert data.rows == []
    assert "字幕" in data.missing_message
    assert "略過" in data.missing_message
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_preview_readout.py -q`
Expected: FAIL(`No module named 'ass_style_tool.preview_readout'`)

- [ ] **Step 3: 實作 `preview_readout.py`**

```python
"""套用樣式「換算對照」讀出的純資料組裝(無 Qt、無檔案 I/O、易測)。

把 profile + 檔案 PlayRes + 原字幕值 + 影片解析度,組成一份可直接呈現的
ReadoutData。實際數字換算一律委派給 ass_style.compute_applied_values,
確保與批次寫檔完全一致。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .ass_style import compute_applied_values
from .profile import Profile
from .resolution import aspect_mismatch


@dataclass
class OriginalValues:
    """來源字幕檔中,將被修改的目標樣式的現有數值。"""
    fontsize: float
    outline: float
    shadow: float
    margin_l: int
    margin_r: int
    margin_v: int


@dataclass
class ReadoutRow:
    label: str
    original: str
    applied: str


@dataclass
class ReadoutData:
    mechanism: str
    context_subtitle: str
    context_video: str
    aspect_warning: bool
    rows: List[ReadoutRow]
    missing_message: str
    note: str


def _fmt(value) -> str:
    """數字顯示:整數不帶小數點;小數去掉多餘尾零(1.20 → 1.2)。"""
    number = float(value)
    if number == int(number):
        return str(int(number))
    return f"{round(number, 2):g}"


def build_readout(
    profile: Profile,
    play_res_x: int,
    play_res_y: int,
    original: Optional[OriginalValues],
    subtitle_name: str,
    video_name: Optional[str],
    video_res: Optional[Tuple[int, int]],
) -> ReadoutData:
    av = compute_applied_values(profile, play_res_x, play_res_y)
    canvas_w, canvas_h = av.ref_w, av.ref_h

    mechanism = (
        f"工具把 profile(基準 {profile.base_width}×{profile.base_height})"
        f"依這個檔案的畫布 {canvas_w}×{canvas_h} "
        f"等比縮放 {av.scale_y:.3f}× 後套用"
    )
    context_subtitle = (
        f"此檔案:{subtitle_name} · 字幕畫布 {canvas_w}×{canvas_h}"
    )

    aspect_warning = False
    if video_res is not None:
        vw, vh = video_res
        aspect_warning = aspect_mismatch((canvas_w, canvas_h), (vw, vh))
        status = ("⚠ 比例不符,字幕可能被拉伸變形" if aspect_warning
                  else "比例相符 ✓")
        context_video = f"影片:{video_name} · {vw}×{vh} · {status}"
    else:
        context_video = "影片:載入影片可看到實際疊在畫面上的效果"

    note = "字型、顏色、對齊 直接採用 profile 設定(不縮放)"

    if original is None:
        names = "、".join(profile.target_style_names)
        missing_message = (
            f"此檔案沒有目標樣式「{names}」→ 套用時將略過,不會改到這個檔案"
        )
        return ReadoutData(
            mechanism=mechanism,
            context_subtitle=context_subtitle,
            context_video=context_video,
            aspect_warning=aspect_warning,
            rows=[],
            missing_message=missing_message,
            note=note,
        )

    rows = [
        ReadoutRow("字級", _fmt(original.fontsize), _fmt(av.fontsize)),
        ReadoutRow("外框", _fmt(original.outline), _fmt(av.outline)),
        ReadoutRow("陰影", _fmt(original.shadow), _fmt(av.shadow)),
        ReadoutRow("邊界 L", _fmt(original.margin_l), _fmt(av.margin_l)),
        ReadoutRow("邊界 R", _fmt(original.margin_r), _fmt(av.margin_r)),
        ReadoutRow("邊界 V", _fmt(original.margin_v), _fmt(av.margin_v)),
    ]
    return ReadoutData(
        mechanism=mechanism,
        context_subtitle=context_subtitle,
        context_video=context_video,
        aspect_warning=aspect_warning,
        rows=rows,
        missing_message="",
        note=note,
    )
```

- [ ] **Step 4: 跑測試確認通過**

Run: `py -m pytest tests/test_preview_readout.py -q`
Expected: PASS(6 個測試全綠)

- [ ] **Step 5: Commit**

```bash
git add ass_style_tool/preview_readout.py tests/test_preview_readout.py
git commit -m "Add build_readout: pure assembly for the apply-style readout

Turns profile + file PlayRes + original style values + video resolution
into a ready-to-render ReadoutData (mechanism line, aspect check, 3-column
original-to-applied table, target-missing message).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `PreviewPanel` 接上讀出 UI

**Files:**
- Modify: `ass_style_tool/qt/preview_panel.py`
- Test: `tests/test_preview_panel.py`

**Interfaces:**
- Consumes: `build_readout`, `OriginalValues`（Task 2）、`resolution.probe_video_resolution`、`ass_style.get_play_res`、既有 `load_subs`。
- Produces（供測試斷言）:
  - `PreviewPanel._update_readout()` 更新讀出元件。
  - 元件:`self.readout_mechanism`(QLabel)、`self.readout_context_sub`(QLabel)、`self.readout_context_video`(QLabel)、`self.readout_table`(QTableWidget, 3 欄)、`self.readout_missing`(QLabel)、`self.readout_note`(QLabel)。
  - `self._video_path: Optional[Path]`、`self._video_res: Optional[tuple]`、`self._source_subs`(已解析的來源 subs 或 None)。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_preview_panel.py` 末端加入(頂部視需要 import `pysubs2` 已可用;用既有 `_panel`/`FakePlayer`/`_write_sample`):

```python
# ---------- 換算對照讀出 ----------

def test_readout_populates_rows_on_set_media(qapp, tmp_path, monkeypatch):
    import ass_style_tool.qt.preview_panel as pp
    monkeypatch.setattr(pp, "probe_video_resolution", lambda path: None)
    player = FakePlayer()
    panel = _panel(player)                       # DEFAULT_VALUES: 基準 1920x1080
    panel.set_media(_write_sample(tmp_path))     # SAMPLE_ASS 畫布 1280x720
    # scale 1280/1920 = 0.6667 → 字級 72→48、原字幕 Default 40
    labels = [panel.readout_table.item(r, 0).text()
              for r in range(panel.readout_table.rowCount())]
    assert "字級" in labels
    row = labels.index("字級")
    assert panel.readout_table.item(row, 1).text() == "40"   # 原字幕現值
    assert panel.readout_table.item(row, 2).text() == "48"   # 套用後
    assert "1280×720" in panel.readout_mechanism.text()
    panel.shutdown()


def test_readout_no_video_shows_guidance(qapp, tmp_path, monkeypatch):
    import ass_style_tool.qt.preview_panel as pp
    monkeypatch.setattr(pp, "probe_video_resolution", lambda path: None)
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path))
    assert "載入影片" in panel.readout_context_video.text()
    panel.shutdown()


def test_readout_video_aspect_shown(qapp, tmp_path, monkeypatch):
    import ass_style_tool.qt.preview_panel as pp
    monkeypatch.setattr(pp, "probe_video_resolution", lambda path: (1920, 1080))
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path), video_path=Path("v.mkv"))
    # 畫布 1280x720 (16:9) vs 1920x1080 (16:9) → 相符
    assert "比例相符" in panel.readout_context_video.text()
    panel.shutdown()


def test_readout_updates_on_style_change(qapp, tmp_path, monkeypatch):
    import ass_style_tool.qt.preview_panel as pp
    monkeypatch.setattr(pp, "probe_video_resolution", lambda path: None)
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path))
    before = panel.readout_mechanism.text()
    panel._apply_preview()                       # 防抖到期會走的路徑
    assert panel.readout_mechanism.text() == before   # 同一 profile → 穩定
    panel.shutdown()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_preview_panel.py -k readout -q`
Expected: FAIL(`AttributeError: 'PreviewPanel' object has no attribute 'readout_table'` 或 `probe_video_resolution`)

- [ ] **Step 3: 加入 import 與新狀態**

在 `ass_style_tool/qt/preview_panel.py`:

頂部 import 區補上(`QGroupBox`, `QTableWidget`, `QTableWidgetItem`, `QAbstractItemView`, `QHeaderView` 加進既有 `PySide6.QtWidgets` import;新增模組 import):

```python
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QSlider,
                               QSplitter, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..ass_style import get_play_res, load_subs
from ..preview import render_preview_ass
from ..preview_readout import OriginalValues, build_readout
from ..profile import Profile
from ..resolution import probe_video_resolution
```

在 `__init__` 內(`self._scrubbing = False` 之後)新增狀態:

```python
        self._video_path: Optional[Path] = None
        self._video_res: Optional[tuple] = None
        self._source_subs = None
```

- [ ] **Step 4: 建立讀出 UI 元件**

在 `__init__` 中,建立 `self.status` 之前,加入讀出區並加到 `root`:

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

（`root.addWidget(self.status)` 維持在其後。)

- [ ] **Step 5: 追蹤影片路徑並探測解析度**

新增 helper,並在 `set_media`/`_open_video` 呼叫。`set_media` 改為在載入影片時記錄路徑:

```python
    def _set_video(self, path: Optional[Path]) -> None:
        """記錄目前影片路徑並探測解析度(供比例檢查用);探測失敗回 None。"""
        self._video_path = Path(path) if path is not None else None
        if self._video_path is None:
            self._video_res = None
            return
        try:
            self._video_res = probe_video_resolution(self._video_path)
        except Exception:
            self._video_res = None
```

修改 `set_media`(在 `if video_path is not None:` 區塊內呼叫 `_set_video`):

```python
    def set_media(self, sub_path: Path,
                  video_path: Optional[Path] = None) -> None:
        self._source_sub = Path(sub_path)
        if video_path is not None:
            self._set_video(Path(video_path))
            self.player.load_video(Path(video_path))
        self._refresh_lines()
        self._apply_preview()
```

修改 `_open_video`(選檔後記錄影片):

```python
    def _open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "開啟影片", "",
            "影片 (*.mkv *.mp4 *.avi *.webm *.ts);;所有檔案 (*)")
        if path:
            self._set_video(Path(path))
            self.player.load_video(Path(path))
            self._apply_preview()
```

- [ ] **Step 6: 快取來源 subs + 實作 `_update_readout`,並接進 `_apply_preview`**

在 `_refresh_lines` 成功載入後快取 subs(把 `subs = load_subs(...)` 的結果存到 `self._source_subs`,失敗時設 None):

```python
    def _refresh_lines(self) -> None:
        self.line_list.clear()
        if self._source_sub is None:
            return
        try:
            subs = load_subs(self._source_sub)
        except Exception as exc:  # 單檔讀取失敗只顯示狀態,不中斷
            self.status.setText(f"字幕讀取失敗: {exc}")
            self._source_subs = None
            return
        self._source_subs = subs
        for line in dialogue_lines(subs):
            item = QListWidgetItem(
                f"{format_timestamp(line.start_ms)}  {line.text}")
            item.setData(Qt.UserRole, line.start_ms)
            self.line_list.addItem(item)
        self.status.setText(
            f"{self._source_sub.name}(共 {self.line_list.count()} 行,點擊跳轉)")
```

新增查目標樣式現值與更新讀出的方法:

```python
    def _lookup_original(self, profile: Profile):
        """回傳來源字幕中第一個存在的目標樣式現值;都不存在回 None。"""
        if self._source_subs is None:
            return None
        for name in profile.target_style_names:
            style = self._source_subs.styles.get(name)
            if style is not None:
                return OriginalValues(
                    fontsize=style.fontsize, outline=style.outline,
                    shadow=style.shadow, margin_l=style.marginl,
                    margin_r=style.marginr, margin_v=style.marginv)
        return None

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
        self.readout_mechanism.setText(data.mechanism)
        self.readout_context_sub.setText(data.context_subtitle)
        self.readout_context_video.setText(data.context_video)
        self.readout_note.setText(data.note)
        if data.missing_message:
            self.readout_missing.setText(data.missing_message)
            self.readout_missing.show()
            self.readout_table.hide()
        else:
            self.readout_missing.hide()
            self.readout_table.show()
            self.readout_table.setRowCount(len(data.rows))
            for r, row in enumerate(data.rows):
                self.readout_table.setItem(r, 0, QTableWidgetItem(row.label))
                self.readout_table.setItem(r, 1, QTableWidgetItem(row.original))
                self.readout_table.setItem(r, 2, QTableWidgetItem(row.applied))
```

修改 `_apply_preview`,讓讀出在渲染成功與否都會更新,且無效 profile 時略過(保留舊值):

```python
    def _apply_preview(self) -> None:
        if self._source_sub is None:
            return
        try:
            profile = self._get_profile()
        except ValueError:
            return  # 欄位打到一半暫時無效,略過本次防抖
        try:
            render_preview_ass(self._source_sub, profile, self._temp_ass)
            if self.player.video_loaded():
                self.player.show_subtitle(self._temp_ass)
        except Exception as exc:
            self.status.setText(f"預覽產生失敗: {exc}")
        self._update_readout()
```

- [ ] **Step 7: 跑讀出測試 + 既有 preview_panel 全套**

Run: `py -m pytest tests/test_preview_panel.py -q`
Expected: PASS（新增 readout 測試 + 既有 12 個測試全綠）

- [ ] **Step 8: 跑全套測試確認無回歸**

Run: `py -m pytest tests -q`
Expected: PASS(297 + 新增測試,全綠)

- [ ] **Step 9: Commit**

```bash
git add ass_style_tool/qt/preview_panel.py tests/test_preview_panel.py
git commit -m "Wire the apply-style readout into PreviewPanel

Live 換算對照 panel: mechanism line, subtitle canvas + video aspect check,
and a 原字幕現值→套用後 table. Updates on file load and on style edits via
the existing debounce; probes video resolution once per loaded video.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- 單一計算來源 `compute_applied_values` + `apply_profile` 改用 → Task 1 ✓
- 三層讀出(白話機制說明 / 情境行 + 比例檢查 / 三欄對照表)→ `build_readout`(Task 2)+ UI(Task 3)✓
- 目標樣式不存在的「將略過」呈現 → Task 2 `missing_message` + Task 3 `readout_missing` ✓
- 影片比例檢查(`aspect_mismatch`)、無影片降級文字 → Task 2 + Task 3 ✓
- 更新時機沿用既有 300ms 防抖訊號 → Task 3 `_apply_preview` 末端呼叫 `_update_readout` ✓
- 影片解析度用既有 `probe_video_resolution`、探測失敗優雅降級、每部影片探測一次(快取)→ Task 3 `_set_video` ✓
- 「不縮放欄位」一句話說明 note → Task 2/3 ✓
- 保證讀出數字 == 寫檔數字 → Task 1 共用函式 + `test_apply_profile_matches_compute_applied_values` ✓
- 測試計畫(純函式、apply_profile 回歸、資料組裝、UI 接線、既有全綠)→ 各 Task 測試步驟涵蓋 ✓

**2. Placeholder scan:** 無 TBD/TODO;每個 code step 均含完整程式碼與可執行指令。

**3. Type consistency:** `AppliedValues`(Task 1)欄位在 `build_readout`(Task 2)以 `av.fontsize/outline/shadow/margin_*/ref_w/ref_h/scale_y` 使用一致;`OriginalValues`/`ReadoutData` 欄位在 Task 3 `_lookup_original`/`_update_readout` 使用一致(`marginl/marginr/marginv` 為 pysubs2 屬性名,對應 `OriginalValues.margin_l/r/v`);`probe_video_resolution`、`get_play_res`、`build_readout` 簽章跨 Task 一致。

## 範圍外(本計畫不做)

- 視覺渲染器改動(已存在,只加無影片時的引導文字)。
- 字幕檔分頁整批 log 試算(套用樣式版 dry-run)。
- 顏色/字型的視覺化對比(色塊、字型樣本)。
