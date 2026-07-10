# 縮放字級模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「縮放字級」批次模式——保持原樣式不變,只把所有 Style 的 Fontsize(與 Outline/Shadow、inline `\fs`)等比縮放,逐行處理保留原編碼/換行/註解;整合進 GUI 的「字幕檔」分頁作為與「套用樣式」並列的操作模式,含試算預覽(dry-run)。

**Architecture:** 新的 `scale_engine.py` 是獨立的逐行縮放引擎(不用 pysubs2,因為要保留檔案原貌只改數值)。GUI 端新增 `ScalePanel` widget 與 `ScaleWorker`,掛進既有 `SubtitleFileTab` 的操作模式切換;掃描、輸出模式、進度/取消全部沿用現有機制。

**Tech Stack:** Python 3.13、charset-normalizer、PySide6、pytest(offscreen Qt)。

**Spec:** `docs/superpowers/specs/2026-07-10-scale-mode-design.md`

## Global Constraints

- 工作目錄/repo root:`C:\Claude_code`,git branch 由執行者依 subagent-driven 流程建立
- **環境重點**:`python` 是壞的 Windows Store stub,一律用 `py`:`py -m pytest tests -v`
- Python 3.9+ 相容;每個新模組頂端加 `from __future__ import annotations`
- 引擎**不得**使用 pysubs2(會重排整檔);逐行處理,只改必要數值,不動註解(`;` 開頭)、其他 section、`[Script Info]` 的 PlayResX/PlayResY
- 保留原始編碼(含 BOM 狀態)與原始換行符(CRLF/LF 依各行原樣)
- 數值格式:四捨五入到 1 位小數,能整數就輸出整數(`fmt_num`)
- inline 標籤:`\fs` 後緊接數字才縮放(自然排除 `\fscx`/`\fscy`/`\fsp`);`\fscx`/`\fscy` 僅在選項開啟時縮放
- 原地模式:`.bak` 已存在則不覆蓋備份(沿用專案既有原則)
- 既有「套用樣式」流程行為不變;不動 v1/v2 已合入模組除非任務明確要求
- Qt 測試用既有 `tests/conftest.py` 的 offscreen `qapp` fixture
- 測試指令:`py -m pytest tests -v`(從 repo root;目前基準 127 passed)
- Commit 訊息用 conventional commits

### 既有介面(本計畫會用到)

- `tests/conftest.py`:session 級 `qapp` fixture(QT_QPA_PLATFORM=offscreen)
- `ass_style_tool.batch_runner.ScanResult`(matches, warnings)、`episode_match.MatchResult`(sub_path, episode, video_path, video_resolution, status)
- `ass_style_tool.qt.subtitle_tab.SubtitleFileTab`:欄位 `folder_edit/table/inplace_radio/outdir_radio/outdir_edit/scan_button/run_button/cancel_button/progress`、signal `log(str)`、`populate_preview(scan)`、`_output_dir() -> Path|None`、`_on_run/_on_finished/_on_progress/_on_cancel`、`shutdown()`
- `ass_style_tool.qt.batch_worker.BatchWorker`:signals `progress(int,int)/file_done(str,str)/message(str)/finished(int,int,int)`、`run()/cancel()`
- `tests.test_ass_style.SAMPLE_ASS`(v4+,PlayRes 1280x720,Default fontsize 40 outline 2 shadow 1;OP fontsize 60)

## File Structure

```
ass_style_tool/
└── scale_engine.py       # ScaleOptions/ScaleReport、fmt_num、Format 解析、scale_text、編碼偵測、scale_file
ass_style_tool/qt/
├── scale_panel.py        # ScalePanel(QWidget):倍率/目標二選一、勾選項、get_options()
├── batch_worker.py       # (修改)新增 ScaleWorker
└── subtitle_tab.py       # (修改)操作模式切換、掛 ScalePanel、試算預覽、執行分流
tests/
├── test_scale_engine.py
└── test_scale_gui.py
```

---

### Task 1: scale_engine — 數值格式、Format 解析、Style 縮放(scale_text 核心)

**Files:**
- Create: `ass_style_tool/scale_engine.py`
- Test: `tests/test_scale_engine.py`

**Interfaces:**
- Consumes: 無(純邏輯;本任務尚不含編碼/檔案 I/O)
- Produces:
  - `ScaleError(ValueError)`
  - `ScaleOptions` dataclass:`factor: float|None = None, target_size: float|None = None, base_style: str = "Default", scale_decorations: bool = True, scale_inline_fs: bool = True, scale_fscxy: bool = False`;method `validate()`(factor/target 恰一個、皆須 > 0,違反丟 `ScaleError`)
  - `StyleChange` dataclass:`name: str, old_size: str, new_size: str`
  - `ScaleReport` dataclass:`style_changes: list[StyleChange]`(default 空)、`inline_fs_count: int = 0`、`factor_used: float = 1.0`
  - `fmt_num(value: float) -> str`
  - `parse_format_indices(format_line: str) -> dict[str, int]`(欄位小寫名 → index)
  - `scale_text(text: str, options: ScaleOptions) -> tuple[str, ScaleReport]`(本任務先完成 Style 縮放;Events 留 Task 2 擴充)

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_scale_engine.py`:

```python
from __future__ import annotations

import pytest

from ass_style_tool.scale_engine import (ScaleError, ScaleOptions,
                                         fmt_num, parse_format_indices,
                                         scale_text)

