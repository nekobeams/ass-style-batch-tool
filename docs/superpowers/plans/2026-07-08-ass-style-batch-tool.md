# ASS 字幕樣式批次修改工具 Implementation Plan

**Goal:** 建立一個 tkinter GUI 工具,批次把整季 ASS/SSA 字幕檔中指定 Style(如 Default)改成統一的目標樣式,並依各檔 PlayRes 比例縮放數值。

**Architecture:** 六個 Python 模組分層:`profile`(設定檔)→ `resolution`(解析度規則)→ `ass_style`(ASS 讀寫與套用)→ `episode_match`(集數配對)→ `batch_runner`(批次協調)→ `gui`(tkinter 介面)。GUI 只呼叫 `batch_runner` 與 `profile`,核心邏輯全部可脫離 GUI 測試。

**Tech Stack:** Python 3.9+、pysubs2(ASS 解析)、charset-normalizer(編碼偵測)、tkinter + tkinterdnd2(GUI/拖放,後者選配)、ffprobe(外部指令,選配)、pytest(測試)。

**Spec:** `docs/superpowers/specs/2026-07-08-ass-style-batch-tool-design.md`

## Global Constraints

- 工作目錄/repo root:專案根目錄,所有指令從此目錄執行
- Python 3.9+;每個模組頂端加 `from __future__ import annotations`
- 依賴:`pysubs2>=1.6`、`charset-normalizer>=3.0`、`tkinterdnd2`(選配,缺少時 GUI 退回按鈕模式)、`pytest`(開發用)
- **絕不改寫** `[Script Info]` 的 `PlayResX`/`PlayResY`/`ScaledBorderAndShadow` 標頭,只修改目標 Style 行
- 只修改 `target_style_names` 列出的 Style;找不到 → 跳過該檔並記 log,**不自動新增** Style
- 縮放參考解析度規則(與 libass/VSFilter 一致):PlayRes 兩者有效→直接用;只有一個→依 4:3 推導;全缺→384×288
- ffprobe 只用於預覽顯示與長寬比警告,**不參與縮放計算**
- 字幕輸出一律 UTF-8 with BOM(`utf-8-sig`)
- 原地覆蓋模式:寫入前必先備份 `.bak`,備份失敗則不寫入
- 單檔失敗不中斷整批,記錄後繼續
- 測試指令:`python -m pytest tests -v`(從 repo root 執行)
- Commit 訊息用 conventional commits(`feat:`/`test:`/`docs:`/`chore:`)

## File Structure

```
專案根目錄\
├── ass_style_tool\
│   ├── __init__.py        # 空檔,標記 package
│   ├── __main__.py        # python -m ass_style_tool 進入點
│   ├── profile.py         # TargetStyle/Profile dataclass、ASS 色碼轉換、JSON 讀寫
│   ├── resolution.py      # 參考解析度規則、縮放計算、ffprobe 包裝、長寬比檢查
│   ├── ass_style.py       # 編碼偵測讀檔、套用樣式、UTF-8 BOM 寫檔
│   ├── episode_match.py   # 檔名集數抽取、字幕/影片配對
│   ├── batch_runner.py    # 掃描資料夾、單檔處理(備份/輸出)、批次執行
│   └── gui.py             # tkinter GUI
├── tests\
│   ├── __init__.py        # 空檔,讓測試間可互相 import 共用 fixture
│   ├── test_profile.py
│   ├── test_resolution.py
│   ├── test_ass_style.py
│   ├── test_episode_match.py
│   └── test_batch_runner.py
├── profiles\
│   └── sample-1080p.json  # 範例設定檔
├── requirements.txt
├── .gitignore
└── README.md
```

---

### Task 1: 專案腳手架 + profile 模組(設定檔與色碼轉換)

**Files:**
- Create: `requirements.txt`, `.gitignore`, `ass_style_tool/__init__.py`
- Create: `ass_style_tool/profile.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Consumes: 無(最底層模組)
- Produces:
  - `TargetStyle` dataclass:欄位 `fontname: str, fontsize: float, bold: bool, italic: bool, primary_colour: str, outline_colour: str, back_colour: str, outline: float, shadow: float, alignment: int, margin_l: int, margin_r: int, margin_v: int`
  - `Profile` dataclass:欄位 `profile_name: str, target_style_names: list[str], base_width: int, base_height: int, style: TargetStyle`
  - `parse_ass_color(text: str) -> pysubs2.Color` — 解析 `&HAABBGGRR`,非法字串丟 `ValueError`
  - `color_to_ass(color: pysubs2.Color) -> str` — 反向轉換
  - `load_profile(path: Path) -> Profile` — 讀 JSON(spec 格式,含巢狀 `base_resolution`/`style`),非法色碼或 alignment 不在 1–9 丟 `ValueError`
  - `save_profile(profile: Profile, path: Path) -> None`

- [ ] **Step 1: 安裝依賴、建立腳手架檔案**

```powershell
python -m pip install "pysubs2>=1.6" "charset-normalizer>=3.0" tkinterdnd2 pytest
```

建立 `requirements.txt`:

```
pysubs2>=1.6
charset-normalizer>=3.0
tkinterdnd2>=0.3
pytest>=7.0
```

建立 `.gitignore`:

```
__pycache__/
*.pyc
.pytest_cache/
```

建立空檔 `ass_style_tool/__init__.py` 與 `tests/__init__.py`(內容皆為空;後者讓 `tests.test_profile` 可被其他測試檔 import 共用 fixture)。

- [ ] **Step 2: 寫失敗測試**

建立 `tests/test_profile.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pysubs2
import pytest

from ass_style_tool.profile import (Profile, TargetStyle, color_to_ass,
                                    load_profile, parse_ass_color,
                                    save_profile)


def make_style(**overrides) -> TargetStyle:
    kwargs = dict(
        fontname="思源黑體 CN", fontsize=72.0, bold=False, italic=False,
        primary_colour="&H00FFFFFF", outline_colour="&H00000000",
        back_colour="&H00000000", outline=3.6, shadow=1.0, alignment=2,
        margin_l=20, margin_r=20, margin_v=24,
    )
    kwargs.update(overrides)
    return TargetStyle(**kwargs)


def make_profile(**overrides) -> Profile:
    kwargs = dict(
        profile_name="測試設定", target_style_names=["Default"],
        base_width=1920, base_height=1080, style=make_style(),
    )
    kwargs.update(overrides)
    return Profile(**kwargs)


def test_parse_ass_color_white():
    c = parse_ass_color("&H00FFFFFF")
    assert (c.r, c.g, c.b, c.a) == (255, 255, 255, 0)


def test_parse_ass_color_component_order():
    # &HAABBGGRR: AA=12, BB=34, GG=56, RR=78
    c = parse_ass_color("&H12345678")
    assert (c.a, c.b, c.g, c.r) == (0x12, 0x34, 0x56, 0x78)


def test_parse_ass_color_trailing_ampersand():
    c = parse_ass_color("&HFFFFFF&")  # SSA v4 寫法
    assert (c.r, c.g, c.b) == (255, 255, 255)


def test_parse_ass_color_invalid_raises():
    with pytest.raises(ValueError):
        parse_ass_color("not a color")


def test_color_roundtrip():
    original = "&H12345678"
    assert color_to_ass(parse_ass_color(original)) == original


def test_profile_save_load_roundtrip(tmp_path):
    profile = make_profile()
    path = tmp_path / "p.json"
    save_profile(profile, path)
    assert load_profile(path) == profile


