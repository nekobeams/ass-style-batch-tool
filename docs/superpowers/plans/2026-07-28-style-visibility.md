# 樣式可見化與流程優化 Implementation Plan

**Goal:** 讓使用者在工具內直接看見這批字幕檔有哪些樣式名、預計會被改成什麼,不必再開 Subtitle Edit 查完再回來填。

**Architecture:** 新增一層純邏輯的樣式掃描模組(`style_scan.py`),由 `scan_folder()` 在既有的檔名配對與 ffprobe 之後多跑一輪解析,結果掛在 `ScanResult.styles`。GUI 端新增側欄的可勾選樣式清單元件(`style_picker.py`)取代樣式編輯器裡的自由文字欄位,並在主表格加一欄「預計 / 結果」。掃描本身補上進度回報與取消。

**Tech Stack:** Python 3.13、PySide6 6.11、pysubs2、pytest(offscreen Qt)

## Global Constraints

- **一律用 `py`,不要用 `python`**(本機 `python` 是壞掉的 WindowsApps stub,靜默 exit 49/9009)
- 測試指令一律 `py -m pytest tests -q`,從 repo root(專案根目錄)執行
- Qt 測試在 offscreen 下跑(`tests/conftest.py` 已設定),**絕不**真的呼叫 mkvextract / ffprobe / mpv,一律注入假物件
- 純邏輯模組不得 import PySide6
- 所有註解與使用者可見字串用繁體中文;commit 訊息用英文
- **核心不變式:掃描結果只能是資訊,不能替使用者做刪除決定。** profile/設定帶來但這批檔案裡不存在的樣式名,必須照常顯示、保持勾選、標記「未在檔案中找到」,絕不自動取消勾選
- 既有 466 測試必須持續通過

---

### Task 1: `style_scan.py` 純邏輯層

**Files:**
- Create: `ass_style_tool\style_scan.py`
- Test: `tests\test_style_scan.py`

**Interfaces:**
- Consumes: `ass_style.load_subs(path)`、`ass_style.get_play_res(subs)`(既有)
- Produces:
  - `FileStyles(path: Path, styles: Dict[str, float], play_res: Tuple[int,int], error: Optional[str])`
  - `scan_styles(path: Path) -> FileStyles`
  - `StyleSummary(names: List[str], inconsistent: List[Path], unreadable: List[Path])`
  - `summarize(results: Sequence[FileStyles]) -> StyleSummary`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests\test_style_scan.py`:

```python
from __future__ import annotations

from pathlib import Path

from ass_style_tool.style_scan import FileStyles, scan_styles, summarize

_HEADER = """[Script Info]
PlayResX: {w}
PlayResY: {h}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
"""

_STYLE = ("Style: {name},Arial,{size},&H00FFFFFF,&H000000FF,&H00000000,"
          "&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n")

_EVENTS = """
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,{style},,0,0,0,,測試字幕
"""


def write_ass(path: Path, styles, w=1920, h=1080, encoding="utf-8-sig") -> Path:
    """寫出一個真的能被 pysubs2 解析的 ASS 檔。styles 是 [(名稱, 字級)]。"""
    text = _HEADER.format(w=w, h=h)
    for name, size in styles:
        text += _STYLE.format(name=name, size=size)
    text += _EVENTS.format(style=styles[0][0])
    path.write_text(text, encoding=encoding)
    return path


def test_scan_styles_reads_names_and_sizes(tmp_path):
    p = write_ass(tmp_path / "a.ass", [("Default", 48), ("CHT", 52)])
    result = scan_styles(p)
    assert result.error is None
    assert result.styles == {"Default": 48.0, "CHT": 52.0}


def test_scan_styles_reads_play_res(tmp_path):
    p = write_ass(tmp_path / "a.ass", [("Default", 48)], w=1280, h=720)
    assert scan_styles(p).play_res == (1280, 720)


def test_scan_styles_handles_big5(tmp_path):
    p = write_ass(tmp_path / "big5.ass", [("Default", 40)], encoding="big5")
    result = scan_styles(p)
    assert result.error is None
    assert result.styles == {"Default": 40.0}


def test_scan_styles_reports_broken_file_without_raising(tmp_path):
    p = tmp_path / "broken.ass"
    p.write_bytes(b"\xff\xfe\x00\x00 not a subtitle at all \xff")
    result = scan_styles(p)
    assert result.error is not None
    assert result.styles == {}


def test_summarize_dedupes_and_sorts(tmp_path):
    a = FileStyles(tmp_path / "a.ass", {"Default": 48.0, "CHT": 52.0})
    b = FileStyles(tmp_path / "b.ass", {"Default": 48.0})
    summary = summarize([a, b])
    assert summary.names == ["CHT", "Default"]


def test_summarize_flags_the_odd_file_out(tmp_path):
    same1 = FileStyles(tmp_path / "1.ass", {"Default": 48.0})
    same2 = FileStyles(tmp_path / "2.ass", {"Default": 48.0})
    odd = FileStyles(tmp_path / "3.ass", {"CHS": 48.0})
    summary = summarize([same1, same2, odd])
    assert summary.inconsistent == [tmp_path / "3.ass"]


def test_summarize_collects_unreadable_separately(tmp_path):
    ok = FileStyles(tmp_path / "ok.ass", {"Default": 48.0})
    bad = FileStyles(tmp_path / "bad.ass", error="讀取失敗")
    summary = summarize([ok, bad])
    assert summary.unreadable == [tmp_path / "bad.ass"]
    assert summary.names == ["Default"]
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `py -m pytest tests/test_style_scan.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.style_scan'`

- [ ] **Step 3: 寫實作**

建立 `ass_style_tool\style_scan.py`:

```python
"""字幕檔樣式的掃描與彙整(純邏輯,不依賴 Qt)。

掃描階段只需要知道「這個檔案有哪些樣式、各自多大、PlayRes 多少」,
不必把整份事件行搬進 GUI。獨立成一層是為了能直接拿真實 .ass 檔測,
不必啟動 Qt。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .ass_style import get_play_res, load_subs


@dataclass
class FileStyles:
    """單一字幕檔的樣式掃描結果。

    error 不為 None 時 styles/play_res 無意義——讀檔或解析失敗了,但掃描
    不會因此中斷(與 batch_runner 單檔失敗不中斷整批的作法一致)。
    """
    path: Path
    styles: Dict[str, float] = field(default_factory=dict)
    play_res: Tuple[int, int] = (0, 0)
    error: Optional[str] = None


def scan_styles(path: Path) -> FileStyles:
    try:
        subs = load_subs(path)
    except Exception as exc:      # 壞檔不可讓整批掃描中斷
        return FileStyles(path=path, error=str(exc))
    styles = {name: float(style.fontsize)
              for name, style in subs.styles.items()}
    return FileStyles(path=path, styles=styles, play_res=get_play_res(subs))


@dataclass
class StyleSummary:
    names: List[str] = field(default_factory=list)
    inconsistent: List[Path] = field(default_factory=list)
    unreadable: List[Path] = field(default_factory=list)


def summarize(results: Sequence[FileStyles]) -> StyleSummary:
    """彙整整批掃描結果。

    inconsistent 只在各檔的樣式名集合不完全相同時才有內容——使用者的
    情境是全季一致,所以這是例外通報,不是常態顯示。
    """
    summary = StyleSummary()
    readable: List[FileStyles] = []
    for result in results:
        if result.error is not None:
            summary.unreadable.append(result.path)
        else:
            readable.append(result)

    all_names: set = set()
    for result in readable:
        all_names |= set(result.styles)
    summary.names = sorted(all_names)

    if not readable:
        return summary
    # 以「出現最廣的樣式名組合」當基準,其餘視為例外
    signatures = Counter(frozenset(r.styles) for r in readable)
    majority = signatures.most_common(1)[0][0]
    summary.inconsistent = [r.path for r in readable
                            if frozenset(r.styles) != majority]
    return summary
```