V4PLUS_SAMPLE = (
    "[Script Info]\r\n"
    "; 這是註解,不可被更動\r\n"
    "PlayResX: 1280\r\n"
    "PlayResY: 720\r\n"
    "\r\n"
    "[V4+ Styles]\r\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
    "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
    "Alignment, MarginL, MarginR, MarginV, Encoding\r\n"
    "Style: Default,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
    "0,0,0,0,100,100,0,0,1,2,1,2,10,10,10,1\r\n"
    "Style: OP,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
    "0,0,0,0,100,100,0,0,1,2,1,8,10,10,10,1\r\n"
    "\r\n"
    "[Events]\r\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\r\n"
    "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,測試字幕\r\n"
)

# v4(SSA)欄位順序不同:Fontsize 在第 3 欄之外的位置、無 Outline 欄名(TertiaryColour 等)
V4_SAMPLE = (
    "[V4 Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "TertiaryColour, BackColour, Bold, Italic, BorderStyle, Outline, "
    "Shadow, Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding\n"
    "Style: Default,Arial,20,16777215,255,0,0,0,0,1,2,1,2,10,10,10,0,1\n"
)


# ---------- fmt_num ----------

def test_fmt_num_integer():
    assert fmt_num(40.0) == "40"


def test_fmt_num_rounds_to_one_decimal():
    assert fmt_num(40.55) in ("40.5", "40.6")  # 浮點表示法邊界,兩者皆可接受
    assert fmt_num(40.44) == "40.4"


def test_fmt_num_no_trailing_zero():
    assert fmt_num(50.0000001) == "50"


def test_fmt_num_keeps_half():
    assert fmt_num(40.5) == "40.5"


# ---------- parse_format_indices ----------

def test_parse_format_indices_v4plus():
    line = ("Format: Name, Fontname, Fontsize, PrimaryColour, Outline, "
            "Shadow, Alignment")
    idx = parse_format_indices(line)
    assert idx["name"] == 0
    assert idx["fontsize"] == 2
    assert idx["outline"] == 4
    assert idx["shadow"] == 5


def test_parse_format_indices_tolerates_spacing():
    idx = parse_format_indices("Format:Name,Fontsize , Outline")
    assert idx == {"name": 0, "fontsize": 1, "outline": 2}


# ---------- ScaleOptions.validate ----------

def test_options_requires_exactly_one_mode():
    with pytest.raises(ScaleError):
        ScaleOptions().validate()
    with pytest.raises(ScaleError):
        ScaleOptions(factor=1.5, target_size=60).validate()


def test_options_rejects_nonpositive():
    with pytest.raises(ScaleError):
        ScaleOptions(factor=0).validate()
    with pytest.raises(ScaleError):
        ScaleOptions(target_size=-5).validate()


# ---------- scale_text:倍率模式 ----------

def test_scale_factor_mode():
    out, report = scale_text(V4PLUS_SAMPLE, ScaleOptions(factor=1.5))
    assert "Style: Default,Arial,60," in out
    assert "Style: OP,Arial,90," in out
    assert report.factor_used == 1.5
    assert [(c.name, c.old_size, c.new_size) for c in report.style_changes] == [
        ("Default", "40", "60"), ("OP", "60", "90")]


def test_scale_factor_scales_outline_shadow():
    out, _ = scale_text(V4PLUS_SAMPLE, ScaleOptions(factor=2))
    # Default: Outline 2->4, Shadow 1->2(欄位位置依 Format 動態解析)
    assert ",1,4,2,2,10,10,10,1" in out


def test_scale_no_decorations():
    out, _ = scale_text(
        V4PLUS_SAMPLE, ScaleOptions(factor=2, scale_decorations=False))
    assert ",1,2,1,2,10,10,10,1" in out  # Outline/Shadow 不變


def test_scale_v4_ssa_format():
    out, report = scale_text(V4_SAMPLE, ScaleOptions(factor=2))
    assert "Style: Default,Arial,40," in out
    assert report.style_changes[0].new_size == "40"


# ---------- scale_text:目標模式 ----------

def test_target_mode_scales_proportionally():
    out, report = scale_text(
        V4PLUS_SAMPLE, ScaleOptions(target_size=50, base_style="Default"))
    assert "Style: Default,Arial,50," in out
    assert "Style: OP,Arial,75," in out  # 60 * (50/40)
    assert report.factor_used == pytest.approx(1.25)


def test_target_mode_falls_back_to_first_style():
    out, _ = scale_text(
        V4PLUS_SAMPLE, ScaleOptions(target_size=80, base_style="不存在"))
    # 用第一個 style(Default, 40)當基準:factor=2
    assert "Style: Default,Arial,80," in out
    assert "Style: OP,Arial,120," in out


# ---------- 完整性 ----------

def test_comments_and_playres_untouched():
    out, _ = scale_text(V4PLUS_SAMPLE, ScaleOptions(factor=3))
    assert "; 這是註解,不可被更動" in out
    assert "PlayResX: 1280" in out
    assert "PlayResY: 720" in out


def test_factor_one_is_identity():
    out, _ = scale_text(V4PLUS_SAMPLE, ScaleOptions(factor=1.0))
    assert out == V4PLUS_SAMPLE  # 逐字元一致(含 CRLF)


def test_not_ass_raises():
    with pytest.raises(ScaleError):
        scale_text("hello\nworld\n", ScaleOptions(factor=2))
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_scale_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.scale_engine'`

- [ ] **Step 3: 實作 scale_engine.py(本任務範圍)**

建立 `ass_style_tool/scale_engine.py`:

```python
"""等比縮放 ASS/SSA 字級的逐行引擎:保留編碼、換行與所有非目標內容。

刻意不用 pysubs2:pysubs2 會重寫整個檔案(欄位正規化、統一編碼與換行),
而本引擎的契約是「只改必要的數值,其餘位元組原樣保留」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


class ScaleError(ValueError):
    """檔案無法安全縮放(非 ASS 內容、基準樣式無效、選項矛盾等)。"""


@dataclass
class ScaleOptions:
    factor: Optional[float] = None
    target_size: Optional[float] = None
    base_style: str = "Default"
    scale_decorations: bool = True
    scale_inline_fs: bool = True
    scale_fscxy: bool = False

    def validate(self) -> None:
        if (self.factor is None) == (self.target_size is None):
            raise ScaleError("倍率與目標大小必須恰好指定一個")
        if self.factor is not None and self.factor <= 0:
            raise ScaleError("倍率必須大於 0")
        if self.target_size is not None and self.target_size <= 0:
            raise ScaleError("目標大小必須大於 0")


@dataclass
class StyleChange:
    name: str
    old_size: str
    new_size: str


@dataclass
class ScaleReport:
    style_changes: List[StyleChange] = field(default_factory=list)
    inline_fs_count: int = 0
    factor_used: float = 1.0


def fmt_num(value: float) -> str:
    """四捨五入到 1 位小數;能整數就輸出整數(不產生 '40.0')。"""
    rounded = round(value, 1)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.1f}"


_STYLES_SECTIONS = {"[v4+ styles]", "[v4 styles]"}
_EVENTS_SECTION = "[events]"


def parse_format_indices(format_line: str) -> Dict[str, int]:
    """解析 'Format: ...' 行,回傳 {欄位小寫名: index}。不可寫死欄位位置。"""
    _, _, rest = format_line.partition(":")
    fields = [f.strip().lower() for f in rest.split(",")]
    return {name: i for i, name in enumerate(fields)}


def _split_line_ending(line: str) -> Tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def _replace_preserving_space(part: str, new_core: str) -> str:
    lead = part[: len(part) - len(part.lstrip())]
    trail = part[len(part.rstrip()):]
    return f"{lead}{new_core}{trail}"


def _iter_style_sizes(lines: List[str]):
    """依序產出 (style名, fontsize float);供目標模式找基準用。"""
    section = ""
    fmt: Optional[Dict[str, int]] = None
    for raw in lines:
        content, _ = _split_line_ending(raw)
        stripped = content.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.lower()
            fmt = None
            continue
        if section not in _STYLES_SECTIONS:
            continue
        low = stripped.lower()
        if low.startswith("format:"):
            fmt = parse_format_indices(content)
        elif low.startswith("style:") and fmt is not None and "fontsize" in fmt:
            _, _, rest = content.partition(":")
            parts = rest.split(",")
            idx = fmt["fontsize"]
            if len(parts) <= idx:
                continue
            name_idx = fmt.get("name", 0)
            name = parts[name_idx].strip() if len(parts) > name_idx else ""
            try:
                yield name, float(parts[idx].strip())
            except ValueError:
                continue


def _determine_factor(lines: List[str], options: ScaleOptions) -> float:
    if options.factor is not None:
        return options.factor
    first_size: Optional[float] = None
    base_size: Optional[float] = None
    for name, size in _iter_style_sizes(lines):
        if first_size is None:
            first_size = size
        if name == options.base_style:
            base_size = size
            break
    size = base_size if base_size is not None else first_size
    if size is None or size <= 0:
        raise ScaleError("找不到有效的基準 Style Fontsize")
    return options.target_size / size


def _scale_style_line(content: str, fmt: Dict[str, int], factor: float,
                      options: ScaleOptions, report: ScaleReport) -> str:
    prefix, colon, rest = content.partition(":")
    parts = rest.split(",")
    idx = fmt["fontsize"]
    if len(parts) <= idx:
        return content
    old_raw = parts[idx].strip()
    try:
        old_size = float(old_raw)
    except ValueError:
        return content
    name_idx = fmt.get("name", 0)
    name = parts[name_idx].strip() if len(parts) > name_idx else ""
    if options.target_size is not None and name == options.base_style:
        new_text = fmt_num(options.target_size)
    else:
        new_text = fmt_num(old_size * factor)
    parts[idx] = _replace_preserving_space(parts[idx], new_text)
    if options.scale_decorations:
        for key in ("outline", "shadow"):
            j = fmt.get(key)
            if j is not None and j < len(parts):
                try:
                    old_val = float(parts[j].strip())
                except ValueError:
                    continue
                parts[j] = _replace_preserving_space(
                    parts[j], fmt_num(old_val * factor))
    report.style_changes.append(
        StyleChange(name=name, old_size=old_raw, new_size=new_text))
    return prefix + colon + ",".join(parts)


def _scale_event_line(content: str, factor: float, options: ScaleOptions,
                      report: ScaleReport) -> str:
    # Task 2 實作 inline \fs 縮放;本任務先原樣返回
    return content


def scale_text(text: str, options: ScaleOptions) -> Tuple[str, ScaleReport]:
    """對整份 ASS 文字做等比縮放。回傳 (新文字, 報告);非 ASS 丟 ScaleError。"""
    options.validate()
    lines = text.splitlines(keepends=True)
    has_styles = any(
        _split_line_ending(l)[0].strip().lower() in _STYLES_SECTIONS
        for l in lines)
    if not has_styles:
        raise ScaleError("找不到 [V4+ Styles]/[V4 Styles],不是 ASS/SSA 內容")
    factor = _determine_factor(lines, options)
    report = ScaleReport(factor_used=factor)

    out: List[str] = []
    section = ""
    fmt: Optional[Dict[str, int]] = None
    for raw in lines:
        content, ending = _split_line_ending(raw)
        stripped = content.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.lower()
            fmt = None
            out.append(raw)
            continue
        if section in _STYLES_SECTIONS:
            low = stripped.lower()
            if low.startswith("format:"):
                fmt = parse_format_indices(content)
            elif (low.startswith("style:") and fmt is not None
                  and "fontsize" in fmt):
                content = _scale_style_line(content, fmt, factor, options,
                                            report)
        elif section == _EVENTS_SECTION:
            content = _scale_event_line(content, factor, options, report)
        out.append(content + ending)
    return "".join(out), report
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_scale_engine.py -v`
Expected: 16 passed