def test_saved_json_matches_spec_shape(tmp_path):
    path = tmp_path / "p.json"
    save_profile(make_profile(), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["base_resolution"] == {"width": 1920, "height": 1080}
    assert data["target_style_names"] == ["Default"]
    assert data["style"]["fontname"] == "思源黑體 CN"


def test_load_profile_rejects_bad_alignment(tmp_path):
    path = tmp_path / "p.json"
    save_profile(make_profile(style=make_style(alignment=10)), path)
    with pytest.raises(ValueError):
        load_profile(path)


def test_load_profile_rejects_bad_color(tmp_path):
    path = tmp_path / "p.json"
    save_profile(make_profile(style=make_style(primary_colour="oops")), path)
    with pytest.raises(ValueError):
        load_profile(path)
```

- [ ] **Step 3: 執行測試,確認失敗**

Run: `python -m pytest tests/test_profile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.profile'`

- [ ] **Step 4: 實作 profile.py**

建立 `ass_style_tool/profile.py`:

```python
"""目標樣式設定檔(Profile)的資料結構、ASS 色碼轉換與 JSON 讀寫。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pysubs2


@dataclass
class TargetStyle:
    fontname: str
    fontsize: float
    bold: bool
    italic: bool
    primary_colour: str
    outline_colour: str
    back_colour: str
    outline: float
    shadow: float
    alignment: int
    margin_l: int
    margin_r: int
    margin_v: int


@dataclass
class Profile:
    profile_name: str
    target_style_names: list[str]
    base_width: int
    base_height: int
    style: TargetStyle


def parse_ass_color(text: str) -> pysubs2.Color:
    """解析 '&HAABBGGRR' 格式色碼;非法字串丟 ValueError。"""
    cleaned = text.strip().upper()
    if cleaned.startswith("&H"):
        cleaned = cleaned[2:]
    cleaned = cleaned.rstrip("&")
    if not cleaned:
        raise ValueError(f"空白色碼: {text!r}")
    value = int(cleaned, 16)  # 非十六進位字元會丟 ValueError
    return pysubs2.Color(
        r=value & 0xFF,
        g=(value >> 8) & 0xFF,
        b=(value >> 16) & 0xFF,
        a=(value >> 24) & 0xFF,
    )


def color_to_ass(color: pysubs2.Color) -> str:
    return f"&H{color.a:02X}{color.b:02X}{color.g:02X}{color.r:02X}"


def _validate_style(style: TargetStyle) -> None:
    parse_ass_color(style.primary_colour)
    parse_ass_color(style.outline_colour)
    parse_ass_color(style.back_colour)
    if not 1 <= style.alignment <= 9:
        raise ValueError(f"alignment 必須是 1-9,收到 {style.alignment}")


def load_profile(path: Path) -> Profile:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    style = TargetStyle(**data["style"])
    _validate_style(style)
    return Profile(
        profile_name=data["profile_name"],
        target_style_names=list(data["target_style_names"]),
        base_width=int(data["base_resolution"]["width"]),
        base_height=int(data["base_resolution"]["height"]),
        style=style,
    )


def save_profile(profile: Profile, path: Path) -> None:
    data = {
        "profile_name": profile.profile_name,
        "target_style_names": profile.target_style_names,
        "base_resolution": {
            "width": profile.base_width,
            "height": profile.base_height,
        },
        "style": asdict(profile.style),
    }
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
```

- [ ] **Step 5: 執行測試,確認通過**

Run: `python -m pytest tests/test_profile.py -v`
Expected: 9 passed

- [ ] **Step 6: Commit**

```powershell
git add requirements.txt .gitignore ass_style_tool/__init__.py ass_style_tool/profile.py tests/__init__.py tests/test_profile.py
git commit -m "feat: add profile module with ASS color conversion and JSON I/O"
```

---

### Task 2: resolution 模組(參考解析度規則、縮放、ffprobe)

**Files:**
- Create: `ass_style_tool/resolution.py`
- Test: `tests/test_resolution.py`

**Interfaces:**
- Consumes: 無
- Produces:
  - `SPEC_DEFAULT_RES: tuple[int, int]` = `(384, 288)`
  - `reference_resolution(play_res_x: int, play_res_y: int) -> tuple[int, int]` — 依 libass/VSFilter 規則
  - `compute_scale(ref_w: int, ref_h: int, base_w: int, base_h: int) -> tuple[float, float]` — 回傳 `(scale_x, scale_y)`
  - `ffprobe_available() -> bool`
  - `probe_video_resolution(video_path: Path) -> tuple[int, int] | None` — 失敗一律回 `None`,不丟例外
  - `aspect_mismatch(ref: tuple[int, int], video: tuple[int, int], tolerance: float = 0.05) -> bool`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_resolution.py`:

```python
from __future__ import annotations

from pathlib import Path

from ass_style_tool.resolution import (SPEC_DEFAULT_RES, aspect_mismatch,
                                       compute_scale,
                                       probe_video_resolution,
                                       reference_resolution)


def test_reference_both_valid():
    assert reference_resolution(1920, 1080) == (1920, 1080)


def test_reference_only_x_derives_4_3():
    assert reference_resolution(1280, 0) == (1280, 960)


def test_reference_only_y_derives_4_3():
    assert reference_resolution(0, 720) == (960, 720)


def test_reference_none_uses_spec_default():
    assert reference_resolution(0, 0) == SPEC_DEFAULT_RES == (384, 288)


def test_reference_negative_treated_as_missing():
    assert reference_resolution(-1, -5) == (384, 288)


def test_compute_scale():
    sx, sy = compute_scale(1280, 720, 1920, 1080)
    assert abs(sx - 1280 / 1920) < 1e-9
    assert abs(sy - 720 / 1080) < 1e-9


def test_aspect_mismatch_43_vs_169():
    assert aspect_mismatch((640, 480), (1920, 1080)) is True


def test_aspect_match_same_ratio():
    assert aspect_mismatch((1280, 720), (1920, 1080)) is False


def test_aspect_match_within_tolerance():
    assert aspect_mismatch((1920, 1080), (1919, 1080)) is False


class FakeCompleted:
    def __init__(self, returncode: int, stdout: str = ""):
        self.returncode = returncode
        self.stdout = stdout


def test_probe_parses_output(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.resolution.subprocess.run",
        lambda *a, **k: FakeCompleted(0, "1920,1080\n"),
    )
    assert probe_video_resolution(Path("x.mkv")) == (1920, 1080)


def test_probe_nonzero_exit_returns_none(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.resolution.subprocess.run",
        lambda *a, **k: FakeCompleted(1, ""),
    )
    assert probe_video_resolution(Path("x.mkv")) is None


def test_probe_garbage_output_returns_none(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.resolution.subprocess.run",
        lambda *a, **k: FakeCompleted(0, "N/A\n"),
    )
    assert probe_video_resolution(Path("x.mkv")) is None


def test_probe_oserror_returns_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("ffprobe not found")

    monkeypatch.setattr("ass_style_tool.resolution.subprocess.run", boom)
    assert probe_video_resolution(Path("x.mkv")) is None
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `python -m pytest tests/test_resolution.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.resolution'`

- [ ] **Step 3: 實作 resolution.py**

建立 `ass_style_tool/resolution.py`:

```python
"""縮放參考解析度規則(與 libass/VSFilter 行為一致)與 ffprobe 包裝。"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

#: ASS 規範:PlayRes 全缺時播放器假設的虛擬畫布
SPEC_DEFAULT_RES: Tuple[int, int] = (384, 288)


def reference_resolution(play_res_x: int, play_res_y: int) -> Tuple[int, int]:
    """決定縮放參考解析度。

    - 兩者有效 (>0) -> 直接使用
    - 只有一個有效 -> 依 4:3 推導另一個(播放器實際行為)
    - 皆無效 -> 384x288(規範預設)
    """
    x_ok = play_res_x > 0
    y_ok = play_res_y > 0
    if x_ok and y_ok:
        return play_res_x, play_res_y
    if x_ok:
        return play_res_x, round(play_res_x * 3 / 4)
    if y_ok:
        return round(play_res_y * 4 / 3), play_res_y
    return SPEC_DEFAULT_RES


def compute_scale(ref_w: int, ref_h: int, base_w: int, base_h: int) -> Tuple[float, float]:
    """回傳 (scale_x, scale_y) = 參考解析度 / 設定檔基準解析度。"""
    return ref_w / base_w, ref_h / base_h


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def probe_video_resolution(video_path: Path) -> Optional[Tuple[int, int]]:
    """用 ffprobe 讀取影片第一條視訊流的寬高;任何失敗都回 None。"""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    stripped = result.stdout.strip()
    if not stripped:
        return None
    parts = stripped.splitlines()[0].split(",")
    if len(parts) != 2:
        return None
    try:
        width, height = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def aspect_mismatch(
    ref: Tuple[int, int], video: Tuple[int, int], tolerance: float = 0.05
) -> bool:
    """PlayRes 長寬比與影片長寬比相對誤差超過 tolerance 時回 True。"""
    ref_ratio = ref[0] / ref[1]
    video_ratio = video[0] / video[1]
    return abs(ref_ratio - video_ratio) / video_ratio > tolerance
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `python -m pytest tests/test_resolution.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```powershell
git add ass_style_tool/resolution.py tests/test_resolution.py
git commit -m "feat: add resolution module with libass-compatible reference rules and ffprobe wrapper"
```

---

### Task 3: ass_style 模組(編碼偵測、樣式套用、BOM 寫檔)

**Files:**
- Create: `ass_style_tool/ass_style.py`
- Test: `tests/test_ass_style.py`

**Interfaces:**
- Consumes: `profile.Profile`, `profile.parse_ass_color`, `resolution.reference_resolution`, `resolution.compute_scale`
- Produces:
  - `detect_and_decode(path: Path) -> str` — 先試 `utf-8-sig`,再用 charset-normalizer;全失敗丟 `ValueError`
  - `load_subs(path: Path) -> pysubs2.SSAFile`
  - `save_subs(subs: pysubs2.SSAFile, path: Path) -> None` — 寫 UTF-8 with BOM 的 ASS
  - `get_play_res(subs: pysubs2.SSAFile) -> tuple[int, int]` — 讀不到/非數字回 0
  - `get_scaled_border_shadow(subs: pysubs2.SSAFile) -> str` — 標頭缺失回 `"unset"`
  - `apply_profile(subs: pysubs2.SSAFile, profile: Profile) -> list[str]` — 就地修改,回傳實際修改到的 Style 名稱

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_ass_style.py`:

```python
from __future__ import annotations

from pathlib import Path

import pysubs2
import pytest

from ass_style_tool.ass_style import (apply_profile, detect_and_decode,
                                      get_play_res,
                                      get_scaled_border_shadow, load_subs,
                                      save_subs)
from tests.test_profile import make_profile, make_style

SAMPLE_ASS = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,10,1
Style: OP,Comic Sans MS,60,&H0000FFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,8,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,測試字幕一
Dialogue: 0,0:00:04.00,0:00:06.00,OP,,0,0,0,,片頭曲
"""


def test_load_utf8_bom(tmp_path):
    path = tmp_path / "a.ass"
    path.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    subs = load_subs(path)
    assert "測試字幕一" in subs.events[0].text


def test_load_utf8_no_bom(tmp_path):
    path = tmp_path / "a.ass"
    path.write_bytes(SAMPLE_ASS.encode("utf-8"))
    subs = load_subs(path)
    assert subs.styles["Default"].fontname == "Arial"


def test_load_big5(tmp_path):
    long_line = (
        "這是一段比較長的繁體中文字幕內容,用來讓編碼偵測擁有足夠的樣本資料,"
        "裡面包含常見的標點符號、以及像動畫、字幕、樣式這些常用詞彙。"
    )
    text = SAMPLE_ASS.replace("測試字幕一", long_line)
    path = tmp_path / "big5.ass"
    path.write_bytes(text.encode("big5"))
    subs = load_subs(path)
    assert "繁體中文字幕內容" in subs.events[0].text


def test_undecodable_raises(tmp_path):
    path = tmp_path / "bad.ass"
    path.write_bytes(bytes(range(256)) * 4)
    with pytest.raises(ValueError):
        detect_and_decode(path)


def test_save_writes_utf8_bom(tmp_path):
    subs = pysubs2.SSAFile.from_string(SAMPLE_ASS)
    out = tmp_path / "out.ass"
    save_subs(subs, out)
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")
    # 能重新讀回
    assert "Default" in load_subs(out).styles


def test_get_play_res():
    subs = pysubs2.SSAFile.from_string(SAMPLE_ASS)
    assert get_play_res(subs) == (1280, 720)


def test_get_play_res_missing():
    stripped = SAMPLE_ASS.replace("PlayResX: 1280\nPlayResY: 720\n", "")
    subs = pysubs2.SSAFile.from_string(stripped)
    assert get_play_res(subs) == (0, 0)


def test_get_scaled_border_shadow_unset():
    subs = pysubs2.SSAFile.from_string(SAMPLE_ASS)
    assert get_scaled_border_shadow(subs) == "unset"


def test_get_scaled_border_shadow_present():
    text = SAMPLE_ASS.replace(
        "ScriptType: v4.00+", "ScriptType: v4.00+\nScaledBorderAndShadow: yes"
    )
    subs = pysubs2.SSAFile.from_string(text)
    assert get_scaled_border_shadow(subs) == "yes"


def test_apply_profile_scales_to_720p():
    subs = pysubs2.SSAFile.from_string(SAMPLE_ASS)
    modified = apply_profile(subs, make_profile())
    assert modified == ["Default"]
    st = subs.styles["Default"]
    # scale_y = 720/1080, scale_x = 1280/1920
    assert st.fontname == "思源黑體 CN"
    assert st.fontsize == 48          # round(72 * 720/1080)
    assert st.outline == 2.4          # round(3.6 * 720/1080, 2)
    assert st.shadow == 0.67          # round(1.0 * 720/1080, 2)
    assert st.marginv == 16           # round(24 * 720/1080)
    assert st.marginl == 13           # round(20 * 1280/1920)
    assert st.marginr == 13
    assert int(st.alignment) == 2
    assert (st.primarycolor.r, st.primarycolor.g, st.primarycolor.b) == (255, 255, 255)


def test_apply_profile_leaves_other_styles_untouched():
    subs = pysubs2.SSAFile.from_string(SAMPLE_ASS)
    apply_profile(subs, make_profile())
    op = subs.styles["OP"]
    assert op.fontname == "Comic Sans MS"
    assert op.fontsize == 60


def test_apply_profile_missing_style_returns_empty():
    subs = pysubs2.SSAFile.from_string(SAMPLE_ASS)
    profile = make_profile(target_style_names=["不存在的樣式"])
    assert apply_profile(subs, profile) == []
    assert "不存在的樣式" not in subs.styles  # 不自動新增


def test_apply_profile_no_playres_uses_spec_default():
    stripped = SAMPLE_ASS.replace("PlayResX: 1280\nPlayResY: 720\n", "")
    subs = pysubs2.SSAFile.from_string(stripped)
    apply_profile(subs, make_profile())
    # scale_y = 288/1080
    assert subs.styles["Default"].fontsize == 19  # round(72 * 288/1080) = round(19.2)


def test_apply_profile_does_not_touch_headers():
    subs = pysubs2.SSAFile.from_string(SAMPLE_ASS)
    apply_profile(subs, make_profile())
    assert subs.info["PlayResX"] == "1280"
    assert subs.info["PlayResY"] == "720"
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `python -m pytest tests/test_ass_style.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.ass_style'`

- [ ] **Step 3: 實作 ass_style.py**

建立 `ass_style_tool/ass_style.py`:

```python
"""ASS 檔案讀寫(含編碼偵測)與目標樣式套用。"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import pysubs2
from charset_normalizer import from_bytes

from .profile import Profile, parse_ass_color
from .resolution import compute_scale, reference_resolution


def detect_and_decode(path: Path) -> str:
    """讀檔並解碼:先試 utf-8-sig(涵蓋含/不含 BOM 的 UTF-8),
    失敗再用 charset-normalizer 統計偵測(涵蓋 Big5/GBK 等)。"""
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    best = from_bytes(raw).best()
    if best is None:
        raise ValueError(f"無法判斷檔案編碼: {path}")
    return str(best)


def load_subs(path: Path) -> pysubs2.SSAFile:
    return pysubs2.SSAFile.from_string(detect_and_decode(path))


def save_subs(subs: pysubs2.SSAFile, path: Path) -> None:
    """一律輸出 UTF-8 with BOM(Aegisub 預設)。"""
    Path(path).write_text(subs.to_string("ass"), encoding="utf-8-sig")


def get_play_res(subs: pysubs2.SSAFile) -> Tuple[int, int]:
    def _read(key: str) -> int:
        try:
            return int(float(subs.info.get(key, 0)))
        except (TypeError, ValueError):
            return 0

    return _read("PlayResX"), _read("PlayResY")


def get_scaled_border_shadow(subs: pysubs2.SSAFile) -> str:
    return str(subs.info.get("ScaledBorderAndShadow", "unset"))


def apply_profile(subs: pysubs2.SSAFile, profile: Profile) -> List[str]:
    """把 profile 的目標樣式套用到指定名稱的 Style(依 PlayRes 規則縮放)。

    只修改 [V4+ Styles] 中對應的行;絕不改寫 Script Info 標頭、
    不新增 Style。回傳實際修改到的 Style 名稱。
    """
    ref_w, ref_h = reference_resolution(*get_play_res(subs))
    scale_x, scale_y = compute_scale(
        ref_w, ref_h, profile.base_width, profile.base_height
    )
    target = profile.style
    modified: List[str] = []
    for name in profile.target_style_names:
        style = subs.styles.get(name)
        if style is None:
            continue
        style.fontname = target.fontname
        style.fontsize = round(target.fontsize * scale_y)
        style.bold = target.bold
        style.italic = target.italic
        style.primarycolor = parse_ass_color(target.primary_colour)
        style.outlinecolor = parse_ass_color(target.outline_colour)
        style.backcolor = parse_ass_color(target.back_colour)
        style.outline = round(target.outline * scale_y, 2)
        style.shadow = round(target.shadow * scale_y, 2)
        style.alignment = pysubs2.Alignment(target.alignment)
        style.marginl = round(target.margin_l * scale_x)
        style.marginr = round(target.margin_r * scale_x)
        style.marginv = round(target.margin_v * scale_y)
        modified.append(name)
    return modified
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `python -m pytest tests/test_ass_style.py -v`
Expected: 14 passed
(若 `test_load_big5` 因 charset-normalizer 偵測結果不同而失敗,把測試中的中文樣本再加長一倍後重跑;實作不變。)

- [ ] **Step 5: Commit**

```powershell
git add ass_style_tool/ass_style.py tests/test_ass_style.py
git commit -m "feat: add ass_style module with encoding detection and scaled style application"
```

---

### Task 4: episode_match 模組(集數抽取與配對)

**Files:**
- Create: `ass_style_tool/episode_match.py`
- Test: `tests/test_episode_match.py`

**Interfaces:**
- Consumes: 無
- Produces:
  - `SUB_EXTS: set[str]`(`.ass`/`.ssa`)、`VIDEO_EXTS: set[str]`(常見影片副檔名)
  - `extract_episode(filename: str) -> int | None`
  - `MatchResult` dataclass:欄位 `sub_path: Path, episode: int | None, video_path: Path | None = None, video_resolution: tuple[int, int] | None = None, status: str = "no_video"`;status 值域 `"matched" | "no_video" | "ambiguous" | "no_episode"`
  - `find_files(folder: Path) -> tuple[list[Path], list[Path]]` — 遞迴掃描,回傳 (字幕檔, 影片檔),各自排序
  - `match_pairs(sub_paths: list[Path], video_paths: list[Path]) -> list[MatchResult]`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_episode_match.py`(集數樣本直接取自使用者的真實檔名):

```python
from __future__ import annotations

from pathlib import Path

from ass_style_tool.episode_match import (MatchResult, extract_episode,
                                          find_files, match_pairs)


def test_extract_bracketed_episode_dbd():
    name = "[DBD-Raws][High School DxD Born][01][1080P][BDRip][HEVC-10bit][FLAC].tc.ass"
    assert extract_episode(name) == 1


def test_extract_bracketed_episode_vcb():
    name = "[VCB-Studio] Blend S [12][Ma10p_1080p][x265_flac_aac].mkv"
    assert extract_episode(name) == 12


def test_extract_dash_episode_lolihouse():
    name = "[LoliHouse] Blend S - 12 [WebRip 1920x1080 HEVC-yuv420p10 AAC].LKSub-sc_繁_台.ass"
    assert extract_episode(name) == 12


def test_extract_sxxexx():
    assert extract_episode("Show.S01E05.1080p.mkv") == 5


def test_extract_ep_prefix():
    assert extract_episode("Anime EP07 BDRip.ass") == 7


def test_bracketed_720_excluded_finds_real_episode():
    assert extract_episode("[Group] Show [720][04].mkv") == 4


def test_resolution_in_brackets_not_episode():
    # [1080P] 非純數字、720p 也非純數字,唯一集數是 [03]
    assert extract_episode("[Group] Anime [1080P][03].ass") == 3


def test_no_episode_returns_none():
    assert extract_episode("movie.ass") is None


def test_find_files(tmp_path):
    (tmp_path / "a [01].ass").write_text("x", encoding="utf-8")
    (tmp_path / "sub" ).mkdir()
    (tmp_path / "sub" / "b [02].ssa").write_text("x", encoding="utf-8")
    (tmp_path / "v [01].mkv").write_bytes(b"")
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    subs, videos = find_files(tmp_path)
    assert [p.name for p in subs] == ["a [01].ass", "b [02].ssa"]
    assert [p.name for p in videos] == ["v [01].mkv"]


def _paths(*names: str) -> list[Path]:
    return [Path(n) for n in names]


def test_match_one_to_one():
    results = match_pairs(
        _paths("[A] Show [01].ass", "[A] Show [02].ass"),
        _paths("[B] Show - 01 [x].mkv", "[B] Show - 02 [x].mkv"),
    )
    assert [r.status for r in results] == ["matched", "matched"]
    assert results[0].video_path == Path("[B] Show - 01 [x].mkv")
    assert results[0].episode == 1


def test_match_no_video():
    results = match_pairs(_paths("[A] Show [03].ass"), [])
    assert results[0].status == "no_video"
    assert results[0].video_path is None


def test_match_no_episode():
    results = match_pairs(_paths("opening.ass"), _paths("[B] Show - 01.mkv"))
    assert results[0].status == "no_episode"


def test_match_ambiguous_two_videos():
    results = match_pairs(
        _paths("[A] Show [01].ass"),
        _paths("[B] Show - 01 [720p].mkv", "[C] Show - 01 [1080p].mkv"),
    )
    assert results[0].status == "ambiguous"
    assert results[0].video_path is None


def test_match_ambiguous_two_subs_same_episode():
    results = match_pairs(
        _paths("[A] Show [01].tc.ass", "[A] Show [01].sc.ass"),
        _paths("[B] Show - 01.mkv"),
    )
    assert [r.status for r in results] == ["ambiguous", "ambiguous"]
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `python -m pytest tests/test_episode_match.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.episode_match'`

- [ ] **Step 3: 實作 episode_match.py**

建立 `ass_style_tool/episode_match.py`:

```python
"""從檔名抽取集數編號,並把字幕檔與影片檔配對。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SUB_EXTS = {".ass", ".ssa"}
VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".webm", ".mov", ".flv", ".wmv"}

#: 幾乎可以肯定是解析度而非集數的 1-3 位數字
_NON_EPISODE_NUMBERS = {480, 540, 576, 720, 960}

#: 依優先序嘗試的集數樣式
_PATTERNS = [
    re.compile(r"S\d{1,2}E(\d{1,3})", re.IGNORECASE),          # S01E05
    re.compile(r"\bEP?(\d{1,3})\b", re.IGNORECASE),             # E05 / EP05
    re.compile(r"\[(\d{1,3})(?:v\d)?\]"),                       # [05] / [05v2]
    re.compile(r"[ _]-[ _](\d{1,3})(?=[ _\[\(.]|$)"),           # " - 05 "
]


def extract_episode(filename: str) -> Optional[int]:
    name = Path(filename).name
    for pattern in _PATTERNS:
        for match in pattern.finditer(name):
            value = int(match.group(1))
            if value in _NON_EPISODE_NUMBERS:
                continue
            return value
    return None


@dataclass
class MatchResult:
    sub_path: Path
    episode: Optional[int]
    video_path: Optional[Path] = None
    video_resolution: Optional[Tuple[int, int]] = None
    status: str = "no_video"  # matched | no_video | ambiguous | no_episode


def find_files(folder: Path) -> Tuple[List[Path], List[Path]]:
    subs: List[Path] = []
    videos: List[Path] = []
    for path in sorted(Path(folder).rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext in SUB_EXTS:
            subs.append(path)
        elif ext in VIDEO_EXTS:
            videos.append(path)
    return subs, videos


def match_pairs(
    sub_paths: List[Path], video_paths: List[Path]
) -> List[MatchResult]:
    videos_by_ep: Dict[int, List[Path]] = {}
    for video in video_paths:
        ep = extract_episode(video.name)
        if ep is not None:
            videos_by_ep.setdefault(ep, []).append(video)

    sub_eps = [extract_episode(sub.name) for sub in sub_paths]
    sub_ep_counts: Dict[int, int] = {}
    for ep in sub_eps:
        if ep is not None:
            sub_ep_counts[ep] = sub_ep_counts.get(ep, 0) + 1

    results: List[MatchResult] = []
    for sub, ep in zip(sub_paths, sub_eps):
        if ep is None:
            results.append(MatchResult(sub_path=sub, episode=None, status="no_episode"))
            continue
        candidates = videos_by_ep.get(ep, [])
        if sub_ep_counts[ep] > 1 or len(candidates) > 1:
            results.append(MatchResult(sub_path=sub, episode=ep, status="ambiguous"))
        elif len(candidates) == 1:
            results.append(
                MatchResult(sub_path=sub, episode=ep,
                            video_path=candidates[0], status="matched")
            )
        else:
            results.append(MatchResult(sub_path=sub, episode=ep, status="no_video"))
    return results
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `python -m pytest tests/test_episode_match.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```powershell
git add ass_style_tool/episode_match.py tests/test_episode_match.py
git commit -m "feat: add episode extraction and subtitle/video matching"
```

---

### Task 5: batch_runner 模組(掃描、單檔處理、批次執行)

**Files:**
- Create: `ass_style_tool/batch_runner.py`
- Test: `tests/test_batch_runner.py`

**Interfaces:**
- Consumes:
  - `ass_style.load_subs / save_subs / apply_profile / get_play_res / get_scaled_border_shadow`
  - `episode_match.find_files / match_pairs / MatchResult`
  - `resolution.reference_resolution / probe_video_resolution / ffprobe_available / aspect_mismatch`
  - `profile.Profile`
- Produces:
  - `FileReport` dataclass:欄位 `sub_path: Path, status: str, messages: list[str]`;status 值域 `"ok" | "skipped" | "error"`
  - `ScanResult` dataclass:欄位 `matches: list[MatchResult], warnings: list[str]`
  - `scan_folder(folder: Path) -> ScanResult` — 掃描+配對+(ffprobe 可用時)填 `video_resolution`
  - `process_file(match: MatchResult, profile: Profile, output_dir: Path | None) -> FileReport` — `output_dir=None` 表原地覆蓋(先備份 `.bak`)
  - `run_batch(scan: ScanResult, profile: Profile, output_dir: Path | None = None, progress_cb: Callable[[FileReport], None] | None = None) -> list[FileReport]`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_batch_runner.py`:

```python
from __future__ import annotations

from pathlib import Path

import pysubs2

from ass_style_tool.batch_runner import (FileReport, ScanResult,
                                         process_file, run_batch,
                                         scan_folder)
from ass_style_tool.episode_match import MatchResult
from tests.test_ass_style import SAMPLE_ASS
from tests.test_profile import make_profile


def _write_sample(tmp_path: Path, name: str = "[A] Show [01].ass") -> Path:
    path = tmp_path / name
    path.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    return path


def test_process_file_inplace_backs_up_and_modifies(tmp_path):
    sub = _write_sample(tmp_path)
    original_bytes = sub.read_bytes()
    report = process_file(MatchResult(sub_path=sub, episode=1), make_profile(), None)
    assert report.status == "ok"
    backup = tmp_path / "[A] Show [01].ass.bak"
    assert backup.read_bytes() == original_bytes
    updated = pysubs2.SSAFile.from_string(sub.read_text(encoding="utf-8-sig"))
    assert updated.styles["Default"].fontname == "思源黑體 CN"
    assert updated.styles["Default"].fontsize == 48


def test_process_file_output_dir_leaves_original(tmp_path):
    sub = _write_sample(tmp_path)
    original_bytes = sub.read_bytes()
    out_dir = tmp_path / "out"
    report = process_file(MatchResult(sub_path=sub, episode=1), make_profile(), out_dir)
    assert report.status == "ok"
    assert sub.read_bytes() == original_bytes          # 原檔不動
    assert not (tmp_path / "[A] Show [01].ass.bak").exists()  # 不備份
    produced = out_dir / "[A] Show [01].ass"
    updated = pysubs2.SSAFile.from_string(produced.read_text(encoding="utf-8-sig"))
    assert updated.styles["Default"].fontsize == 48


def test_process_file_missing_style_skipped(tmp_path):
    sub = _write_sample(tmp_path)
    profile = make_profile(target_style_names=["沒有這個"])
    report = process_file(MatchResult(sub_path=sub, episode=1), profile, None)
    assert report.status == "skipped"
    assert not (tmp_path / "[A] Show [01].ass.bak").exists()  # 沒改就不備份


def test_process_file_corrupt_is_error(tmp_path):
    sub = tmp_path / "bad [01].ass"
    sub.write_text("this is not a subtitle file", encoding="utf-8")
    report = process_file(MatchResult(sub_path=sub, episode=1), make_profile(), None)
    assert report.status == "error"


def test_process_file_logs_metadata(tmp_path):
    sub = _write_sample(tmp_path)
    match = MatchResult(sub_path=sub, episode=1, video_resolution=(640, 480))
    report = process_file(match, make_profile(), None)
    joined = "\n".join(report.messages)
    assert "ScaledBorderAndShadow: unset" in joined
    assert "1280x720" in joined       # 縮放參考解析度
    assert "長寬比" in joined          # 720p PlayRes vs 4:3 影片 -> 警告


def test_scan_folder_matches_and_warns_without_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.batch_runner.ffprobe_available", lambda: False
    )
    _write_sample(tmp_path, "[A] Show [01].ass")
    (tmp_path / "[B] Show - 01 [x].mkv").write_bytes(b"")
    scan = scan_folder(tmp_path)
    assert len(scan.matches) == 1
    assert scan.matches[0].status == "matched"
    assert scan.matches[0].video_resolution is None
    assert any("ffprobe" in w for w in scan.warnings)