- [ ] **Step 4: 執行測試確認通過**

Run: `py -m pytest tests/test_style_scan.py -q`
Expected: PASS(7 passed)

- [ ] **Step 5: 執行全套測試**

Run: `py -m pytest tests -q`
Expected: PASS(473 passed)

- [ ] **Step 6: Commit**

```bash
git add ass_style_tool/style_scan.py tests/test_style_scan.py
git commit -m "feat: add pure-logic subtitle style scanning layer"
```

---

### Task 2: `scan_folder()` 帶入樣式掃描、進度與取消

**Files:**
- Modify: `ass_style_tool\batch_runner.py`(`ScanResult` 與 `scan_folder`)
- Test: `tests\test_batch_runner.py`(既有檔案,附加測試)

**Interfaces:**
- Consumes: `style_scan.scan_styles`、`style_scan.FileStyles`(Task 1)
- Produces:
  - `ScanResult.styles: Dict[Path, FileStyles]`
  - `ScanResult.cancelled: bool`
  - `scan_folder(folder, *, progress=None, should_cancel=None) -> ScanResult`

- [ ] **Step 1: 寫失敗的測試**

附加到 `tests\test_batch_runner.py` 末尾。若檔案內尚未 import `write_ass`,在檔案頂端加入 `from tests.test_style_scan import write_ass`(pytest 以 repo root 為 rootdir,可直接 import)。