- [ ] **Step 5: 跑全套確認無回歸**

Run: `py -m pytest tests -v`
Expected: 143 passed(127 + 16)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/scale_engine.py tests/test_scale_engine.py
git commit -m "feat: add line-based scale engine (format parsing, style scaling)"
```

---

### Task 2: scale_engine — inline `\fs` 與 `\fscx/\fscy` 縮放

**Files:**
- Modify: `ass_style_tool/scale_engine.py`(實作 `_scale_event_line`)
- Test: `tests/test_scale_engine.py`(附加測試)

**Interfaces:**
- Consumes: Task 1 的 `scale_text/_scale_event_line/fmt_num/ScaleReport`
- Produces: `_scale_event_line` 完整行為——只處理 `Dialogue:`/`Comment:` 開頭的行;`scale_inline_fs` 時縮放 `\fs<數字>`(每處 `report.inline_fs_count += 1`);`scale_fscxy` 時同法處理 `\fscx<數字>`/`\fscy<數字>`

- [ ] **Step 1: 附加失敗測試(tests/test_scale_engine.py 末尾)**

```python
# ---------- inline \fs ----------

INLINE_SAMPLE = (
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, Outline, Shadow\n"
    "Style: Default,Arial,40,2,1\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\fs40}大字{\\b1\\fs20.5}小字\n"
    "Dialogue: 0,0:00:04.00,0:00:06.00,Default,,0,0,0,,{\\fscx100\\fscy100\\fsp2}不動\n"
)


def test_inline_fs_scaled():
    out, report = scale_text(INLINE_SAMPLE, ScaleOptions(factor=2))
    assert "{\\fs80}大字" in out
    assert "\\fs41}小字" in out  # 20.5*2=41,整數輸出
    assert report.inline_fs_count == 2


def test_inline_fs_does_not_touch_fscx_fscy_fsp():
    out, _ = scale_text(INLINE_SAMPLE, ScaleOptions(factor=2))
    assert "\\fscx100" in out
    assert "\\fscy100" in out
    assert "\\fsp2" in out


def test_inline_fs_disabled():
    out, report = scale_text(
        INLINE_SAMPLE, ScaleOptions(factor=2, scale_inline_fs=False))
    assert "{\\fs40}大字" in out
    assert report.inline_fs_count == 0


def test_fscxy_opt_in():
    out, report = scale_text(
        INLINE_SAMPLE, ScaleOptions(factor=2, scale_fscxy=True))
    assert "\\fscx200" in out
    assert "\\fscy200" in out
    assert "\\fsp2" in out          # \fsp 永遠不動
    assert report.inline_fs_count == 4  # 2 個 \fs + 2 個 \fscx/y


def test_comment_lines_also_scaled():
    # Events 內的 Comment: 行同樣處理(與 Dialogue 一致)
    text = INLINE_SAMPLE.replace(
        "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\fs40}大字{\\b1\\fs20.5}小字",
        "Comment: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\fs40}大字{\\b1\\fs20.5}小字")
    out, report = scale_text(text, ScaleOptions(factor=2))
    assert "{\\fs80}大字" in out
    assert report.inline_fs_count == 2


def test_inline_fs_identity_at_factor_one():
    out, _ = scale_text(INLINE_SAMPLE, ScaleOptions(factor=1.0))
    assert out == INLINE_SAMPLE
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_scale_engine.py -v`
Expected: 新增 6 個中多數 FAIL(inline 尚未實作,`test_inline_fs_scaled` 等斷言失敗)

- [ ] **Step 3: 實作 `_scale_event_line`(替換 Task 1 的佔位版本)**

在 `scale_engine.py` 模組層(`_EVENTS_SECTION` 定義附近)加入正則:

```python
#: \fs 後必須緊接數字 → 自然排除 \fscx、\fscy、\fsp 等其他標籤
_FS_RE = re.compile(r"(\\fs)(\d+(?:\.\d+)?)")
_FSCXY_RE = re.compile(r"(\\fsc[xy])(\d+(?:\.\d+)?)")
```

把佔位的 `_scale_event_line` 整個替換為:

```python
def _scale_event_line(content: str, factor: float, options: ScaleOptions,
                      report: ScaleReport) -> str:
    low = content.lstrip().lower()
    if not (low.startswith("dialogue:") or low.startswith("comment:")):
        return content

    def _sub(match: "re.Match[str]") -> str:
        report.inline_fs_count += 1
        return match.group(1) + fmt_num(float(match.group(2)) * factor)

    if options.scale_inline_fs:
        content = _FS_RE.sub(_sub, content)
    if options.scale_fscxy:
        content = _FSCXY_RE.sub(_sub, content)
    return content
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_scale_engine.py -v`
Expected: 22 passed(16 + 6)

- [ ] **Step 5: Commit**

```powershell
git add ass_style_tool/scale_engine.py tests/test_scale_engine.py
git commit -m "feat: scale inline \\fs override tags with fscx/fscy opt-in"
```

---

### Task 3: scale_engine — 編碼/換行保留與檔案 I/O

**Files:**
- Modify: `ass_style_tool/scale_engine.py`(附加編碼與檔案函式)
- Test: `tests/test_scale_engine.py`(附加測試)

**Interfaces:**
- Consumes: Task 1-2 的 `scale_text/ScaleOptions/ScaleReport/ScaleError`
- Produces:
  - `SubtitleCodec` dataclass:`bom: bytes, codec: str`;methods `decode(raw: bytes) -> str`、`encode(text: str) -> bytes`(encode 補回 BOM)
  - `detect_codec(raw: bytes) -> SubtitleCodec` — 依序:UTF-8 BOM → UTF-16 LE/BE BOM → 無 BOM UTF-8 嚴格解碼 → charset-normalizer;全失敗丟 `ScaleError`
  - `read_subtitle_text(path: Path) -> tuple[str, SubtitleCodec]`
  - `scale_file(path: Path, options: ScaleOptions, out_path: Path | None = None) -> ScaleReport` — `out_path=None` 原地(先備份 `.bak`,已存在不覆蓋);寫回用原 codec(位元組級保留編碼與 BOM)

- [ ] **Step 1: 附加失敗測試(tests/test_scale_engine.py 末尾)**

```python
# ---------- 編碼與檔案 I/O ----------
from pathlib import Path