def test_scan_folder_empty_warns(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.batch_runner.ffprobe_available", lambda: False
    )
    scan = scan_folder(tmp_path)
    assert scan.matches == []
    assert any("找不到" in w for w in scan.warnings)


def test_run_batch_continues_after_error(tmp_path):
    good = _write_sample(tmp_path, "[A] Show [01].ass")
    bad = tmp_path / "[A] Show [02].ass"
    bad.write_text("garbage", encoding="utf-8")
    scan = ScanResult(
        matches=[
            MatchResult(sub_path=good, episode=1),
            MatchResult(sub_path=bad, episode=2),
        ],
        warnings=[],
    )
    seen: list[FileReport] = []
    reports = run_batch(scan, make_profile(), None, progress_cb=seen.append)
    assert [r.status for r in reports] == ["ok", "error"]
    assert len(seen) == 2
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `python -m pytest tests/test_batch_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.batch_runner'`

- [ ] **Step 3: 實作 batch_runner.py**

建立 `ass_style_tool/batch_runner.py`:

```python
"""批次流程協調:掃描資料夾、逐檔套用樣式、輸出/備份與紀錄。"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from .ass_style import (apply_profile, get_play_res,
                        get_scaled_border_shadow, load_subs, save_subs)
from .episode_match import MatchResult, find_files, match_pairs
from .profile import Profile
from .resolution import (aspect_mismatch, ffprobe_available,
                         probe_video_resolution, reference_resolution)


@dataclass
class FileReport:
    sub_path: Path
    status: str  # ok | skipped | error
    messages: List[str] = field(default_factory=list)


@dataclass
class ScanResult:
    matches: List[MatchResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def scan_folder(folder: Path) -> ScanResult:
    subs, videos = find_files(folder)
    scan = ScanResult(matches=match_pairs(subs, videos))
    if not subs:
        scan.warnings.append("資料夾內找不到任何 .ass/.ssa 字幕檔")
    if not ffprobe_available():
        scan.warnings.append("找不到 ffprobe:預覽將不含影片解析度資訊與長寬比警告")
        return scan
    for match in scan.matches:
        if match.video_path is not None:
            match.video_resolution = probe_video_resolution(match.video_path)
    return scan


def process_file(
    match: MatchResult, profile: Profile, output_dir: Optional[Path]
) -> FileReport:
    report = FileReport(sub_path=match.sub_path, status="ok")
    try:
        subs = load_subs(match.sub_path)
    except Exception as exc:  # 單檔失敗不可中斷整批
        return FileReport(match.sub_path, "error", [f"讀取失敗: {exc}"])

    report.messages.append(
        f"ScaledBorderAndShadow: {get_scaled_border_shadow(subs)}"
    )
    ref_w, ref_h = reference_resolution(*get_play_res(subs))
    report.messages.append(f"縮放參考解析度: {ref_w}x{ref_h}")
    if match.video_resolution is not None and aspect_mismatch(
        (ref_w, ref_h), match.video_resolution
    ):
        vw, vh = match.video_resolution
        report.messages.append(
            f"警告: PlayRes 長寬比與影片 {vw}x{vh} 不符,字幕可能變形,建議人工檢查"
        )

    modified = apply_profile(subs, profile)
    if not modified:
        report.status = "skipped"
        report.messages.append(
            f"找不到目標 Style {profile.target_style_names},未修改"
        )
        return report
    report.messages.append(f"已套用樣式到: {', '.join(modified)}")

    try:
        if output_dir is None:
            backup = match.sub_path.with_name(match.sub_path.name + ".bak")
            shutil.copy2(match.sub_path, backup)  # 備份失敗會丟例外 -> 不寫入
            save_subs(subs, match.sub_path)
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            save_subs(subs, output_dir / match.sub_path.name)
    except Exception as exc:
        return FileReport(
            match.sub_path, "error", report.messages + [f"寫入失敗: {exc}"]
        )
    return report


def run_batch(
    scan: ScanResult,
    profile: Profile,
    output_dir: Optional[Path] = None,
    progress_cb: Optional[Callable[[FileReport], None]] = None,
) -> List[FileReport]:
    reports: List[FileReport] = []
    for match in scan.matches:
        report = process_file(match, profile, output_dir)
        reports.append(report)
        if progress_cb is not None:
            progress_cb(report)
    return reports
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `python -m pytest tests/test_batch_runner.py -v`
Expected: 8 passed

- [ ] **Step 5: 跑全部測試確認沒破壞其他模組**

Run: `python -m pytest tests -v`
Expected: 58 passed(9+13+14+14+8)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/batch_runner.py tests/test_batch_runner.py
git commit -m "feat: add batch runner with scan preview, backup and per-file error isolation"
```