```python
# ---------- 掃描帶入樣式資訊 / 進度 / 取消 ----------

def test_scan_folder_collects_styles_per_file(tmp_path, monkeypatch):
    from tests.test_style_scan import write_ass
    monkeypatch.setattr("ass_style_tool.batch_runner.ffprobe_available",
                        lambda: False)
    write_ass(tmp_path / "show [01].ass", [("Default", 48)])
    write_ass(tmp_path / "show [02].ass", [("Default", 48), ("CHT", 52)])
    scan = scan_folder(tmp_path)
    assert set(scan.styles[tmp_path / "show [01].ass"].styles) == {"Default"}
    assert set(scan.styles[tmp_path / "show [02].ass"].styles) == {"Default",
                                                                  "CHT"}


def test_scan_folder_reports_progress(tmp_path, monkeypatch):
    from tests.test_style_scan import write_ass
    monkeypatch.setattr("ass_style_tool.batch_runner.ffprobe_available",
                        lambda: False)
    for i in (1, 2, 3):
        write_ass(tmp_path / f"show [{i:02d}].ass", [("Default", 48)])
    seen = []
    scan_folder(tmp_path, progress=lambda done, total: seen.append((done,
                                                                    total)))
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_scan_folder_stops_when_cancelled(tmp_path, monkeypatch):
    from tests.test_style_scan import write_ass
    monkeypatch.setattr("ass_style_tool.batch_runner.ffprobe_available",
                        lambda: False)
    for i in (1, 2, 3, 4):
        write_ass(tmp_path / f"show [{i:02d}].ass", [("Default", 48)])
    calls = {"n": 0}

    def should_cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 2      # 前兩個檔案照跑,之後取消

    scan = scan_folder(tmp_path, should_cancel=should_cancel)
    assert scan.cancelled is True
    assert len(scan.styles) == 2   # 取消後剩下的檔案沒有被解析
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `py -m pytest tests/test_batch_runner.py -q -k "styles or progress or cancelled"`
Expected: FAIL — `AttributeError: 'ScanResult' object has no attribute 'styles'`

- [ ] **Step 3: 寫實作**

在 `batch_runner.py` 的 import 區加入:

```python
from .style_scan import FileStyles, scan_styles
```

並把 `Dict` 加進 typing import(該行改為 `from typing import Callable, Dict, List, Optional`)。

把 `ScanResult` 改成:

```python
@dataclass
class ScanResult:
    matches: List[MatchResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    styles: Dict[Path, FileStyles] = field(default_factory=dict)
    cancelled: bool = False
```

把整個 `scan_folder` 換成:

```python
def scan_folder(
    folder: Path,
    *,
    progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> ScanResult:
    """掃描資料夾:檔名配對 → 影片解析度 → 字幕樣式。

    樣式解析不需要 ffprobe,所以即使找不到 ffprobe 也要繼續跑完
    (舊版在這裡直接 return,會讓沒裝 ffprobe 的使用者完全看不到樣式)。
    """
    subs, videos = find_files(folder)
    scan = ScanResult(matches=match_pairs(subs, videos))
    if not subs:
        scan.warnings.append("資料夾內找不到任何 .ass/.ssa/.srt 字幕檔")
    have_ffprobe = ffprobe_available()
    if not have_ffprobe:
        scan.warnings.append("找不到 ffprobe:預覽將不含影片解析度資訊與長寬比警告")

    total = len(scan.matches)
    for index, match in enumerate(scan.matches):
        if should_cancel is not None and should_cancel():
            scan.cancelled = True
            break
        if have_ffprobe and match.video_path is not None:
            match.video_resolution = probe_video_resolution(match.video_path)
        scan.styles[match.sub_path] = scan_styles(match.sub_path)
        if progress is not None:
            progress(index + 1, total)
    return scan
```

- [ ] **Step 4: 執行測試確認通過**

Run: `py -m pytest tests/test_batch_runner.py -q`
Expected: PASS

- [ ] **Step 5: mutation 驗證取消真的有效**

暫時把實作裡的 `if should_cancel is not None and should_cancel():` 那兩行連同 `break` 註解掉,然後執行:

Run: `py -m pytest tests/test_batch_runner.py -q -k cancelled`
Expected: **FAIL**(`assert scan.cancelled is True` 失敗,且 `len(scan.styles) == 4`)

確認變紅後把註解解除,再跑一次確認變綠:

Run: `py -m pytest tests/test_batch_runner.py -q -k cancelled`
Expected: PASS

- [ ] **Step 6: 執行全套測試**

Run: `py -m pytest tests -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add ass_style_tool/batch_runner.py tests/test_batch_runner.py
git commit -m "feat: collect per-file styles during scan, add progress and cancel"
```

---

### Task 3: `ScanWorker` 支援進度與取消

**Files:**
- Modify: `ass_style_tool\qt\batch_worker.py`(`ScanWorker`,約第 18-27 行)
- Test: `tests\test_batch_worker.py`(既有檔案,附加測試)

**Interfaces:**
- Consumes: `batch_runner.scan_folder(folder, progress=..., should_cancel=...)`(Task 2)
- Produces: `ScanWorker.progress = Signal(int, int)`、`ScanWorker.cancel()`

- [ ] **Step 1: 寫失敗的測試**

附加到 `tests\test_batch_worker.py` 末尾:

```python
# ---------- ScanWorker 進度與取消 ----------

def test_scan_worker_forwards_progress_and_cancel(monkeypatch, tmp_path):
    from ass_style_tool.qt.batch_worker import ScanWorker

    captured = {}

    def fake_scan_folder(folder, *, progress=None, should_cancel=None):
        captured["folder"] = folder
        progress(1, 2)
        captured["cancelled_before"] = should_cancel()
        return "SCAN"

    monkeypatch.setattr("ass_style_tool.batch_runner.scan_folder",
                        fake_scan_folder)
    worker = ScanWorker(tmp_path)
    seen_progress = []
    worker.progress.connect(lambda d, t: seen_progress.append((d, t)))
    results = []
    worker.finished.connect(results.append)

    worker.cancel()          # 開跑前就取消,should_cancel 必須回報 True
    worker.run()

    assert captured["folder"] == tmp_path
    assert captured["cancelled_before"] is True
    assert seen_progress == [(1, 2)]
    assert results == ["SCAN"]
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `py -m pytest tests/test_batch_worker.py -q -k scan_worker_forwards`
Expected: FAIL — `AttributeError: 'ScanWorker' object has no attribute 'progress'`

- [ ] **Step 3: 寫實作**

把 `batch_worker.py` 裡整個 `ScanWorker` 類別換成:

```python
class ScanWorker(QObject):
    progress = Signal(int, int)        # 已完成, 總數
    finished = Signal(object)          # 攜帶 ScanResult

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self._folder = folder
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        from ..batch_runner import scan_folder
        self.finished.emit(scan_folder(
            self._folder,
            progress=lambda done, total: self.progress.emit(done, total),
            should_cancel=lambda: self._cancelled,
        ))
```

- [ ] **Step 4: 執行測試確認通過**

Run: `py -m pytest tests/test_batch_worker.py -q`
Expected: PASS

- [ ] **Step 5: 執行全套測試**

Run: `py -m pytest tests -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ass_style_tool/qt/batch_worker.py tests/test_batch_worker.py
git commit -m "feat: forward scan progress and cancellation through ScanWorker"
```

---

### Task 4: 「預計」欄文字的純函式

**Files:**
- Modify: `ass_style_tool\qt\gui_helpers.py`(`PreviewRow` 與 `preview_rows`)
- Test: `tests\test_gui_helpers.py`(既有檔案,附加測試)

**Interfaces:**
- Consumes: `style_scan.FileStyles`(Task 1)、`ass_style.compute_applied_values`、`scale_engine.fmt_num`、`scale_engine.ScaleOptions`(皆為既有)
- Produces:
  - `apply_plan_text(file_styles, profile, target_names) -> str`
  - `scale_plan_text(file_styles, options) -> str`
  - `PreviewRow.plan: str`
  - `preview_rows(scan, plans: Optional[Dict[Path, str]] = None) -> List[PreviewRow]`

- [ ] **Step 1: 寫失敗的測試**

附加到 `tests\test_gui_helpers.py` 末尾:

```python
# ---------- 「預計」欄文字 ----------

from pathlib import Path

from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values
from ass_style_tool.qt.gui_helpers import apply_plan_text, scale_plan_text
from ass_style_tool.scale_engine import ScaleOptions
from ass_style_tool.style_scan import FileStyles


def _profile(**overrides):
    values = dict(DEFAULT_VALUES)
    values.update(overrides)
    return profile_from_values(values)


def test_apply_plan_text_shows_old_and_new_size():
    fs = FileStyles(Path("a.ass"), {"Default": 48.0}, (1920, 1080))
    # base 1920x1080、fontsize 72 → 縮放係數 1.0,預計 48 → 72
    text = apply_plan_text(fs, _profile(fontsize="72"), ["Default"])
    assert text == "Default 48 → 72"


def test_apply_plan_text_scales_by_play_res():
    fs = FileStyles(Path("a.ass"), {"Default": 24.0}, (960, 540))
    # 960x540 相對於基準 1920x1080 是 0.5 倍 → 72 * 0.5 = 36
    text = apply_plan_text(fs, _profile(fontsize="72"), ["Default"])
    assert text == "Default 24 → 36"


def test_apply_plan_text_marks_missing_style():
    fs = FileStyles(Path("a.ass"), {"CHS": 48.0}, (1920, 1080))
    text = apply_plan_text(fs, _profile(), ["Default"])
    assert "找不到" in text and "Default" in text


def test_apply_plan_text_marks_unreadable_file():
    fs = FileStyles(Path("a.ass"), error="讀取失敗")
    assert apply_plan_text(fs, _profile(), ["Default"]) == "⚠ 無法讀取"


def test_apply_plan_text_with_no_selection():
    fs = FileStyles(Path("a.ass"), {"Default": 48.0}, (1920, 1080))
    assert apply_plan_text(fs, _profile(), []) == "⊘ 未選樣式"


def test_scale_plan_text_uses_factor():
    fs = FileStyles(Path("a.ass"), {"Default": 40.0}, (1920, 1080))
    text = scale_plan_text(fs, ScaleOptions(factor=1.5, base_style="Default"))
    assert text == "Default 40 → 60(×1.5)"


def test_scale_plan_text_derives_factor_from_target_size():
    fs = FileStyles(Path("a.ass"), {"Default": 40.0}, (1920, 1080))
    text = scale_plan_text(fs,
                           ScaleOptions(target_size=60, base_style="Default"))
    assert text == "Default 40 → 60(×1.5)"


def test_scale_plan_text_marks_missing_base_style():
    fs = FileStyles(Path("a.ass"), {"CHS": 40.0}, (1920, 1080))
    text = scale_plan_text(fs, ScaleOptions(factor=1.5, base_style="Default"))
    assert "找不到基準樣式" in text


def test_preview_rows_carries_plan_text():
    from ass_style_tool.batch_runner import ScanResult
    from ass_style_tool.episode_match import MatchResult
    from ass_style_tool.qt.gui_helpers import preview_rows
    scan = ScanResult(matches=[MatchResult(Path("a.ass"), 1, status="no_video")])
    rows = preview_rows(scan, {Path("a.ass"): "Default 48 → 72"})
    assert rows[0].plan == "Default 48 → 72"


def test_preview_rows_plan_defaults_to_blank():
    from ass_style_tool.batch_runner import ScanResult
    from ass_style_tool.episode_match import MatchResult
    from ass_style_tool.qt.gui_helpers import preview_rows
    scan = ScanResult(matches=[MatchResult(Path("a.ass"), 1, status="no_video")])
    assert preview_rows(scan)[0].plan == ""
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `py -m pytest tests/test_gui_helpers.py -q`
Expected: FAIL — `ImportError: cannot import name 'apply_plan_text'`

- [ ] **Step 3: 寫實作**

在 `gui_helpers.py` 頂端把 import 區改成(保留既有的 `from dataclasses import dataclass` 等):

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..ass_style import compute_applied_values
from ..profile import Profile
from ..scale_engine import ScaleOptions, fmt_num
from ..style_scan import FileStyles
```

把 `PreviewRow` 加一個欄位:

```python
@dataclass
class PreviewRow:
    episode: str
    sub_name: str
    video_name: str
    status_label: str
    plan: str = ""
```

把 `preview_rows` 換成:

```python
def preview_rows(scan,
                 plans: Optional[Dict[Path, str]] = None) -> List[PreviewRow]:
    plans = plans or {}
    rows: List[PreviewRow] = []
    for m in scan.matches:
        episode = f"{m.episode:02d}" if m.episode is not None else "?"
        video = m.video_path.name if m.video_path is not None else "-"
        rows.append(PreviewRow(
            episode=episode,
            sub_name=m.sub_path.name,
            video_name=video,
            status_label=STATUS_LABELS.get(m.status, m.status),
            plan=plans.get(m.sub_path, ""),
        ))
    return rows
```

在檔案末尾加入兩個純函式:

```python
def apply_plan_text(file_styles: Optional[FileStyles], profile: Profile,
                    target_names: Sequence[str]) -> str:
    """「預計」欄文字:目標樣式在這個檔案會從幾號變成幾號。

    字級之外的欄位(外框/陰影/邊距)也會被改,但表格一欄塞不下,
    字級是最能一眼看出縮放對不對的代表值。
    """
    if file_styles is None:
        return ""
    if file_styles.error is not None:
        return "⚠ 無法讀取"
    if not target_names:
        return "⊘ 未選樣式"
    applied = compute_applied_values(profile, *file_styles.play_res)
    parts = [
        f"{name} {fmt_num(file_styles.styles[name])} "
        f"→ {fmt_num(applied.fontsize)}"
        for name in target_names if name in file_styles.styles
    ]
    if not parts:
        return f"⊘ 找不到 {'、'.join(target_names)}"
    return "、".join(parts)


def scale_plan_text(file_styles: Optional[FileStyles],
                    options: ScaleOptions) -> str:
    """縮放模式的「預計」欄文字。"""
    if file_styles is None:
        return ""
    if file_styles.error is not None:
        return "⚠ 無法讀取"
    base = file_styles.styles.get(options.base_style)
    if base is None:
        return f"⊘ 找不到基準樣式 {options.base_style}"
    if options.factor is not None:
        factor = options.factor
    elif options.target_size is not None and base:
        factor = options.target_size / base
    else:
        return ""
    return (f"{options.base_style} {fmt_num(base)} "
            f"→ {fmt_num(base * factor)}(×{fmt_num(factor)})")
```

- [ ] **Step 4: 執行測試確認通過**

Run: `py -m pytest tests/test_gui_helpers.py -q`
Expected: PASS

- [ ] **Step 5: 執行全套測試**

Run: `py -m pytest tests -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ass_style_tool/qt/gui_helpers.py tests/test_gui_helpers.py
git commit -m "feat: add planned-change column text for apply and scale modes"
```

---

### Task 5: `StylePicker` 側欄元件(含核心不變式)

**Files:**
- Create: `ass_style_tool\qt\style_picker.py`
- Test: `tests\test_style_picker.py`

**Interfaces:**
- Consumes: 無(純 Qt 元件)
- Produces:
  - `StylePicker.set_available(names: Sequence[str]) -> None`
  - `StylePicker.set_selected(names: Sequence[str]) -> None`
  - `StylePicker.selected() -> List[str]`
  - `StylePicker.changed = Signal()`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests\test_style_picker.py`:

```python
from __future__ import annotations

from ass_style_tool.qt.style_picker import StylePicker


def test_available_names_are_listed(qapp):
    picker = StylePicker()
    picker.set_available(["CHT", "Default"])
    assert picker.list.count() == 2


def test_selected_names_start_checked(qapp):
    picker = StylePicker()
    picker.set_available(["Default", "CHT"])
    picker.set_selected(["Default"])
    assert picker.selected() == ["Default"]


def test_checking_an_item_updates_selection(qapp):
    from PySide6.QtCore import Qt
    picker = StylePicker()
    picker.set_available(["Default", "CHT"])
    picker.set_selected([])
    picker.list.item(0).setCheckState(Qt.CheckState.Checked)
    assert picker.selected() == ["Default"]


def test_changed_signal_fires_on_check(qapp):
    from PySide6.QtCore import Qt
    picker = StylePicker()
    picker.set_available(["Default"])
    fired = []
    picker.changed.connect(lambda: fired.append(1))
    picker.list.item(0).setCheckState(Qt.CheckState.Checked)
    assert fired == [1]


# ---------- 核心不變式 ----------

def test_selected_name_missing_from_scan_is_kept_and_flagged(qapp):
    """掃描結果不得替使用者刪掉已選的樣式名。

    先前「修改既有軌道」對話框正是靜默丟掉使用者設定而釀成 Critical,
    這條是本功能最重要的不變式。
    """
    picker = StylePicker()
    picker.set_selected(["CHT"])
    picker.set_available(["Default"])          # 掃描結果裡沒有 CHT
    assert "CHT" in picker.selected()          # 仍然被選著
    assert picker.list.count() == 2            # 仍然列出來
    labels = [picker.list.item(i).text() for i in range(picker.list.count())]
    assert any("CHT" in text and "未在檔案中找到" in text for text in labels)


def test_rescanning_does_not_drop_user_selection(qapp):
    picker = StylePicker()
    picker.set_available(["Default", "CHT"])
    picker.set_selected(["Default", "CHT"])
    picker.set_available(["Default"])          # 換了一批檔案,只剩 Default
    assert picker.selected() == ["Default", "CHT"]
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `py -m pytest tests/test_style_picker.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.qt.style_picker'`

- [ ] **Step 3: 寫實作**

建立 `ass_style_tool\qt\style_picker.py`:

```python
"""側欄的目標樣式勾選清單。

掃描結果是資訊來源,不是刪除依據:設定或 profile 帶來、但這批檔案裡
不存在的樣式名,仍然列出、仍然保持勾選,只多標一個「未在檔案中找到」。
先前「修改既有軌道」對話框就是靜默丟掉使用者設定,結果用假的保證
重現了它本來要防的災難——那個教訓在這裡直接適用。
"""
from __future__ import annotations

from typing import List, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QLabel, QListWidget, QListWidgetItem,
                               QVBoxLayout, QWidget)

_NOT_FOUND = "(未在檔案中找到)"


class StylePicker(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._available: List[str] = []
        self._selected: List[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setMaximumHeight(140)
        self.list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.list)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self._rebuild()

    # ---------- 對外 ----------
    def set_available(self, names: Sequence[str]) -> None:
        self._available = list(names)
        self._rebuild()

    def set_selected(self, names: Sequence[str]) -> None:
        self._selected = list(names)
        self._rebuild()

    def selected(self) -> List[str]:
        return list(self._selected)

    # ---------- 內部 ----------
    def _rebuild(self) -> None:
        # 聯集,順序:掃描到的在前,使用者選了但沒掃到的接在後面
        names = list(self._available)
        for name in self._selected:
            if name not in names:
                names.append(name)

        self.list.blockSignals(True)
        self.list.clear()
        for name in names:
            found = name in self._available
            item = QListWidgetItem(name if found else f"{name} {_NOT_FOUND}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in self._selected
                               else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._update_hint()

    def _on_item_changed(self, _item: QListWidgetItem) -> None:
        self._selected = [
            self.list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list.count())
            if self.list.item(i).checkState() == Qt.CheckState.Checked
        ]
        self._update_hint()
        self.changed.emit()

    def _update_hint(self) -> None:
        if not self._available:
            self.hint.setText("尚未掃描到樣式")
            return
        missing = [n for n in self._selected if n not in self._available]
        self.hint.setText(
            f"⚠ {'、'.join(missing)} 不在這批檔案中,這些檔案會被略過"
            if missing else "")
```

- [ ] **Step 4: 執行測試確認通過**

Run: `py -m pytest tests/test_style_picker.py -q`
Expected: PASS(6 passed)

- [ ] **Step 5: mutation 驗證核心不變式**

暫時把 `_rebuild` 裡的聯集три行改成只用掃描結果:

```python
        names = list(self._available)   # ← 暫時刪掉底下的 for 迴圈
```

Run: `py -m pytest tests/test_style_picker.py -q -k "missing_from_scan or does_not_drop"`
Expected: **FAIL**(兩個測試都紅:`CHT` 不在 `selected()` 裡、清單只有 1 列)

確認變紅後把 for 迴圈改回來,再跑一次:

Run: `py -m pytest tests/test_style_picker.py -q`
Expected: PASS

- [ ] **Step 6: 執行全套測試**

Run: `py -m pytest tests -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add ass_style_tool/qt/style_picker.py tests/test_style_picker.py
git commit -m "feat: add StylePicker sidebar widget that never drops user selections"
```

---

### Task 6: 字幕檔分頁整合(側欄清單、預計欄、自動掃描)

**Files:**
- Modify: `ass_style_tool\qt\subtitle_tab.py`
- Test: `tests\test_subtitle_tab.py`(既有檔案,附加測試)

**Interfaces:**
- Consumes: `StylePicker`(Task 5)、`apply_plan_text` / `scale_plan_text` / `preview_rows`(Task 4)、`ScanResult.styles`(Task 2)
- Produces:
  - `SubtitleTab.style_picker: StylePicker`
  - `SubtitleTab.auto_scan_once() -> None`(主視窗切分頁時呼叫,每個分頁只掃一次)
  - `SubtitleTab.effective_profile() -> Profile`(把勾選的樣式名蓋進 profile)

- [ ] **Step 1: 寫失敗的測試**

附加到 `tests\test_subtitle_tab.py` 末尾:

```python
# ---------- 目標樣式清單與預計欄 ----------

def test_scan_fills_style_picker(qapp, tmp_path):
    from pathlib import Path
    from ass_style_tool.batch_runner import ScanResult
    from ass_style_tool.episode_match import MatchResult
    from ass_style_tool.style_scan import FileStyles
    tab = _tab()
    scan = ScanResult(
        matches=[MatchResult(Path("a.ass"), 1, status="no_video")],
        styles={Path("a.ass"): FileStyles(Path("a.ass"),
                                          {"Default": 48.0, "CHT": 52.0},
                                          (1920, 1080))})
    from PySide6.QtCore import Qt
    tab._on_scan_finished(scan)
    names = [tab.style_picker.list.item(i).data(Qt.ItemDataRole.UserRole)
             for i in range(tab.style_picker.list.count())]
    assert sorted(names) == ["CHT", "Default"]


def test_plan_column_shows_predicted_size(qapp):
    from pathlib import Path
    from ass_style_tool.batch_runner import ScanResult
    from ass_style_tool.episode_match import MatchResult
    from ass_style_tool.style_scan import FileStyles
    tab = _tab()
    scan = ScanResult(
        matches=[MatchResult(Path("a.ass"), 1, status="no_video")],
        styles={Path("a.ass"): FileStyles(Path("a.ass"), {"Default": 48.0},
                                          (1920, 1080))})
    tab._on_scan_finished(scan)
    tab.style_picker.set_selected(["Default"])
    text = tab.table.item(0, 4).text()
    assert "Default 48 →" in text


def test_effective_profile_uses_picker_selection(qapp):
    tab = _tab()
    tab.style_picker.set_available(["CHT"])
    tab.style_picker.set_selected(["CHT"])
    assert tab.effective_profile().target_style_names == ["CHT"]


def test_run_button_disabled_when_nothing_selected(qapp):
    from pathlib import Path
    from ass_style_tool.batch_runner import ScanResult
    from ass_style_tool.episode_match import MatchResult
    from ass_style_tool.style_scan import FileStyles
    tab = _tab()
    scan = ScanResult(
        matches=[MatchResult(Path("a.ass"), 1, status="no_video")],
        styles={Path("a.ass"): FileStyles(Path("a.ass"), {"Default": 48.0},
                                          (1920, 1080))})
    tab._on_scan_finished(scan)
    tab.style_picker.set_selected([])
    assert tab.run_button.isEnabled() is False
    tab.style_picker.set_selected(["Default"])
    assert tab.run_button.isEnabled() is True


# ---------- auto_scan_once ----------

def test_auto_scan_once_scans_then_stops(qapp, monkeypatch, tmp_path):
    tab = _tab()
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab.folder_edit.setText(str(tmp_path))
    tab.auto_scan_once()
    tab.auto_scan_once()
    assert calls == [1]


def test_auto_scan_once_skips_missing_folder(qapp, monkeypatch, tmp_path):
    tab = _tab()
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab.folder_edit.setText(str(tmp_path / "不存在"))
    tab.auto_scan_once()
    assert calls == []
```

若既有測試檔沒有 `_tab()` 輔助函式,在檔案頂端加入:

```python
def _tab():
    from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values
    from ass_style_tool.qt.subtitle_tab import SubtitleTab
    return SubtitleTab(lambda: profile_from_values(DEFAULT_VALUES))
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `py -m pytest tests/test_subtitle_tab.py -q -k "style_picker or plan_column or effective_profile or auto_scan_once or nothing_selected"`
Expected: FAIL — `AttributeError: 'SubtitleTab' object has no attribute 'style_picker'`

- [ ] **Step 3: 寫實作**

在 `subtitle_tab.py` import 區加入:

```python
from dataclasses import replace

from .gui_helpers import apply_plan_text, preview_rows, scale_plan_text
from .style_picker import StylePicker
from ..style_scan import summarize
```

(既有若已 import `preview_rows` 則合併,不要重複 import。)

把 `_HEADERS` 改成:

```python
_HEADERS = ["集數", "字幕檔", "影片檔", "狀態", "預計 / 結果"]
```

在 `__init__` 的 `self._scanned_folder = None` 之後加一行:

```python
        self._auto_scanned = False
```

在建立 `self.splitter` 之前(輸出群組 `out_box` 之後)加入樣式清單:

```python
        # ----- 設定側欄:目標樣式 -----
        # group() 的第二參數收的是 QLayout(它會對其呼叫 setContentsMargins /
        # setSpacing),所以 picker 要先包一層 layout,不可直接傳 widget。
        self.style_picker = StylePicker()
        self.style_picker.changed.connect(self._on_styles_changed)
        style_box = QVBoxLayout()
        style_box.addWidget(self.style_picker)
```

把 `self.splitter = main_splitter(...)` 那一段改成:

```python
        self.splitter = main_splitter(
            self.table,
            settings_sidebar(group("操作模式", mode_box),
                             group("目標樣式", style_box),
                             group("輸出", out_box)))
```

把 `populate_preview` 換成:

```python
    def populate_preview(self, scan) -> int:
        rows = preview_rows(scan, self._plans())
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(
                    (row.episode, row.sub_name, row.video_name,
                     row.status_label, row.plan)):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self._update_run_enabled()
        self._update_dry_run_enabled()
        return len(rows)
```

在其後加入這些方法:

```python
    def _plans(self) -> dict:
        """每個字幕檔的「預計」欄文字。掃描結果尚未有樣式資訊時回傳空的。"""
        if self._scan is None:
            return {}
        styles = getattr(self._scan, "styles", {})
        if self.scale_mode_radio.isChecked():
            options = self.scale_panel.options()
            return {path: scale_plan_text(fs, options)
                    for path, fs in styles.items()}
        profile = self.effective_profile()
        names = self.style_picker.selected()
        return {path: apply_plan_text(fs, profile, names)
                for path, fs in styles.items()}

    def effective_profile(self) -> Profile:
        """把側欄勾選的樣式名蓋進目前的 profile。

        profile 描述「改成什麼樣子」,勾選描述「這批要改哪個」,兩者
        分開存放(勾選存 QSettings),執行時才合起來。
        """
        return replace(self._get_profile(),
                       target_style_names=self.style_picker.selected())

    def _on_styles_changed(self) -> None:
        if self._scan is not None:
            self.populate_preview(self._scan)

    def _update_run_enabled(self) -> None:
        has_rows = self.table.rowCount() > 0
        has_styles = bool(self.style_picker.selected())
        busy = self._thread is not None
        self.run_button.setEnabled(has_rows and has_styles and not busy)

    def auto_scan_once(self) -> None:
        """分頁第一次被顯示時自動掃描一次(主視窗切分頁時呼叫)。"""
        if self._auto_scanned:
            return
        folder = self.folder_edit.text().strip()
        if not folder or not Path(folder).is_dir():
            return
        if self._thread is not None or self._scan_thread is not None:
            return
        self._auto_scanned = True
        self._on_scan()
```

在 `_on_scan_finished` 裡,`self._scan = scan` 之後、`populate_preview` 之前插入:

```python
        summary = summarize(list(getattr(scan, "styles", {}).values()))
        self.style_picker.set_available(summary.names)
        if summary.inconsistent:
            self.log.emit(
                f"注意:有 {len(summary.inconsistent)} 個檔案的樣式組合與其他檔不同")
        for path in summary.unreadable:
            self.log.emit(f"警告:無法解析樣式 {path.name}")
```

把 `_on_run` 裡取用 profile 的地方從 `self._get_profile()` 改成 `self.effective_profile()`。

在 `save_settings` / `restore_settings` 加入勾選的存取(接在既有的 folder/outdir 之後):

```python
        settings.setValue("subtitle/styles", self.style_picker.selected())
```

```python
        saved_styles = settings.value("subtitle/styles", [])
        if isinstance(saved_styles, str):     # QSettings 單元素清單會退化成字串
            saved_styles = [saved_styles]
        self.style_picker.set_selected(list(saved_styles or []))
```

- [ ] **Step 4: 執行測試確認通過**

Run: `py -m pytest tests/test_subtitle_tab.py -q`
Expected: PASS

- [ ] **Step 5: 執行全套測試**

Run: `py -m pytest tests -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ass_style_tool/qt/subtitle_tab.py ass_style_tool/qt/layout_helpers.py tests/test_subtitle_tab.py
git commit -m "feat: wire style picker, plan column and lazy auto-scan into subtitle tab"
```

---

### Task 7: 主視窗切分頁觸發掃描、樣式編輯器移除目標欄位

**Files:**
- Modify: `ass_style_tool\qt\main_window.py`
- Modify: `ass_style_tool\qt\style_editor.py`
- Test: `tests\test_main_window.py`、`tests\test_style_editor.py`(既有檔案,附加測試)

**Interfaces:**
- Consumes: `SubtitleTab.auto_scan_once()`(Task 6)
- Produces: `MainWindow._on_tab_changed(index: int)`;`StyleEditor` 不再有 `target_style_names` 的輸入框,但 `values()` 仍供應該鍵

- [ ] **Step 1: 寫失敗的測試**

附加到 `tests\test_style_editor.py` 末尾:

```python
# ---------- 目標 Style 欄位已移出樣式編輯器 ----------

def test_editor_has_no_target_style_widget(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    assert "target_style_names" not in editor._edits


def test_get_values_still_supplies_target_style_names(qapp):
    """profile_from_values 仍要求這個鍵,移除輸入框不能連鍵一起拿掉。"""
    from ass_style_tool.profile_fields import profile_from_values
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    values = editor.get_values()
    assert values["target_style_names"]
    assert profile_from_values(values).target_style_names


def test_loading_profile_keeps_its_target_names(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    editor.set_values({**editor.get_values(),
                       "target_style_names": "CHT, CHS"})
    assert editor.get_values()["target_style_names"] == "CHT, CHS"
```

附加到 `tests\test_main_window.py` 末尾:

```python
# ---------- 切分頁自動掃描 ----------

def test_tab_change_triggers_auto_scan_once(qapp, monkeypatch):
    from ass_style_tool.qt.main_window import MainWindow
    window = MainWindow()
    calls = []
    monkeypatch.setattr(window.subtitle_tab, "auto_scan_once",
                        lambda: calls.append("subtitle"))
    monkeypatch.setattr(window.mkv_tab, "auto_scan_once",
                        lambda: calls.append("mkv"))
    window.tabs.setCurrentIndex(1)     # MKV
    window.tabs.setCurrentIndex(0)     # 字幕檔
    assert calls == ["mkv", "subtitle"]


def test_tab_change_ignores_tabs_without_auto_scan(qapp):
    """「樣式與預覽」分頁沒有 auto_scan_once,切過去不可炸。"""
    from ass_style_tool.qt.main_window import MainWindow
    window = MainWindow()
    window.tabs.setCurrentIndex(window.tabs.count() - 1)
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `py -m pytest tests/test_style_editor.py tests/test_main_window.py -q`
Expected: FAIL — `assert 'target_style_names' not in editor.inputs` 失敗

- [ ] **Step 3: 寫實作**

在 `style_editor.py` 的 `_TEXT_FIELDS` 移除這一行:

```python
    ("目標 Style(逗號分隔)", "target_style_names"),
```

在 `StyleEditor.__init__` 建立 `self._edits` / `self._checks` 之後加入:

```python
        # 目標 Style 已移到各工作分頁的側欄(它回答的是「這批要改哪個」,
        # 與本編輯器描述的「改成什麼樣子」不同性質)。這裡仍保留其值,
        # 因為 profile_from_values() 要求這個鍵,且存檔要原樣寫回。
        self._target_style_names = str(DEFAULT_VALUES["target_style_names"])
```

把 `get_values()` 換成(既有版本只走 `_edits` 與 `_checks`,移除輸入框後就會少掉這個鍵,`profile_from_values()` 會拋「目標 Style 名稱不可為空」):

```python
    def get_values(self) -> dict:
        values: dict = {}
        for key, edit in self._edits.items():
            values[key] = edit.text()
        for key, check in self._checks.items():
            values[key] = check.isChecked()
        values["target_style_names"] = self._target_style_names
        return values
```

在 `set_values()` 最前面(既有的 `for key, edit in ...` 之前)加入:

```python
        if "target_style_names" in values:
            self._target_style_names = str(values["target_style_names"])
```

確認 `style_editor.py` 頂端已 import `DEFAULT_VALUES`;若無則在既有 `from ..profile_fields import ...` 那行補上。

在 `main_window.py` 的 `self._restore_settings()` 之後加入:

```python
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed(self.tabs.currentIndex())
```

並加入方法:

```python
    def _on_tab_changed(self, index: int) -> None:
        """分頁第一次被顯示時才掃描它的資料夾。

        開啟時三個分頁全掃,等於為使用者沒要看的分頁白跑 ffprobe 子行程
        (一季 24 集約 1-5 秒),所以改成用到才掃。
        """
        widget = self.tabs.widget(index)
        auto_scan = getattr(widget, "auto_scan_once", None)
        if callable(auto_scan):
            auto_scan()
```

- [ ] **Step 4: 執行測試確認通過**

Run: `py -m pytest tests/test_style_editor.py tests/test_main_window.py -q`
Expected: PASS

- [ ] **Step 5: 執行全套測試**

Run: `py -m pytest tests -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ass_style_tool/qt/main_window.py ass_style_tool/qt/style_editor.py tests/test_style_editor.py tests/test_main_window.py
git commit -m "feat: scan a tab's folder on first show, drop target style field from editor"
```

---

### Task 8: 封裝分頁整合

**Files:**
- Modify: `ass_style_tool\qt\mux_tab.py`
- Test: `tests\test_mux_tab.py`(既有檔案,附加測試)

**Interfaces:**
- Consumes: `StylePicker`(Task 5)、`style_scan.scan_styles` / `summarize`(Task 1)
- Produces: `MuxTab.style_picker`、`MuxTab.auto_scan_once()`、`MuxTab.effective_profile()`

- [ ] **Step 1: 寫失敗的測試**

附加到 `tests\test_mux_tab.py` 末尾:

```python
# ---------- 目標樣式清單 ----------

def test_style_picker_hidden_when_direct_mux(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.direct_mode_radio.setChecked(True)
    assert tab.style_group.isHidden() is True


def test_style_picker_shown_when_applying_style(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.apply_mode_radio.setChecked(True)
    assert tab.style_group.isHidden() is False


def test_effective_profile_uses_picker_selection(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.style_picker.set_available(["CHT"])
    tab.style_picker.set_selected(["CHT"])
    assert tab.effective_profile().target_style_names == ["CHT"]


def test_auto_scan_once_only_scans_one_time(qapp, monkeypatch, tmp_path):
    tab = _tab(monkeypatch)
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab.video_edit.setText(str(tmp_path))
    tab.subtitle_edit.setText(str(tmp_path))
    tab.auto_scan_once()
    tab.auto_scan_once()
    assert calls == [1]


def test_auto_scan_once_skips_when_a_folder_is_missing(qapp, monkeypatch,
                                                       tmp_path):
    tab = _tab(monkeypatch)
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab.video_edit.setText(str(tmp_path))
    tab.subtitle_edit.setText("")          # 字幕資料夾還沒選
    tab.auto_scan_once()
    assert calls == []
```

封裝分頁的兩個資料夾輸入框是 `self.video_edit` 與 `self.subtitle_edit`(`mux_tab.py:74` 與 `:84`)。

- [ ] **Step 2: 執行測試確認失敗**

Run: `py -m pytest tests/test_mux_tab.py -q -k "style_picker or effective_profile or auto_scan_once"`
Expected: FAIL — `AttributeError: 'MuxTab' object has no attribute 'style_group'`

- [ ] **Step 3: 寫實作**

在 `mux_tab.py` import 區加入:

```python
from dataclasses import replace

from .style_picker import StylePicker
from ..style_scan import scan_styles, summarize
```

在側欄建構處加入(與既有 `scale_panel` 的顯示/隱藏作法一致):

```python
        self.style_picker = StylePicker()
        self.style_group = group("目標樣式", self.style_picker)
        self.style_group.setHidden(True)
```

把 `self.style_group` 加進 `settings_sidebar(...)` 的參數中。

在既有的模式切換 handler(處理 `scale_panel` 顯示/隱藏那個)裡加入:

```python
        # 直接封裝原字幕時不需要指定目標樣式
        self.style_group.setHidden(self.direct_mode_radio.isChecked())
```

加入方法:

```python
    def effective_profile(self) -> Profile:
        return replace(self._get_profile(),
                       target_style_names=self.style_picker.selected())

    def auto_scan_once(self) -> None:
        if self._auto_scanned:
            return
        if not self._folders_ready():
            return
        if self._thread is not None or self._scan_thread is not None:
            return
        self._auto_scanned = True
        self._on_scan()
```

在 `__init__` 加入 `self._auto_scanned = False`,並加入:

```python
    def _folders_ready(self) -> bool:
        """兩個資料夾都選好且真的存在才值得自動掃描。"""
        video = self.video_edit.text().strip()
        subtitle = self.subtitle_edit.text().strip()
        return bool(video and subtitle
                    and Path(video).is_dir() and Path(subtitle).is_dir())
```

在掃描完成的 handler 裡,對每個配對到字幕的列跑 `scan_styles`,再用 `summarize` 填入清單:

```python
        results = [scan_styles(p.subtitle_path) for p in pairs
                   if p.subtitle_path is not None]
        summary = summarize(results)
        self.style_picker.set_available(summary.names)
```

把送去執行的 profile 從 `self._get_profile()` 改成 `self.effective_profile()`。

在 `save_settings` / `restore_settings` 加入 `mux/styles` 的存取,寫法與 Task 6 的 `subtitle/styles` 相同。

- [ ] **Step 4: 執行測試確認通過**

Run: `py -m pytest tests/test_mux_tab.py -q`
Expected: PASS

- [ ] **Step 5: 執行全套測試**

Run: `py -m pytest tests -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ass_style_tool/qt/mux_tab.py tests/test_mux_tab.py
git commit -m "feat: add style picker and lazy auto-scan to mux tab"
```

---

### Task 9: MKV 分頁整合(範本檔按需讀取)

**Files:**
- Modify: `ass_style_tool\qt\mkv_tab.py`
- Test: `tests\test_mkv_tab.py`(既有檔案,附加測試)

**Interfaces:**
- Consumes: `StylePicker`(Task 5)、`style_scan.scan_styles`(Task 1)、既有的 `mkv_io` 抽取函式
- Produces: `MkvTab.style_picker`、`MkvTab.read_template_styles()`、`MkvTab.auto_scan_once()`、`MkvTab.effective_profile()`

**背景:** MKV 分頁的字幕在檔案內,讀樣式名須先 `mkvextract`。一季全抽很慢,且 2026-07-27 的 UI 重整才刻意移除遞迴 `mkvmerge -J` 就是嫌慢。因此改成按需從第一個檔案讀,呼應該分頁既有的「範本檔」心智模型。**此分頁沒有逐檔預告欄。**

- [ ] **Step 1: 寫失敗的測試**

附加到 `tests\test_mkv_tab.py` 末尾:

```python
# ---------- 範本檔樣式讀取 ----------

def test_read_template_styles_fills_picker(qapp, monkeypatch, tmp_path):
    from ass_style_tool.style_scan import FileStyles
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    monkeypatch.setattr(
        "ass_style_tool.qt.mkv_tab.extract_template_subtitle",
        lambda mkv, mkvmerge, mkvextract: tmp_path / "t.ass")
    monkeypatch.setattr(
        "ass_style_tool.qt.mkv_tab.scan_styles",
        lambda path: FileStyles(path, {"Default": 48.0, "CHT": 52.0}))
    tab.read_template_styles()
    from PySide6.QtCore import Qt
    names = [tab.style_picker.list.item(i).data(Qt.ItemDataRole.UserRole)
             for i in range(tab.style_picker.list.count())]
    assert sorted(names) == ["CHT", "Default"]


def test_read_template_styles_reports_no_text_track(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    monkeypatch.setattr(
        "ass_style_tool.qt.mkv_tab.extract_template_subtitle",
        lambda mkv, mkvmerge, mkvextract: None)
    messages = []
    tab.log.connect(messages.append)
    tab.read_template_styles()
    assert any("沒有文字字幕軌" in m for m in messages)


def test_effective_profile_uses_picker_selection(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.style_picker.set_available(["CHT"])
    tab.style_picker.set_selected(["CHT"])
    assert tab.effective_profile().target_style_names == ["CHT"]
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `py -m pytest tests/test_mkv_tab.py -q -k "template_styles or effective_profile"`
Expected: FAIL — `AttributeError: 'MkvTab' object has no attribute 'read_template_styles'`

- [ ] **Step 3: 寫實作**

先在 `mkv_io.py` 末尾加入。既有 API 是 `list_ass_tracks(mkv_path, mkvmerge)` 與
`extract_track(mkv_path, track_id, out_path, mkvextract)`(兩者都要外部工具路徑),
`_ASS_CODEC_IDS` 已是文字字幕的判定常數,`list_ass_tracks` 內部已依它過濾,
所以這裡只需包一層、不重寫過濾邏輯:

```python
def extract_template_subtitle(
    mkv_path: Path, mkvmerge: Path, mkvextract: Path
) -> Optional[Path]:
    """抽出影片中第一條 ASS/SSA 字幕軌到暫存檔,失敗或沒有文字軌回傳 None。

    只抽一條、只抽一個檔案——這是給「讀取樣式名稱」用的範本,不是批次處理。
    整季逐檔抽取太慢,而使用者的情境是全季樣式名一致。
    """
    tracks = list_ass_tracks(mkv_path, mkvmerge)
    if not tracks:
        return None
    out_path = Path(tempfile.gettempdir()) / f"{mkv_path.stem}.template.ass"
    if not extract_track(mkv_path, tracks[0].track_id, out_path, mkvextract):
        return None
    return out_path
```

並在 `mkv_io.py` 頂端 import 區加入 `import tempfile`(若尚未 import)。

在 `mkv_tab.py` import 區加入:

```python
from dataclasses import replace

from .style_picker import StylePicker
from ..mkv_io import extract_template_subtitle
from ..style_scan import scan_styles
```

`mkv_tab.py` 既有已 import `mkvmerge_path` / `mkvextract_path`(測試就是 monkeypatch 這兩個),下面的實作直接用它們。

在側欄加入樣式清單與按鈕:

```python
        self.style_picker = StylePicker()
        style_box = QVBoxLayout()
        style_box.addWidget(self.style_picker)
        self.read_styles_button = QPushButton("讀取樣式名稱")
        self.read_styles_button.clicked.connect(self.read_template_styles)
        style_box.addWidget(self.read_styles_button)
```

把 `group("目標樣式", style_box)` 加進 `settings_sidebar(...)`。

加入方法:

```python
    def read_template_styles(self) -> None:
        """從第一個影片抽一條文字字幕軌,讀出樣式名稱當範本。

        不逐檔抽取:一季全抽很慢,而使用者的情境是全季樣式名一致,
        一個範本檔就夠。與「修改既有軌道」對話框同一種心智模型。
        """
        files = self.current_files()
        if not files:
            self.log.emit("請先掃描資料夾")
            return
        mkvmerge, mkvextract = mkvmerge_path(), mkvextract_path()
        if mkvmerge is None or mkvextract is None:
            self.log.emit("找不到 MKVToolNix,無法讀取樣式名稱")
            return
        template = extract_template_subtitle(files[0], mkvmerge, mkvextract)
        if template is None:
            self.log.emit("這批影片沒有文字字幕軌(可能是 PGS/VobSub 圖形字幕)")
            return
        result = scan_styles(template)
        if result.error is not None:
            self.log.emit(f"範本字幕解析失敗:{result.error}")
            return
        self.style_picker.set_available(sorted(result.styles))
        self.log.emit(f"從 {files[0].name} 讀到 {len(result.styles)} 個樣式")

    def effective_profile(self) -> Profile:
        return replace(self._get_profile(),
                       target_style_names=self.style_picker.selected())

    def auto_scan_once(self) -> None:
        if self._auto_scanned:
            return
        folder = self.folder_edit.text().strip()
        if not folder or not Path(folder).is_dir():
            return
        if self._thread is not None or self._scan_thread is not None:
            return
        self._auto_scanned = True
        self._on_scan()
```

在 `__init__` 加入 `self._auto_scanned = False`。`current_files()` 依既有列檔結構實作(回傳目前列出的影片路徑清單)。

把送去執行的 profile 從 `self._get_profile()` 改成 `self.effective_profile()`。

在 `save_settings` / `restore_settings` 加入 `mkv/styles` 的存取,寫法與 Task 6 相同。

- [ ] **Step 4: 執行測試確認通過**

Run: `py -m pytest tests/test_mkv_tab.py -q`
Expected: PASS

- [ ] **Step 5: 執行全套測試**

Run: `py -m pytest tests -q`
Expected: PASS

- [ ] **Step 6: 手動冒煙測試**

```bash
py -m ass_style_tool
```

確認:四個分頁都能開;字幕檔分頁選資料夾後樣式清單自動填入、預計欄顯示 `Default xx → yy`;取消勾選後執行鈕停用;切到 MKV 分頁按「讀取樣式名稱」能列出樣式;關閉再開啟後勾選有還原。

- [ ] **Step 7: Commit**

```bash
git add ass_style_tool/qt/mkv_tab.py ass_style_tool/mkv_io.py tests/test_mkv_tab.py
git commit -m "feat: read style names from a template file in the MKV tab"
```

---

### Task 10: 「預計 / 結果」欄的狀態轉換

**Files:**
- Modify: `ass_style_tool\qt\subtitle_tab.py`
- Modify: `ass_style_tool\qt\mux_tab.py`(加同一欄)
- Modify: `ass_style_tool\qt\mkv_tab.py`(只加「結果」,無預告)
- Test: `tests\test_subtitle_tab.py`、`tests\test_mux_tab.py`

**Interfaces:**
- Consumes: 既有的 `BatchWorker.file_done = Signal(str, str)`(檔名, 狀態)、`MuxWorker` / `MkvWorker` 的對應訊號
- Produces: 各分頁的 `_set_row_result(name: str, status: str) -> None`

**背景:** spec 要求這一欄在執行中顯示「處理中…」、完成換成結果、重新掃描回到預告。不做這件事的話,上一輪的結果會留在畫面上被誤認成這次的。

- [ ] **Step 1: 寫失敗的測試**

附加到 `tests\test_subtitle_tab.py` 末尾:

```python
# ---------- 預計 / 結果 的狀態轉換 ----------

def _scan_with_one_file():
    from pathlib import Path
    from ass_style_tool.batch_runner import ScanResult
    from ass_style_tool.episode_match import MatchResult
    from ass_style_tool.style_scan import FileStyles
    return ScanResult(
        matches=[MatchResult(Path("a.ass"), 1, status="no_video")],
        styles={Path("a.ass"): FileStyles(Path("a.ass"), {"Default": 48.0},
                                          (1920, 1080))})


def test_run_start_marks_rows_in_progress(qapp):
    tab = _tab()
    tab._on_scan_finished(_scan_with_one_file())
    tab.style_picker.set_selected(["Default"])
    tab.mark_rows_pending()
    assert tab.table.item(0, 4).text() == "處理中…"


def test_file_done_replaces_cell_with_result(qapp):
    tab = _tab()
    tab._on_scan_finished(_scan_with_one_file())
    tab.style_picker.set_selected(["Default"])
    tab.mark_rows_pending()
    tab._set_row_result("a.ass", "ok")
    assert "✓" in tab.table.item(0, 4).text()


def test_rescan_restores_plan_text(qapp):
    tab = _tab()
    tab._on_scan_finished(_scan_with_one_file())
    tab.style_picker.set_selected(["Default"])
    tab.mark_rows_pending()
    tab._set_row_result("a.ass", "error")
    tab._on_scan_finished(_scan_with_one_file())      # 重新掃描
    assert "Default 48 →" in tab.table.item(0, 4).text()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `py -m pytest tests/test_subtitle_tab.py -q -k "in_progress or replaces_cell or restores_plan"`
Expected: FAIL — `AttributeError: 'SubtitleTab' object has no attribute 'mark_rows_pending'`

- [ ] **Step 3: 寫實作**

在 `subtitle_tab.py` 加入(`mux_tab.py` 用同樣兩個方法,欄位索引依該分頁實際欄數調整):

```python
_RESULT_ICONS = {"ok": "✓ 已套用", "skipped": "⊘ 略過", "error": "✗ 失敗"}


    def mark_rows_pending(self) -> None:
        """開始執行時把整欄換成「處理中…」,避免舊預告被誤讀成結果。"""
        for r in range(self.table.rowCount()):
            self.table.setItem(r, 4, QTableWidgetItem("處理中…"))

    def _set_row_result(self, name: str, status: str) -> None:
        text = _RESULT_ICONS.get(status, status)
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 1)          # 第 1 欄是字幕檔名
            if item is not None and item.text() == name:
                self.table.setItem(r, 4, QTableWidgetItem(text))
                return
```

在 `_on_run` 啟動 worker 之前呼叫 `self.mark_rows_pending()`,並把 worker 的 `file_done` 接上:

```python
        self._worker.file_done.connect(self._set_row_result)
```

`populate_preview` 已在重新掃描時重建整張表,因此重掃自動回到預告,不需額外處理。

MKV 分頁沒有預告,但同樣需要結果欄:在 `mkv_tab.py` 的 `_HEADERS`(或等效的欄位定義)末端加一欄「結果」,並加入相同的 `mark_rows_pending` / `_set_row_result`(欄位索引改為該表最後一欄,比對用的檔名欄依該表實際結構調整)。

- [ ] **Step 4: 執行測試確認通過**

Run: `py -m pytest tests/test_subtitle_tab.py tests/test_mux_tab.py tests/test_mkv_tab.py -q`
Expected: PASS

- [ ] **Step 5: 執行全套測試**

Run: `py -m pytest tests -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ass_style_tool/qt/subtitle_tab.py ass_style_tool/qt/mux_tab.py ass_style_tool/qt/mkv_tab.py tests/test_subtitle_tab.py tests/test_mux_tab.py tests/test_mkv_tab.py
git commit -m "feat: transition the plan column to per-file results during a run"
```

---

## 完成後

1. 全套測試:`py -m pytest tests -q`
2. 全分支最終程式碼審查(merge-base 取本計畫第一個 commit 之前)
3. 修完審查發現的問題後合回 master
4. **重新打包**(`dist/` 與 `installer_dist/` 目前停在 2026-07-28 16:53,不含本計畫的任何改動)