from ass_style_tool.scale_engine import (detect_codec, read_subtitle_text,
                                         scale_file)

BIG5_TEXT = (
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, Outline, Shadow\n"
    "Style: Default,細明體,40,2,1\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,繁體中文字幕內容測試\n"
)


def test_detect_utf8_bom():
    codec = detect_codec(b"\xef\xbb\xbf[V4+ Styles]\n")
    assert codec.bom == b"\xef\xbb\xbf"
    assert codec.codec == "utf-8"


def test_detect_plain_utf8():
    codec = detect_codec("中文".encode("utf-8"))
    assert codec.bom == b""
    assert codec.codec == "utf-8"


def test_detect_utf16_le_bom_roundtrip():
    raw = b"\xff\xfe" + "abc\n中".encode("utf-16-le")
    codec = detect_codec(raw)
    assert codec.encode(codec.decode(raw)) == raw


def test_big5_roundtrip_bytes(tmp_path):
    raw = BIG5_TEXT.encode("big5")
    p = tmp_path / "b.ass"
    p.write_bytes(raw)
    text, codec = read_subtitle_text(p)
    assert "繁體中文字幕內容測試" in text
    assert codec.encode(text) == raw  # Big5 進 Big5 出,位元組一致


def test_scale_file_identity_factor_one_is_byte_identical(tmp_path):
    raw = b"\xef\xbb\xbf" + BIG5_TEXT.encode("utf-8")  # UTF-8 with BOM
    p = tmp_path / "a.ass"
    p.write_bytes(raw)
    out = tmp_path / "out.ass"
    scale_file(p, ScaleOptions(factor=1.0), out)
    assert out.read_bytes() == raw  # 倍率 1.0 輸出與輸入位元組一致(含 BOM)


def test_scale_file_inplace_backs_up_once(tmp_path):
    p = tmp_path / "a.ass"
    p.write_text(BIG5_TEXT, encoding="utf-8")
    original = p.read_bytes()
    report = scale_file(p, ScaleOptions(factor=2))
    assert report.style_changes[0].new_size == "80"
    backup = tmp_path / "a.ass.bak"
    assert backup.read_bytes() == original
    # 第二次原地縮放不可覆蓋原始備份
    scale_file(p, ScaleOptions(factor=2))
    assert backup.read_bytes() == original


def test_scale_file_outdir_leaves_original(tmp_path):
    p = tmp_path / "a.ass"
    p.write_text(BIG5_TEXT, encoding="utf-8")
    original = p.read_bytes()
    out = tmp_path / "out" / "a.ass"
    scale_file(p, ScaleOptions(factor=2), out)
    assert p.read_bytes() == original
    assert "Style: Default,細明體,80,4,2" in out.read_text(encoding="utf-8")


def test_crlf_preserved(tmp_path):
    text = BIG5_TEXT.replace("\n", "\r\n")
    p = tmp_path / "a.ass"
    p.write_bytes(text.encode("utf-8"))
    out = tmp_path / "out.ass"
    scale_file(p, ScaleOptions(factor=2), out)
    data = out.read_bytes()
    assert b"\r\n" in data
    assert b"\n" not in data.replace(b"\r\n", b"")  # 沒有孤兒 LF
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_scale_engine.py -v`
Expected: FAIL — `ImportError: cannot import name 'detect_codec'`

- [ ] **Step 3: 實作(附加到 scale_engine.py)**

import 區加入:

```python
import codecs
import shutil
from pathlib import Path

from charset_normalizer import from_bytes
```

檔案末尾附加:

```python
@dataclass
class SubtitleCodec:
    bom: bytes
    codec: str

    def decode(self, raw: bytes) -> str:
        return raw[len(self.bom):].decode(self.codec)

    def encode(self, text: str) -> bytes:
        return self.bom + text.encode(self.codec)


def detect_codec(raw: bytes) -> SubtitleCodec:
    """偵測編碼並記住 BOM 狀態,讓寫回能位元組級保留原編碼。"""
    if raw.startswith(codecs.BOM_UTF8):
        return SubtitleCodec(codecs.BOM_UTF8, "utf-8")
    if raw.startswith(codecs.BOM_UTF16_LE):
        return SubtitleCodec(codecs.BOM_UTF16_LE, "utf-16-le")
    if raw.startswith(codecs.BOM_UTF16_BE):
        return SubtitleCodec(codecs.BOM_UTF16_BE, "utf-16-be")
    try:
        raw.decode("utf-8")
        return SubtitleCodec(b"", "utf-8")
    except UnicodeDecodeError:
        pass
    best = from_bytes(raw).best()
    if best is None:
        raise ScaleError("無法判斷檔案編碼")
    return SubtitleCodec(b"", best.encoding)