---

### Task 6: GUI 與進入點

**Files:**
- Create: `ass_style_tool/gui.py`
- Create: `ass_style_tool/__main__.py`

**Interfaces:**
- Consumes: `batch_runner.scan_folder / run_batch`、`profile.Profile / TargetStyle / load_profile / save_profile / parse_ass_color`、`resolution.ffprobe_available`
- Produces: `gui.main() -> None`(建立 App 並進 mainloop);`python -m ass_style_tool` 可啟動

GUI 無自動化測試(tkinter 視窗),以 import 檢查 + 手動冒煙測試驗證。

- [ ] **Step 1: 實作 gui.py**

建立 `ass_style_tool/gui.py`:

```python
"""tkinter GUI:拖放資料夾、編輯目標樣式、掃描預覽、批次套用。"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, scrolledtext, ttk

from .batch_runner import run_batch, scan_folder
from .profile import (Profile, TargetStyle, load_profile, parse_ass_color,
                      save_profile)
from .resolution import ffprobe_available

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except ImportError:  # 未安裝 tkinterdnd2 -> 退回純按鈕模式
    _HAS_DND = False

_STATUS_LABELS = {
    "matched": "已配對",
    "no_video": "無對應影片",
    "no_episode": "無法判斷集數",
    "ambiguous": "配對模糊",
}
_REPORT_LABELS = {"ok": "完成", "skipped": "跳過", "error": "錯誤"}


def _ass_to_hex_rgb(ass_colour: str) -> str:
    c = parse_ass_color(ass_colour)
    return f"#{c.r:02x}{c.g:02x}{c.b:02x}"


class App:
    def __init__(self) -> None:
        self.root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
        self.root.title("ASS 字幕樣式批次工具")
        self.scan_result = None
        self.log_queue: "queue.Queue[str]" = queue.Queue()

        self.folder_var = tk.StringVar()
        self.output_mode_var = tk.StringVar(value="inplace")
        self.output_dir_var = tk.StringVar()
        self.profile_name_var = tk.StringVar(value="我的字幕標準")
        self.target_styles_var = tk.StringVar(value="Default")
        self.base_w_var = tk.StringVar(value="1920")
        self.base_h_var = tk.StringVar(value="1080")
        self.fontname_var = tk.StringVar(value="思源黑體 CN")
        self.fontsize_var = tk.StringVar(value="72")
        self.bold_var = tk.BooleanVar(value=False)
        self.italic_var = tk.BooleanVar(value=False)
        self.colour_vars = {
            "主色": tk.StringVar(value="&H00FFFFFF"),
            "外框色": tk.StringVar(value="&H00000000"),
            "陰影色": tk.StringVar(value="&H00000000"),
        }
        self.outline_var = tk.StringVar(value="3.6")
        self.shadow_var = tk.StringVar(value="1.0")
        self.alignment_var = tk.StringVar(value="2")
        self.margin_l_var = tk.StringVar(value="20")
        self.margin_r_var = tk.StringVar(value="20")
        self.margin_v_var = tk.StringVar(value="24")

        self._build()
        if not ffprobe_available():
            self._log("提示: 找不到 ffprobe,預覽將不含影片解析度資訊與長寬比警告")
        self.root.after(100, self._poll_log)

    # ---------- UI 構建 ----------
    def _build(self) -> None:
        pad = {"padx": 4, "pady": 2}

        folder_frame = ttk.LabelFrame(self.root, text="輸入資料夾(可拖放)")
        folder_frame.pack(fill="x", **pad)
        entry = ttk.Entry(folder_frame, textvariable=self.folder_var)
        entry.pack(side="left", fill="x", expand=True, **pad)
        ttk.Button(folder_frame, text="瀏覽...",
                   command=self._browse_folder).pack(side="left", **pad)
        if _HAS_DND:
            for widget in (self.root, entry):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)

        style_frame = ttk.LabelFrame(self.root, text="目標樣式")
        style_frame.pack(fill="x", **pad)
        text_rows = [
            ("設定檔名稱", self.profile_name_var),
            ("目標 Style 名稱(逗號分隔)", self.target_styles_var),
            ("字型名稱", self.fontname_var),
            ("字體大小", self.fontsize_var),
            ("外框寬度", self.outline_var),
            ("陰影深度", self.shadow_var),
        ]
        row = 0
        for label, var in text_rows:
            ttk.Label(style_frame, text=label).grid(
                row=row, column=0, sticky="w", **pad)
            ttk.Entry(style_frame, textvariable=var, width=32).grid(
                row=row, column=1, sticky="we", **pad)
            row += 1

        ttk.Label(style_frame, text="基準解析度(寬 x 高)").grid(
            row=row, column=0, sticky="w", **pad)
        res_box = ttk.Frame(style_frame)
        res_box.grid(row=row, column=1, sticky="w")
        ttk.Entry(res_box, textvariable=self.base_w_var, width=6).pack(side="left")
        ttk.Label(res_box, text=" x ").pack(side="left")
        ttk.Entry(res_box, textvariable=self.base_h_var, width=6).pack(side="left")
        row += 1

        ttk.Label(style_frame, text="粗體 / 斜體").grid(
            row=row, column=0, sticky="w", **pad)
        flag_box = ttk.Frame(style_frame)
        flag_box.grid(row=row, column=1, sticky="w")
        ttk.Checkbutton(flag_box, text="粗體",
                        variable=self.bold_var).pack(side="left")
        ttk.Checkbutton(flag_box, text="斜體",
                        variable=self.italic_var).pack(side="left")
        row += 1

        ttk.Label(style_frame, text="對齊(1-9,小鍵盤方位)").grid(
            row=row, column=0, sticky="w", **pad)
        ttk.Combobox(style_frame, textvariable=self.alignment_var,
                     values=[str(i) for i in range(1, 10)], width=4,
                     state="readonly").grid(row=row, column=1, sticky="w", **pad)
        row += 1

        ttk.Label(style_frame, text="邊距 L / R / V").grid(
            row=row, column=0, sticky="w", **pad)
        margin_box = ttk.Frame(style_frame)
        margin_box.grid(row=row, column=1, sticky="w")
        for var in (self.margin_l_var, self.margin_r_var, self.margin_v_var):
            ttk.Entry(margin_box, textvariable=var, width=6).pack(
                side="left", padx=2)
        row += 1

        self._swatches: dict[str, tk.Label] = {}
        for label, var in self.colour_vars.items():
            ttk.Label(style_frame, text=label).grid(
                row=row, column=0, sticky="w", **pad)
            colour_box = ttk.Frame(style_frame)
            colour_box.grid(row=row, column=1, sticky="w")
            swatch = tk.Label(colour_box, width=3, relief="sunken",
                              background=_ass_to_hex_rgb(var.get()))
            swatch.pack(side="left", padx=2)
            ttk.Entry(colour_box, textvariable=var, width=12).pack(
                side="left", padx=2)
            ttk.Button(colour_box, text="選色...",
                       command=lambda v=var: self._pick_colour(v)).pack(side="left")
            self._swatches[label] = swatch
            var.trace_add("write", lambda *_: self._refresh_swatches())
            row += 1
        style_frame.columnconfigure(1, weight=1)

        profile_frame = ttk.Frame(self.root)
        profile_frame.pack(fill="x", **pad)
        ttk.Button(profile_frame, text="載入設定檔...",
                   command=self._load_profile).pack(side="left", **pad)
        ttk.Button(profile_frame, text="另存設定檔...",
                   command=self._save_profile).pack(side="left", **pad)

        out_frame = ttk.LabelFrame(self.root, text="輸出模式")
        out_frame.pack(fill="x", **pad)
        ttk.Radiobutton(out_frame, text="原地覆蓋(自動備份 .bak)",
                        variable=self.output_mode_var,
                        value="inplace").pack(anchor="w")
        out_row = ttk.Frame(out_frame)
        out_row.pack(fill="x")
        ttk.Radiobutton(out_row, text="輸出到新資料夾:",
                        variable=self.output_mode_var,
                        value="outdir").pack(side="left")
        ttk.Entry(out_row, textvariable=self.output_dir_var).pack(
            side="left", fill="x", expand=True, **pad)
        ttk.Button(out_row, text="瀏覽...",
                   command=self._browse_output_dir).pack(side="left", **pad)

        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill="x", **pad)
        self.scan_button = ttk.Button(action_frame, text="掃描並預覽配對",
                                      command=self._start_scan)
        self.scan_button.pack(side="left", **pad)
        self.run_button = ttk.Button(action_frame, text="開始套用樣式",
                                     command=self._start_run, state="disabled")
        self.run_button.pack(side="left", **pad)

        self.log_text = scrolledtext.ScrolledText(
            self.root, height=16, state="disabled")
        self.log_text.pack(fill="both", expand=True, **pad)

    # ---------- 檔案/顏色選擇 ----------
    def _browse_folder(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.folder_var.set(path)

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.output_dir_var.set(path)
            self.output_mode_var.set("outdir")

    def _on_drop(self, event) -> None:
        paths = self.root.tk.splitlist(event.data)
        if paths:
            self.folder_var.set(paths[0])

    def _pick_colour(self, var: tk.StringVar) -> None:
        try:
            initial = _ass_to_hex_rgb(var.get())
        except ValueError:
            initial = "#ffffff"
        rgb, _ = colorchooser.askcolor(color=initial)
        if rgb is None:
            return
        try:
            alpha = parse_ass_color(var.get()).a
        except ValueError:
            alpha = 0
        r, g, b = (int(round(x)) for x in rgb)
        var.set(f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}")

    def _refresh_swatches(self) -> None:
        for label, var in self.colour_vars.items():
            try:
                self._swatches[label].configure(
                    background=_ass_to_hex_rgb(var.get()))
            except (ValueError, tk.TclError):
                pass  # 使用者輸入到一半,先不更新色塊

    # ---------- Profile 欄位 <-> 物件 ----------
    def _collect_profile(self) -> Profile:
        style = TargetStyle(
            fontname=self.fontname_var.get().strip(),
            fontsize=float(self.fontsize_var.get()),
            bold=self.bold_var.get(),
            italic=self.italic_var.get(),
            primary_colour=self.colour_vars["主色"].get().strip(),
            outline_colour=self.colour_vars["外框色"].get().strip(),
            back_colour=self.colour_vars["陰影色"].get().strip(),
            outline=float(self.outline_var.get()),
            shadow=float(self.shadow_var.get()),
            alignment=int(self.alignment_var.get()),
            margin_l=int(self.margin_l_var.get()),
            margin_r=int(self.margin_r_var.get()),
            margin_v=int(self.margin_v_var.get()),
        )
        for colour in (style.primary_colour, style.outline_colour,
                       style.back_colour):
            parse_ass_color(colour)
        if not style.fontname:
            raise ValueError("字型名稱不可為空")
        names = [n.strip() for n in self.target_styles_var.get().split(",")
                 if n.strip()]
        if not names:
            raise ValueError("目標 Style 名稱不可為空")
        return Profile(
            profile_name=self.profile_name_var.get().strip() or "未命名",
            target_style_names=names,
            base_width=int(self.base_w_var.get()),
            base_height=int(self.base_h_var.get()),
            style=style,
        )

    def _apply_profile_to_fields(self, profile: Profile) -> None:
        self.profile_name_var.set(profile.profile_name)
        self.target_styles_var.set(", ".join(profile.target_style_names))
        self.base_w_var.set(str(profile.base_width))
        self.base_h_var.set(str(profile.base_height))
        t = profile.style
        self.fontname_var.set(t.fontname)
        self.fontsize_var.set(str(t.fontsize))
        self.bold_var.set(t.bold)
        self.italic_var.set(t.italic)
        self.colour_vars["主色"].set(t.primary_colour)
        self.colour_vars["外框色"].set(t.outline_colour)
        self.colour_vars["陰影色"].set(t.back_colour)
        self.outline_var.set(str(t.outline))
        self.shadow_var.set(str(t.shadow))
        self.alignment_var.set(str(t.alignment))
        self.margin_l_var.set(str(t.margin_l))
        self.margin_r_var.set(str(t.margin_r))
        self.margin_v_var.set(str(t.margin_v))

    def _load_profile(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            self._apply_profile_to_fields(load_profile(Path(path)))
        except Exception as exc:
            messagebox.showerror("載入失敗", str(exc))
            return
        self._log(f"已載入設定檔: {path}")

    def _save_profile(self) -> None:
        try:
            profile = self._collect_profile()
        except ValueError as exc:
            messagebox.showerror("欄位錯誤", str(exc))
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        save_profile(profile, Path(path))
        self._log(f"已儲存設定檔: {path}")

    # ---------- Log ----------
    def _log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll_log(self) -> None:
        try:
            while True:
                self._log(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log)

    # ---------- 掃描 ----------
    def _start_scan(self) -> None:
        folder = self.folder_var.get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showerror("錯誤", "請先選擇有效的輸入資料夾")
            return
        self.scan_button.configure(state="disabled")
        self.run_button.configure(state="disabled")
        threading.Thread(target=self._scan_worker, args=(Path(folder),),
                         daemon=True).start()

    def _scan_worker(self, folder: Path) -> None:
        try:
            scan = scan_folder(folder)
        except Exception as exc:
            self.log_queue.put(f"掃描失敗: {exc}")
            self.root.after(0, lambda: self.scan_button.configure(state="normal"))
            return
        self.scan_result = scan
        for warning in scan.warnings:
            self.log_queue.put(f"警告: {warning}")
        self.log_queue.put(f"=== 掃描結果: 共 {len(scan.matches)} 個字幕檔 ===")
        for m in scan.matches:
            label = _STATUS_LABELS.get(m.status, m.status)
            ep = f"ep{m.episode:02d}" if m.episode is not None else "ep??"
            video = m.video_path.name if m.video_path else "-"
            res = (f" ({m.video_resolution[0]}x{m.video_resolution[1]})"
                   if m.video_resolution else "")
            self.log_queue.put(
                f"[{label}] {ep}  {m.sub_path.name}  <->  {video}{res}")
        if scan.matches:
            self.log_queue.put("請確認以上配對無誤後,按「開始套用樣式」")
        self.root.after(0, self._after_scan)

    def _after_scan(self) -> None:
        self.scan_button.configure(state="normal")
        if self.scan_result is not None and self.scan_result.matches:
            self.run_button.configure(state="normal")

    # ---------- 執行 ----------
    def _start_run(self) -> None:
        if self.scan_result is None:
            return
        try:
            profile = self._collect_profile()
        except ValueError as exc:
            messagebox.showerror("欄位錯誤", str(exc))
            return
        output_dir = None
        if self.output_mode_var.get() == "outdir":
            out = self.output_dir_var.get().strip()
            if not out:
                messagebox.showerror("錯誤", "請先選擇輸出資料夾")
                return
            output_dir = Path(out)
        self.scan_button.configure(state="disabled")
        self.run_button.configure(state="disabled")
        threading.Thread(target=self._run_worker,
                         args=(profile, output_dir), daemon=True).start()

    def _run_worker(self, profile: Profile, output_dir) -> None:
        def on_progress(report) -> None:
            label = _REPORT_LABELS.get(report.status, report.status)
            self.log_queue.put(f"[{label}] {report.sub_path.name}")
            for message in report.messages:
                self.log_queue.put(f"    {message}")

        reports = run_batch(self.scan_result, profile, output_dir,
                            progress_cb=on_progress)
        ok = sum(1 for r in reports if r.status == "ok")
        skipped = sum(1 for r in reports if r.status == "skipped")
        errors = sum(1 for r in reports if r.status == "error")
        self.log_queue.put(
            f"=== 全部完成: 成功 {ok},跳過 {skipped},錯誤 {errors} ===")
        self.root.after(0, self._after_run)

    def _after_run(self) -> None:
        self.scan_button.configure(state="normal")
        self.run_button.configure(state="normal")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
```