def read_subtitle_text(path: Path) -> Tuple[str, SubtitleCodec]:
    raw = Path(path).read_bytes()
    codec = detect_codec(raw)
    return codec.decode(raw), codec


def scale_file(path: Path, options: ScaleOptions,
               out_path: Optional[Path] = None) -> ScaleReport:
    """縮放單一檔案。out_path=None 表原地(先備份 .bak,已存在不覆蓋)。"""
    text, codec = read_subtitle_text(path)
    new_text, report = scale_text(text, options)
    data = codec.encode(new_text)
    if out_path is None:
        backup = Path(path).with_name(Path(path).name + ".bak")
        if not backup.exists():
            shutil.copy2(path, backup)  # 備份失敗丟例外 → 不寫入
        Path(path).write_bytes(data)
    else:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(data)
    return report
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_scale_engine.py -v`
Expected: 30 passed(22 + 8)

- [ ] **Step 5: 跑全套確認無回歸**

Run: `py -m pytest tests -v`
Expected: 157 passed(127 + 30)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/scale_engine.py tests/test_scale_engine.py
git commit -m "feat: add encoding/newline-preserving file I/O to scale engine"
```

---

### Task 4: GUI 整合 — ScalePanel、ScaleWorker、操作模式切換與試算預覽

**Files:**
- Create: `ass_style_tool/qt/scale_panel.py`
- Modify: `ass_style_tool/qt/batch_worker.py`(附加 ScaleWorker)
- Modify: `ass_style_tool/qt/subtitle_tab.py`(操作模式切換、掛面板、試算預覽、執行分流)
- Test: `tests/test_scale_gui.py`

**Interfaces:**
- Consumes: `scale_engine.ScaleOptions/ScaleError/scale_text/scale_file/read_subtitle_text`、既有 `SubtitleFileTab`/`BatchWorker` 結構
- Produces:
  - `ScalePanel(QWidget)`:欄位 `factor_radio/factor_edit/target_radio/target_edit/base_edit/deco_check/inline_check/fscxy_check`;method `get_options() -> ScaleOptions`(非法丟 `ScaleError`)
  - `ScaleWorker(QObject)`:signals 與 BatchWorker 相同(`progress/file_done/message/finished`);`run()/cancel()`;`finished(ok, 0, error)`
  - `SubtitleFileTab` 新增:`apply_mode_radio/scale_mode_radio`、`scale_panel`、`dry_run_button`;縮放模式時執行按鈕文字「開始縮放」,試算預覽僅縮放模式可用

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_scale_gui.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from ass_style_tool.batch_runner import ScanResult
from ass_style_tool.episode_match import MatchResult
from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values
from ass_style_tool.scale_engine import ScaleError


def test_scale_panel_factor_options(qapp):
    from ass_style_tool.qt.scale_panel import ScalePanel
    panel = ScalePanel()
    panel.factor_radio.setChecked(True)
    panel.factor_edit.setText("1.25")
    options = panel.get_options()
    assert options.factor == 1.25
    assert options.target_size is None
    assert options.scale_decorations is True
    assert options.scale_inline_fs is True
    assert options.scale_fscxy is False


def test_scale_panel_target_options(qapp):
    from ass_style_tool.qt.scale_panel import ScalePanel
    panel = ScalePanel()
    panel.target_radio.setChecked(True)
    panel.target_edit.setText("72")
    panel.base_edit.setText("  ")
    panel.fscxy_check.setChecked(True)
    options = panel.get_options()
    assert options.target_size == 72.0
    assert options.base_style == "Default"  # 空白 fallback
    assert options.scale_fscxy is True


def test_scale_panel_invalid_number_raises(qapp):
    from ass_style_tool.qt.scale_panel import ScalePanel
    panel = ScalePanel()
    panel.factor_radio.setChecked(True)
    panel.factor_edit.setText("abc")
    with pytest.raises(ScaleError):
        panel.get_options()


def test_mode_switch_toggles_scale_panel(qapp):
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    assert tab.apply_mode_radio.isChecked()
    assert tab.scale_panel.isHidden() is True     # 預設隱藏
    tab.scale_mode_radio.setChecked(True)
    assert tab.scale_panel.isHidden() is False
    assert tab.run_button.text() == "開始縮放"
    tab.apply_mode_radio.setChecked(True)
    assert tab.scale_panel.isHidden() is True
    assert tab.run_button.text() == "開始套用樣式"