建立 `ass_style_tool/__main__.py`:

```python
from .gui import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: import 檢查(不開視窗)**

Run: `python -c "import ass_style_tool.gui; print('gui import ok')"`
Expected: 輸出 `gui import ok`,無例外

- [ ] **Step 3: 手動冒煙測試**

Run: `python -m ass_style_tool`

人工確認以下項目(逐項看過):
1. 視窗開啟,標題「ASS 字幕樣式批次工具」,所有欄位顯示預設值
2. 若系統沒有 ffprobe,log 出現提示行
3. 「瀏覽...」能選資料夾;若安裝了 tkinterdnd2,拖放資料夾到輸入框能填入路徑
4. 三個「選色...」按鈕開啟色彩選擇器,選色後色碼欄位與色塊同步更新
5. 「另存設定檔...」能存出 JSON;「載入設定檔...」讀回後欄位正確還原
6. 準備一個測試資料夾(放 1-2 個 `.ass` 檔,可用 tests 的 SAMPLE_ASS 內容),按「掃描並預覽配對」,log 列出配對結果,「開始套用樣式」變為可按
7. 按「開始套用樣式」(原地覆蓋模式),log 顯示每檔結果與總結;確認 `.bak` 備份存在、字幕檔 Default style 已改
8. 切換「輸出到新資料夾」模式再跑一次,確認新資料夾有輸出、原檔未動

- [ ] **Step 4: 跑全部自動化測試**

Run: `python -m pytest tests -v`
Expected: 58 passed

- [ ] **Step 5: Commit**

```powershell
git add ass_style_tool/gui.py ass_style_tool/__main__.py
git commit -m "feat: add tkinter GUI with drag-and-drop, style editor, scan preview and batch run"
```

---

### Task 7: 範例設定檔與 README

**Files:**
- Create: `profiles/sample-1080p.json`
- Create: `README.md`

**Interfaces:**
- Consumes: Task 1 的 Profile JSON 格式
- Produces: 使用者文件與可直接載入的範例設定檔

- [ ] **Step 1: 建立範例設定檔**

建立 `profiles/sample-1080p.json`:

```json
{
  "profile_name": "範例:1080p 一般對話字幕",
  "target_style_names": ["Default"],
  "base_resolution": { "width": 1920, "height": 1080 },
  "style": {
    "fontname": "思源黑體 CN",
    "fontsize": 72.0,
    "bold": false,
    "italic": false,
    "primary_colour": "&H00FFFFFF",
    "outline_colour": "&H00000000",
    "back_colour": "&H00000000",
    "outline": 3.6,
    "shadow": 1.0,
    "alignment": 2,
    "margin_l": 20,
    "margin_r": 20,
    "margin_v": 24
  }
}
```

- [ ] **Step 2: 驗證範例檔能被 load_profile 讀取**

Run: `python -c "from ass_style_tool.profile import load_profile; p = load_profile('profiles/sample-1080p.json'); print(p.profile_name)"`
Expected: 輸出 `範例:1080p 一般對話字幕`

- [ ] **Step 3: 建立 README.md**

建立 `README.md`:

```markdown
# ASS 字幕樣式批次工具

批次把整季動畫的 ASS/SSA 字幕檔中指定的 Style(例如 `Default` 一般對話)
統一改成你設定的字型、大小、顏色、外框、陰影、位置,並依各集字幕檔的
PlayResX/PlayResY 按比例縮放數值,讓不同解析度片源的視覺大小一致。
其他 Style(OP/ED/特效/標示)完全不受影響。

## 安裝

需要 Python 3.9+。

```powershell
python -m pip install -r requirements.txt
```

選配:

- `tkinterdnd2` — 支援拖放資料夾(未安裝時退回「瀏覽資料夾」按鈕)
- `ffmpeg/ffprobe`(需在 PATH 中)— 掃描預覽時顯示影片實際解析度,
  並在 PlayRes 長寬比與影片不符時發出警告;不影響樣式套用本身

## 使用

```powershell
python -m ass_style_tool
```

1. 選擇(或拖放)放字幕/影片的資料夾
2. 編輯目標樣式,或「載入設定檔」(見 `profiles/sample-1080p.json`)
3. 選擇輸出模式:原地覆蓋(自動備份 `.bak`)或輸出到新資料夾
4. 按「掃描並預覽配對」,確認每個字幕檔的集數與影片配對正確
5. 按「開始套用樣式」,在 log 檢視每檔結果與總結

## 縮放規則

樣式數值以設定檔的「基準解析度」為基準;每個字幕檔依自己的
PlayResX/PlayResY 按比例換算(缺一個依 4:3 推導、全缺依規範用 384x288)。
工具**不會**改寫 PlayResX/PlayResY/ScaledBorderAndShadow 標頭,
也不會動到未列在「目標 Style 名稱」中的樣式。

## 開發

```powershell
python -m pytest tests -v
```

設計文件:`docs/superpowers/specs/2026-07-08-ass-style-batch-tool-design.md`
```

- [ ] **Step 4: 最終全套測試**

Run: `python -m pytest tests -v`
Expected: 58 passed

- [ ] **Step 5: Commit**

```powershell
git add profiles/sample-1080p.json README.md
git commit -m "docs: add sample profile and README"
```