def test_scale_worker_scales_files(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import ScaleWorker
    from ass_style_tool.scale_engine import ScaleOptions
    from tests.test_ass_style import SAMPLE_ASS
    sub = tmp_path / "a [01].ass"
    sub.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    scan = ScanResult(matches=[
        MatchResult(sub_path=sub, episode=1, status="no_video")],
        warnings=[])
    worker = ScaleWorker(scan, ScaleOptions(factor=2),
                         output_dir=tmp_path / "out")
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done == {"ok": 1, "skipped": 0, "error": 0}
    out_text = (tmp_path / "out" / "a [01].ass").read_text(encoding="utf-8-sig")
    assert "Style: Default,Arial,80," in out_text   # 40*2
    assert "Style: OP,Comic Sans MS,120," in out_text  # 60*2


def test_scale_worker_error_isolated(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import ScaleWorker
    from ass_style_tool.scale_engine import ScaleOptions
    bad = tmp_path / "bad [01].ass"
    bad.write_text("not a subtitle", encoding="utf-8")
    scan = ScanResult(matches=[
        MatchResult(sub_path=bad, episode=1, status="no_video")],
        warnings=[])
    worker = ScaleWorker(scan, ScaleOptions(factor=2),
                         output_dir=tmp_path / "out")
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done == {"ok": 0, "skipped": 0, "error": 1}
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_scale_gui.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.qt.scale_panel'`

- [ ] **Step 3: 實作 scale_panel.py**

建立 `ass_style_tool/qt/scale_panel.py`:

```python
"""縮放字級模式的參數面板。"""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QGridLayout, QLabel, QLineEdit,
                               QRadioButton, QWidget)

from ..scale_engine import ScaleError, ScaleOptions


class ScalePanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 4, 0, 4)

        self.factor_radio = QRadioButton("倍率 ×")
        self.factor_radio.setChecked(True)
        self.factor_edit = QLineEdit("1.25")
        self.factor_edit.setMaximumWidth(80)
        grid.addWidget(self.factor_radio, 0, 0)
        grid.addWidget(self.factor_edit, 0, 1)

        self.target_radio = QRadioButton("主 Style 設為")
        self.target_edit = QLineEdit("72")
        self.target_edit.setMaximumWidth(80)
        grid.addWidget(self.target_radio, 1, 0)
        grid.addWidget(self.target_edit, 1, 1)
        grid.addWidget(QLabel("基準 Style:"), 1, 2)
        self.base_edit = QLineEdit("Default")
        self.base_edit.setMaximumWidth(140)
        grid.addWidget(self.base_edit, 1, 3)

        self.deco_check = QCheckBox("同步縮放外框/陰影")
        self.deco_check.setChecked(True)
        self.inline_check = QCheckBox("縮放對白內 \\fs")
        self.inline_check.setChecked(True)
        self.fscxy_check = QCheckBox("同步縮放 \\fscx/\\fscy(會改變字幅比例)")
        grid.addWidget(self.deco_check, 2, 0, 1, 2)
        grid.addWidget(self.inline_check, 2, 2, 1, 2)
        grid.addWidget(self.fscxy_check, 3, 0, 1, 4)
        grid.setColumnStretch(4, 1)

    def get_options(self) -> ScaleOptions:
        try:
            if self.factor_radio.isChecked():
                options = ScaleOptions(factor=float(self.factor_edit.text()))
            else:
                options = ScaleOptions(
                    target_size=float(self.target_edit.text()),
                    base_style=self.base_edit.text().strip() or "Default")
        except ValueError as exc:
            if isinstance(exc, ScaleError):
                raise
            raise ScaleError(f"數值格式錯誤: {exc}")
        options.scale_decorations = self.deco_check.isChecked()
        options.scale_inline_fs = self.inline_check.isChecked()
        options.scale_fscxy = self.fscxy_check.isChecked()
        options.validate()
        return options
```

- [ ] **Step 4: 附加 ScaleWorker(batch_worker.py 末尾)**

在 `ass_style_tool/qt/batch_worker.py` 的 import 區加入:

```python
from ..scale_engine import ScaleOptions, scale_file
```

檔案末尾附加:

```python
class ScaleWorker(QObject):
    """縮放字級批次 worker;signals 形狀與 BatchWorker 相同(skipped 恆為 0)。"""

    progress = Signal(int, int)
    file_done = Signal(str, str)
    message = Signal(str)
    finished = Signal(int, int, int)

    def __init__(self, scan, options: ScaleOptions,
                 output_dir: Optional[Path]) -> None:
        super().__init__()
        self._matches = list(scan.matches)
        self._options = options
        self._output_dir = output_dir
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._matches)
        ok = error = 0
        for i, match in enumerate(self._matches, start=1):
            if self._cancelled:
                self.message.emit("已取消,停止後續檔案")
                break
            out = (self._output_dir / match.sub_path.name
                   if self._output_dir is not None else None)
            try:
                report = scale_file(match.sub_path, self._options, out)
            except Exception as exc:  # 單檔失敗不中斷整批
                error += 1
                self.file_done.emit(match.sub_path.name, "error")
                self.message.emit(f"    {exc}")
            else:
                ok += 1
                self.file_done.emit(match.sub_path.name, "ok")
                for change in report.style_changes:
                    self.message.emit(
                        f"    {change.name}: {change.old_size} → {change.new_size}")
                self.message.emit(
                    f"    inline \\fs 修改 {report.inline_fs_count} 處"
                    f"(倍率 {report.factor_used:.3f})")
            self.progress.emit(i, total)
        self.finished.emit(ok, 0, error)
```

- [ ] **Step 5: 修改 subtitle_tab.py 接入模式切換**

(a)import 區加入:

```python
from ..scale_engine import ScaleError, read_subtitle_text, scale_text
from .batch_worker import BatchWorker, ScaleWorker
from .scale_panel import ScalePanel
```

並移除原本單獨的 `from .batch_worker import BatchWorker`(避免重複)。

(b)在 `__init__` 中,`folder_row` 佈局之後、`self.table` 之前,插入操作模式列與面板:

```python
        # 操作模式:套用樣式(既有)/ 縮放字級(新)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("操作模式:"))
        self.apply_mode_radio = QRadioButton("套用樣式")
        self.apply_mode_radio.setChecked(True)
        self.scale_mode_radio = QRadioButton("縮放字級")
        mode_row.addWidget(self.apply_mode_radio)
        mode_row.addWidget(self.scale_mode_radio)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        self.scale_panel = ScalePanel()
        self.scale_panel.setHidden(True)
        root.addWidget(self.scale_panel)
        self.scale_mode_radio.toggled.connect(self._on_mode_changed)
```

(c)在 `action_row` 中 `run_button` 之後插入試算預覽按鈕:

```python
        self.dry_run_button = QPushButton("試算預覽(不寫檔)")
        self.dry_run_button.setEnabled(False)
        self.dry_run_button.clicked.connect(self._on_dry_run)
        action_row.addWidget(self.dry_run_button)
```

(d)新增方法(放在 `_on_run` 之前):

```python
    def _on_mode_changed(self, scale_mode: bool) -> None:
        self.scale_panel.setHidden(not scale_mode)
        self.run_button.setText("開始縮放" if scale_mode else "開始套用樣式")
        self._update_dry_run_enabled()

    def _update_dry_run_enabled(self) -> None:
        self.dry_run_button.setEnabled(
            self.scale_mode_radio.isChecked() and self._scan is not None
            and len(self._scan.matches) > 0)

    def _on_dry_run(self) -> None:
        if self._scan is None:
            return
        try:
            options = self.scale_panel.get_options()
        except ScaleError as exc:
            self.log.emit(f"參數錯誤: {exc}")
            return
        self.log.emit("=== 試算預覽(不寫檔)===")
        for match in self._scan.matches:
            try:
                text, _codec = read_subtitle_text(match.sub_path)
                _new, report = scale_text(text, options)
            except Exception as exc:  # noqa: BLE001
                self.log.emit(f"[error] {match.sub_path.name}: {exc}")
                continue
            self.log.emit(
                f"[試算] {match.sub_path.name}(倍率 {report.factor_used:.3f})")
            for change in report.style_changes:
                self.log.emit(
                    f"    {change.name}: {change.old_size} → {change.new_size}")
            self.log.emit(f"    inline \\fs 將修改 {report.inline_fs_count} 處")
```

(e)`populate_preview` 末尾 `return len(rows)` 之前加一行:

```python
        self._update_dry_run_enabled()
```

(f)`_on_run` 中,把建 worker 那兩行:

```python
        self._thread = QThread()
        self._worker = BatchWorker(self._scan, profile, self._output_dir())
```

替換為模式分流(profile 驗證僅套用模式需要,整段 `_on_run` 開頭的 try/except 也要跟著調整):

```python
    def _on_run(self) -> None:
        if self._scan is None:
            return
        if self.scale_mode_radio.isChecked():
            try:
                payload = self.scale_panel.get_options()
            except ScaleError as exc:
                self.log.emit(f"參數錯誤: {exc}")
                return
        else:
            try:
                payload = self._get_profile()
            except ValueError as exc:
                self.log.emit(f"欄位錯誤: {exc}")
                return
        if self.outdir_radio.isChecked() and self._output_dir() is None:
            self.log.emit("請先選擇輸出資料夾")
            return

        self.progress.setValue(0)
        self.scan_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.dry_run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        self._thread = QThread()
        if self.scale_mode_radio.isChecked():
            self._worker = ScaleWorker(self._scan, payload, self._output_dir())
        else:
            self._worker = BatchWorker(self._scan, payload, self._output_dir())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_done.connect(
            lambda name, status: self.log.emit(f"[{status}] {name}"))
        self._worker.message.connect(self.log.emit)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()
```

(g)`_on_finished` 末尾恢復按鈕的區塊加一行:

```python
        self._update_dry_run_enabled()
```

- [ ] **Step 6: 執行測試,確認通過**

Run: `py -m pytest tests/test_scale_gui.py -v`
Expected: 6 passed

- [ ] **Step 7: 跑全套 + import + 啟動冒煙**

Run: `py -m pytest tests -v`
Expected: 163 passed(157 + 6)

Run: `py -c "import ass_style_tool.qt.subtitle_tab; print('ok')"`
Expected: `ok`

```powershell
$p = Start-Process -FilePath "py" -ArgumentList "-m","ass_style_tool" -WorkingDirectory "C:\Claude_code" -PassThru
Start-Sleep -Seconds 3
if ($p.HasExited) { Write-Output "FAIL exit=$($p.ExitCode)" } else { Write-Output "OK"; Stop-Process -Id $p.Id }
```

Expected: `OK`

- [ ] **Step 8: 手動冒煙清單(由使用者執行,記於報告)**

Run: `py -m ass_style_tool`
1. 「字幕檔」分頁出現「操作模式:套用樣式/縮放字級」;預設套用樣式,行為與之前完全相同
2. 切「縮放字級」→ 縮放面板出現(倍率/目標二選一、基準 Style、三個勾選),執行按鈕變「開始縮放」
3. 掃描資料夾後,「試算預覽(不寫檔)」變可按 → log 列出每檔 Style 舊值→新值與 inline \fs 數,檔案未被修改
4. 「開始縮放」原地模式 → `.bak` 產生、字級等比變大;用 Aegisub 開啟確認其他欄位(字型/顏色/邊距)完全沒動
5. 輸出資料夾模式 → 原檔不動、新資料夾有結果
6. Big5 或 UTF-16 的舊字幕跑一次 → 輸出編碼不變、無亂碼

- [ ] **Step 9: Commit**

```powershell
git add ass_style_tool/qt/scale_panel.py ass_style_tool/qt/batch_worker.py ass_style_tool/qt/subtitle_tab.py tests/test_scale_gui.py
git commit -m "feat: add scale mode to subtitle tab with dry-run preview"
```
