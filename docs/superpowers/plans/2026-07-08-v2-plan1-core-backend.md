# v2 Plan 1 — 核心後端模組(tools / mkv_io / preview)Implementation Plan

**Goal:** 建立 v2 的三個純邏輯後端模組——外部工具偵測(tools)、MKV 字幕軌列舉/抽取/重封裝(mkv_io)、預覽暫存字幕產生(preview)——全部可用 pytest 單元測試,為之後的 PySide6 GUI 計畫提供地基。

**Architecture:** 三個新模組加在既有 `ass_style_tool/` 套件下,不動 v1 任何核心模組。外部程序(ffprobe/mkvmerge/mkvextract)一律以 `subprocess` 呼叫,測試時 monkeypatch。命令列組裝與輸出解析拆成純函式獨立測試;實際跑程序的薄包裝不強制單元測試。

**Tech Stack:** Python 3.13、pysubs2、pytest。本計畫不引入 PySide6/mpv(留給 Plan 2)。

**Spec:** `docs/superpowers/specs/2026-07-08-ass-style-tool-v2-design.md`

## Global Constraints

- 工作目錄/repo root:專案根目錄,git branch 由執行者自行建立
- **環境重點**:這台機器 `python` 是壞的 Windows Store stub,一律用 `py`:`py -m pytest tests -v`
- Python 3.9+ 相容;每個新模組頂端加 `from __future__ import annotations`
- 不動 v1 核心模組(profile/resolution/ass_style/episode_match/batch_runner)與其 62 個既有測試
- 所有外部程序呼叫用 `subprocess.run`,`capture_output=True, text=True`,並包 try/except `(OSError, subprocess.TimeoutExpired)` — 缺工具或逾時不可拋出未處理例外
- 測試指令:`py -m pytest tests -v`(從 repo root)
- Commit 訊息用 conventional commits(`feat:`/`test:`/`docs:`)

### v1 既有介面(本計畫會用到,已實作且測試過)

- `ass_style_tool.ass_style.load_subs(path) -> pysubs2.SSAFile`
- `ass_style_tool.ass_style.save_subs(subs, path) -> None`(輸出 UTF-8 with BOM)
- `ass_style_tool.ass_style.apply_profile(subs, profile) -> list[str]`(就地改指定 Style,回傳實際改到的名稱;不動標頭)
- `ass_style_tool.profile.Profile`(欄位 profile_name, target_style_names, base_width, base_height, style)
- 測試輔助:`tests.test_profile.make_profile(**overrides)`、`tests.test_ass_style.SAMPLE_ASS`

## File Structure

```
ass_style_tool/
├── tools.py     # find_tool + ffprobe/mkvmerge/mkvextract 路徑取得
├── mkv_io.py    # SubtitleTrack、list_ass_tracks、extract_track、build_remux_command、parse_progress、remux
└── preview.py   # render_preview_ass
tests/
├── test_tools.py
├── test_mkv_io.py
└── test_preview.py
tests/fixtures/
└── mkvmerge_identify_sample.json   # 真實 mkvmerge -J 輸出樣本(裁剪)
```

---

### Task 1: tools.py — 外部工具偵測

**Files:**
- Create: `ass_style_tool/tools.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: 無
- Produces:
  - `find_tool(exe_names: list[str], extra_dirs: list[Path] | None = None) -> Path | None` — 依序:對每個候選名 `shutil.which` → 掃 `extra_dirs` 內是否有該檔 → 都沒有回 `None`
  - `bundled_tools_dir() -> Path` — 回傳套件旁的 `tools/` 目錄路徑(`Path(__file__).parent / "tools"`,不保證存在)
  - `mkvtoolnix_common_dirs() -> list[Path]` — 回傳 MKVToolNix 常見安裝目錄清單(存在與否不保證)
  - `ffprobe_path() -> Path | None`、`mkvmerge_path() -> Path | None`、`mkvextract_path() -> Path | None` — 各自用 `find_tool` 組合 PATH + 常見目錄 + bundled
  - `ToolStatus` dataclass:`name: str, path: Path | None`;property `available: bool`(= path is not None)
  - `tool_statuses() -> list[ToolStatus]` — 回傳 ffprobe/mkvmerge/mkvextract 三者狀態

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_tools.py`:

```python
from __future__ import annotations

from pathlib import Path

from ass_style_tool.tools import (ToolStatus, find_tool, ffprobe_path,
                                  mkvmerge_path, tool_statuses)


def test_find_tool_uses_which_first(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.tools.shutil.which",
        lambda name: r"C:\sys\mkvmerge.exe" if name == "mkvmerge" else None,
    )
    result = find_tool(["mkvmerge"])
    assert result == Path(r"C:\sys\mkvmerge.exe")


def test_find_tool_tries_multiple_names(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.tools.shutil.which",
        lambda name: r"C:\sys\ffprobe.exe" if name == "ffprobe" else None,
    )
    # 第一個候選名找不到,第二個找到
    assert find_tool(["ffprobe.exe", "ffprobe"]) == Path(r"C:\sys\ffprobe.exe")


def test_find_tool_falls_back_to_extra_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr("ass_style_tool.tools.shutil.which", lambda name: None)
    exe = tmp_path / "mkvmerge.exe"
    exe.write_bytes(b"")
    assert find_tool(["mkvmerge.exe"], extra_dirs=[tmp_path]) == exe


def test_find_tool_returns_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("ass_style_tool.tools.shutil.which", lambda name: None)
    assert find_tool(["nope.exe"], extra_dirs=[tmp_path]) is None


def test_ffprobe_path_found(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.tools.shutil.which",
        lambda name: r"C:\sys\ffprobe.exe" if name.startswith("ffprobe") else None,
    )
    assert ffprobe_path() == Path(r"C:\sys\ffprobe.exe")


def test_mkvmerge_path_none(monkeypatch):
    monkeypatch.setattr("ass_style_tool.tools.shutil.which", lambda name: None)
    monkeypatch.setattr(
        "ass_style_tool.tools.mkvtoolnix_common_dirs", lambda: []
    )
    monkeypatch.setattr(
        "ass_style_tool.tools.bundled_tools_dir", lambda: Path(r"C:\nonexistent")
    )
    assert mkvmerge_path() is None


def test_tool_status_available():
    assert ToolStatus("ffprobe", Path(r"C:\x.exe")).available is True
    assert ToolStatus("mkvmerge", None).available is False


def test_tool_statuses_reports_three(monkeypatch):
    monkeypatch.setattr("ass_style_tool.tools.shutil.which", lambda name: None)
    monkeypatch.setattr("ass_style_tool.tools.mkvtoolnix_common_dirs", lambda: [])
    monkeypatch.setattr(
        "ass_style_tool.tools.bundled_tools_dir", lambda: Path(r"C:\nonexistent")
    )
    statuses = tool_statuses()
    assert {s.name for s in statuses} == {"ffprobe", "mkvmerge", "mkvextract"}
    assert all(s.available is False for s in statuses)
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.tools'`

- [ ] **Step 3: 實作 tools.py**

建立 `ass_style_tool/tools.py`:

```python
"""外部工具(ffprobe/mkvmerge/mkvextract)的偵測:PATH → 常見目錄 → 內建 tools/。"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


def bundled_tools_dir() -> Path:
    """安裝程式會把工具放在套件旁的 tools/ 目錄(不保證存在)。"""
    return Path(__file__).parent / "tools"


def mkvtoolnix_common_dirs() -> List[Path]:
    """MKVToolNix 常見安裝目錄(存在與否不保證)。"""
    return [
        Path(r"C:\Program Files\MKVToolNix"),
        Path(r"C:\Program Files (x86)\MKVToolNix"),
    ]


def find_tool(
    exe_names: List[str], extra_dirs: Optional[List[Path]] = None
) -> Optional[Path]:
    """依序:PATH(shutil.which)→ extra_dirs 內找同名檔 → None。"""
    for name in exe_names:
        found = shutil.which(name)
        if found:
            return Path(found)
    for directory in extra_dirs or []:
        for name in exe_names:
            candidate = Path(directory) / name
            if candidate.exists():
                return candidate
    return None


def ffprobe_path() -> Optional[Path]:
    return find_tool(["ffprobe.exe", "ffprobe"], [bundled_tools_dir()])


def mkvmerge_path() -> Optional[Path]:
    dirs = mkvtoolnix_common_dirs() + [bundled_tools_dir()]
    return find_tool(["mkvmerge.exe", "mkvmerge"], dirs)


def mkvextract_path() -> Optional[Path]:
    dirs = mkvtoolnix_common_dirs() + [bundled_tools_dir()]
    return find_tool(["mkvextract.exe", "mkvextract"], dirs)


@dataclass
class ToolStatus:
    name: str
    path: Optional[Path]

    @property
    def available(self) -> bool:
        return self.path is not None


def tool_statuses() -> List[ToolStatus]:
    return [
        ToolStatus("ffprobe", ffprobe_path()),
        ToolStatus("mkvmerge", mkvmerge_path()),
        ToolStatus("mkvextract", mkvextract_path()),
    ]
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_tools.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```powershell
git add ass_style_tool/tools.py tests/test_tools.py
git commit -m "feat: add external tool detection (ffprobe/mkvmerge/mkvextract)"
```

---

### Task 2: mkv_io.py — 字幕軌列舉(mkvmerge -J 解析)

**Files:**
- Create: `ass_style_tool/mkv_io.py`
- Create: `tests/fixtures/mkvmerge_identify_sample.json`
- Test: `tests/test_mkv_io.py`

**Interfaces:**
- Consumes: `tools.mkvmerge_path`(執行期用;解析函式不依賴)
- Produces:
  - `SubtitleTrack` dataclass:`track_id: int, codec_id: str, language: str, track_name: str, default: bool, forced: bool`
  - `parse_ass_tracks(identify_json: dict) -> list[SubtitleTrack]` — 從 `mkvmerge -J` 的 dict 過濾出 codec_id 為 `S_TEXT/ASS` 或 `S_TEXT/SSA` 的字幕軌(純函式)
  - `list_ass_tracks(mkv_path: Path, mkvmerge: Path) -> list[SubtitleTrack]` — 跑 `mkvmerge -J`,解析失敗/程序失敗回 `[]`

- [ ] **Step 1: 建立 fixture 樣本**

建立 `tests/fixtures/mkvmerge_identify_sample.json`(裁剪自真實 `mkvmerge -J` 輸出,含視訊/音訊/兩條 ASS 字幕/一條 SRT 字幕/字型附件):

```json
{
  "attachments": [
    { "id": 1, "content_type": "application/x-truetype-font", "file_name": "font.ttf" }
  ],
  "chapters": [ { "num_entries": 12 } ],
  "container": { "type": "Matroska" },
  "tracks": [
    {
      "id": 0, "type": "video", "codec": "HEVC/H.265",
      "properties": { "codec_id": "V_MPEGH/ISO/HEVC", "language": "und" }
    },
    {
      "id": 1, "type": "audio", "codec": "FLAC",
      "properties": { "codec_id": "A_FLAC", "language": "jpn" }
    },
    {
      "id": 2, "type": "subtitles", "codec": "SubStationAlpha",
      "properties": {
        "codec_id": "S_TEXT/ASS", "language": "chi",
        "track_name": "繁體中文", "default_track": true, "forced_track": false
      }
    },
    {
      "id": 3, "type": "subtitles", "codec": "SubStationAlpha",
      "properties": {
        "codec_id": "S_TEXT/ASS", "language": "chi",
        "track_name": "簡體中文", "default_track": false, "forced_track": false
      }
    },
    {
      "id": 4, "type": "subtitles", "codec": "SubRip/SRT",
      "properties": {
        "codec_id": "S_TEXT/UTF8", "language": "eng",
        "track_name": "English", "default_track": false, "forced_track": false
      }
    }
  ]
}
```

- [ ] **Step 2: 寫失敗測試**

建立 `tests/test_mkv_io.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from ass_style_tool.mkv_io import (SubtitleTrack, list_ass_tracks,
                                   parse_ass_tracks)

FIXTURE = Path(__file__).parent / "fixtures" / "mkvmerge_identify_sample.json"


def _sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_filters_only_ass_tracks():
    tracks = parse_ass_tracks(_sample())
    assert [t.track_id for t in tracks] == [2, 3]  # SRT(4)被排除


def test_parse_reads_track_metadata():
    t = parse_ass_tracks(_sample())[0]
    assert t.track_id == 2
    assert t.codec_id == "S_TEXT/ASS"
    assert t.language == "chi"
    assert t.track_name == "繁體中文"
    assert t.default is True
    assert t.forced is False


def test_parse_includes_ssa():
    data = {"tracks": [{
        "id": 5, "type": "subtitles",
        "properties": {"codec_id": "S_TEXT/SSA", "language": "und"}
    }]}
    tracks = parse_ass_tracks(data)
    assert len(tracks) == 1
    assert tracks[0].codec_id == "S_TEXT/SSA"


def test_parse_missing_optional_fields_defaults():
    data = {"tracks": [{
        "id": 6, "type": "subtitles",
        "properties": {"codec_id": "S_TEXT/ASS"}
    }]}
    t = parse_ass_tracks(data)[0]
    assert t.language == "und"      # 缺 language 預設 und
    assert t.track_name == ""       # 缺 track_name 預設空字串
    assert t.default is False
    assert t.forced is False


def test_parse_empty_when_no_tracks_key():
    assert parse_ass_tracks({}) == []


class FakeCompleted:
    def __init__(self, returncode: int, stdout: str):
        self.returncode = returncode
        self.stdout = stdout


def test_list_ass_tracks_runs_mkvmerge(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeCompleted(0, FIXTURE.read_text(encoding="utf-8"))

    monkeypatch.setattr("ass_style_tool.mkv_io.subprocess.run", fake_run)
    tracks = list_ass_tracks(Path("show.mkv"), Path(r"C:\mkvmerge.exe"))
    assert [t.track_id for t in tracks] == [2, 3]
    assert captured["cmd"][0] == r"C:\mkvmerge.exe"
    assert "-J" in captured["cmd"]
    assert captured["cmd"][-1] == "show.mkv"


def test_list_ass_tracks_nonzero_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.mkv_io.subprocess.run",
        lambda cmd, **k: FakeCompleted(2, ""),
    )
    assert list_ass_tracks(Path("x.mkv"), Path("mkvmerge")) == []


def test_list_ass_tracks_oserror_returns_empty(monkeypatch):
    def boom(cmd, **k):
        raise OSError("not found")

    monkeypatch.setattr("ass_style_tool.mkv_io.subprocess.run", boom)
    assert list_ass_tracks(Path("x.mkv"), Path("mkvmerge")) == []


def test_list_ass_tracks_bad_json_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.mkv_io.subprocess.run",
        lambda cmd, **k: FakeCompleted(0, "not json"),
    )
    assert list_ass_tracks(Path("x.mkv"), Path("mkvmerge")) == []
```

- [ ] **Step 3: 執行測試,確認失敗**

Run: `py -m pytest tests/test_mkv_io.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.mkv_io'`

- [ ] **Step 4: 實作 mkv_io.py(本任務範圍)**

建立 `ass_style_tool/mkv_io.py`:

```python
"""MKV 字幕軌的列舉、抽取與重封裝(呼叫 mkvmerge/mkvextract)。"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List

_ASS_CODEC_IDS = {"S_TEXT/ASS", "S_TEXT/SSA"}


@dataclass
class SubtitleTrack:
    track_id: int
    codec_id: str
    language: str
    track_name: str
    default: bool
    forced: bool


def parse_ass_tracks(identify_json: dict) -> List[SubtitleTrack]:
    """從 mkvmerge -J 的 dict 取出 ASS/SSA 字幕軌。"""
    result: List[SubtitleTrack] = []
    for track in identify_json.get("tracks", []):
        if track.get("type") != "subtitles":
            continue
        props = track.get("properties", {})
        codec_id = props.get("codec_id", "")
        if codec_id not in _ASS_CODEC_IDS:
            continue
        result.append(SubtitleTrack(
            track_id=int(track["id"]),
            codec_id=codec_id,
            language=props.get("language", "und"),
            track_name=props.get("track_name", ""),
            default=bool(props.get("default_track", False)),
            forced=bool(props.get("forced_track", False)),
        ))
    return result


def list_ass_tracks(mkv_path: Path, mkvmerge: Path) -> List[SubtitleTrack]:
    """跑 mkvmerge -J 列舉 ASS 字幕軌;任何失敗回 []。"""
    cmd = [str(mkvmerge), "-J", str(mkv_path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        return []
    return parse_ass_tracks(data)
```

- [ ] **Step 5: 執行測試,確認通過**

Run: `py -m pytest tests/test_mkv_io.py -v`
Expected: 9 passed

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/mkv_io.py tests/fixtures/mkvmerge_identify_sample.json tests/test_mkv_io.py
git commit -m "feat: add MKV ASS subtitle track enumeration via mkvmerge -J"
```

---

### Task 3: mkv_io.py — 抽取、重封裝命令組裝、進度解析

**Files:**
- Modify: `ass_style_tool/mkv_io.py`(新增函式)
- Test: `tests/test_mkv_io.py`(新增測試)

**Interfaces:**
- Consumes: 本檔的 `SubtitleTrack`
- Produces:
  - `Replacement` dataclass:`track: SubtitleTrack, styled_path: Path`
  - `build_extract_command(mkv_path: Path, track_id: int, out_path: Path, mkvextract: Path) -> list[str]` — 純函式
  - `build_remux_command(mkv_path: Path, out_path: Path, replacements: list[Replacement], mkvmerge: Path) -> list[str]` — 純函式;`replacements` 為空丟 `ValueError`
  - `parse_progress(line: str) -> int | None` — 解析 mkvmerge 的 `Progress: NN%`,無則回 `None`
  - `extract_track(mkv_path, track_id, out_path, mkvextract) -> bool` — 跑抽取,成功回 True
  - `remux(mkv_path, out_path, replacements, mkvmerge, progress_cb=None) -> bool` — 跑重封裝,退出碼 0 或 1(警告)視為成功

- [ ] **Step 1: 寫失敗測試(附加到 tests/test_mkv_io.py 末尾)**

```python
from ass_style_tool.mkv_io import (Replacement, build_extract_command,
                                   build_remux_command, parse_progress)


def _track(tid, lang="chi", name="繁中", default=True, forced=False):
    return SubtitleTrack(tid, "S_TEXT/ASS", lang, name, default, forced)


def test_build_extract_command():
    cmd = build_extract_command(
        Path("show.mkv"), 2, Path("out.ass"), Path(r"C:\mkvextract.exe"))
    assert cmd == [r"C:\mkvextract.exe", "show.mkv", "tracks", "2:out.ass"]


def test_build_remux_excludes_replaced_subtitle_ids():
    cmd = build_remux_command(
        Path("show.mkv"), Path("out.mkv"),
        [Replacement(_track(2), Path("styled2.ass"))],
        Path(r"C:\mkvmerge.exe"),
    )
    # 原檔只排除被替換的字幕軌 2
    i = cmd.index("--subtitle-tracks")
    assert cmd[i + 1] == "!2"
    # 原檔在被替換 .ass 之前
    assert cmd.index("show.mkv") < cmd.index("styled2.ass")


def test_build_remux_restores_track_flags():
    cmd = build_remux_command(
        Path("s.mkv"), Path("o.mkv"),
        [Replacement(_track(2, lang="chi", name="繁中", default=True, forced=False),
                     Path("styled.ass"))],
        Path("mkvmerge"),
    )
    joined = " ".join(cmd)
    assert "--language 0:chi" in joined
    assert "--track-name 0:繁中" in joined
    assert "--default-track 0:yes" in joined
    assert "--forced-track 0:no" in joined


def test_build_remux_multiple_replacements_exclude_list():
    cmd = build_remux_command(
        Path("s.mkv"), Path("o.mkv"),
        [Replacement(_track(2), Path("a.ass")),
         Replacement(_track(3), Path("b.ass"))],
        Path("mkvmerge"),
    )
    i = cmd.index("--subtitle-tracks")
    assert cmd[i + 1] == "!2,3"


def test_build_remux_empty_replacements_raises():
    import pytest
    with pytest.raises(ValueError):
        build_remux_command(Path("s.mkv"), Path("o.mkv"), [], Path("mkvmerge"))


def test_build_remux_omits_empty_track_name():
    cmd = build_remux_command(
        Path("s.mkv"), Path("o.mkv"),
        [Replacement(_track(2, name=""), Path("a.ass"))],
        Path("mkvmerge"),
    )
    assert "--track-name" not in cmd


def test_parse_progress():
    assert parse_progress("Progress: 42%") == 42
    assert parse_progress("Progress: 100%") == 100


def test_parse_progress_none():
    assert parse_progress("Multiplexing...") is None
    assert parse_progress("") is None
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_mkv_io.py -v`
Expected: FAIL — `ImportError: cannot import name 'Replacement'`

- [ ] **Step 3: 實作(附加到 ass_style_tool/mkv_io.py)**

在檔案頂端的 import 區加入 `import re` 與 `Callable, Optional`:

```python
import re
from typing import Callable, List, Optional
```

在檔案末尾附加:

```python
@dataclass
class Replacement:
    track: SubtitleTrack
    styled_path: Path


def build_extract_command(
    mkv_path: Path, track_id: int, out_path: Path, mkvextract: Path
) -> List[str]:
    return [str(mkvextract), str(mkv_path), "tracks", f"{track_id}:{out_path}"]


def build_remux_command(
    mkv_path: Path,
    out_path: Path,
    replacements: List[Replacement],
    mkvmerge: Path,
) -> List[str]:
    if not replacements:
        raise ValueError("replacements 不可為空")
    excluded = ",".join(str(r.track.track_id) for r in replacements)
    cmd: List[str] = [str(mkvmerge), "-o", str(out_path)]
    # 原檔:只丟掉被替換的字幕軌,其餘(含未勾字幕、視訊、音訊、章節、附件)保留
    cmd += ["--subtitle-tracks", f"!{excluded}", str(mkv_path)]
    # 每個改後 .ass 以附加軌加入,還原原軌旗標(檔內為 track 0)
    for r in replacements:
        t = r.track
        cmd += ["--language", f"0:{t.language}"]
        if t.track_name:
            cmd += ["--track-name", f"0:{t.track_name}"]
        cmd += ["--default-track", f"0:{'yes' if t.default else 'no'}"]
        cmd += ["--forced-track", f"0:{'yes' if t.forced else 'no'}"]
        cmd.append(str(r.styled_path))
    return cmd


_PROGRESS_RE = re.compile(r"Progress:\s*(\d{1,3})%")


def parse_progress(line: str) -> Optional[int]:
    match = _PROGRESS_RE.search(line)
    return int(match.group(1)) if match else None


def extract_track(
    mkv_path: Path, track_id: int, out_path: Path, mkvextract: Path
) -> bool:
    cmd = build_extract_command(mkv_path, track_id, out_path, mkvextract)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def remux(
    mkv_path: Path,
    out_path: Path,
    replacements: List[Replacement],
    mkvmerge: Path,
    progress_cb: Optional[Callable[[int], None]] = None,
) -> bool:
    """重封裝;mkvmerge 退出碼 0(成功)或 1(警告)視為成功。"""
    cmd = build_remux_command(mkv_path, out_path, replacements, mkvmerge)
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
    except OSError:
        return False
    assert proc.stdout is not None
    for line in proc.stdout:
        if progress_cb is not None:
            pct = parse_progress(line)
            if pct is not None:
                progress_cb(pct)
    proc.wait()
    return proc.returncode in (0, 1)
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_mkv_io.py -v`
Expected: 17 passed(Task 2 的 9 + 本任務 8)

- [ ] **Step 5: Commit**

```powershell
git add ass_style_tool/mkv_io.py tests/test_mkv_io.py
git commit -m "feat: add MKV track extract, remux command builder and progress parsing"
```

---

### Task 4: preview.py — 預覽暫存字幕產生

**Files:**
- Create: `ass_style_tool/preview.py`
- Test: `tests/test_preview.py`

**Interfaces:**
- Consumes: `ass_style.load_subs / save_subs / apply_profile`、`profile.Profile`
- Produces:
  - `render_preview_ass(source_ass_path: Path, profile: Profile, out_path: Path) -> list[str]` — 讀來源 .ass、套用 profile(縮放規則同批次)、寫出到 out_path(UTF-8 BOM);回傳實際改到的 Style 名稱;不動來源檔

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_preview.py`:

```python
from __future__ import annotations

from pathlib import Path

import pysubs2

from ass_style_tool.preview import render_preview_ass
from tests.test_ass_style import SAMPLE_ASS
from tests.test_profile import make_profile


def _write_source(tmp_path: Path) -> Path:
    src = tmp_path / "source.ass"
    src.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    return src


def test_render_preview_writes_styled_copy(tmp_path):
    src = _write_source(tmp_path)
    out = tmp_path / "preview.ass"
    modified = render_preview_ass(src, make_profile(), out)
    assert modified == ["Default"]
    subs = pysubs2.SSAFile.from_string(out.read_text(encoding="utf-8-sig"))
    assert subs.styles["Default"].fontname == "思源黑體 CN"
    assert subs.styles["Default"].fontsize == 48  # 720p 縮放,同批次規則


def test_render_preview_does_not_touch_source(tmp_path):
    src = _write_source(tmp_path)
    original = src.read_bytes()
    render_preview_ass(src, make_profile(), tmp_path / "preview.ass")
    assert src.read_bytes() == original


def test_render_preview_output_has_bom(tmp_path):
    src = _write_source(tmp_path)
    out = tmp_path / "preview.ass"
    render_preview_ass(src, make_profile(), out)
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_preview.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.preview'`

- [ ] **Step 3: 實作 preview.py**

建立 `ass_style_tool/preview.py`:

```python
"""預覽用暫存字幕產生:套用目前樣式到來源字幕的複本,供 mpv 重載。"""
from __future__ import annotations

from pathlib import Path
from typing import List

from .ass_style import apply_profile, load_subs, save_subs
from .profile import Profile


def render_preview_ass(
    source_ass_path: Path, profile: Profile, out_path: Path
) -> List[str]:
    """讀來源 .ass、套用 profile(縮放規則與批次一致)、寫到 out_path。

    來源檔不被修改(load_subs 每次從磁碟讀新的物件)。回傳實際改到的 Style 名稱。
    """
    subs = load_subs(source_ass_path)
    modified = apply_profile(subs, profile)
    save_subs(subs, out_path)
    return modified
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_preview.py -v`
Expected: 3 passed

- [ ] **Step 5: 跑全部測試確認無回歸**

Run: `py -m pytest tests -v`
Expected: 90 passed(v1 的 62 + tools 8 + mkv_io 17 + preview 3)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/preview.py tests/test_preview.py
git commit -m "feat: add preview .ass renderer reusing batch scaling rules"
```

---

## 本計畫完成後

三個後端模組就緒(工具偵測、MKV 列舉/抽取/重封裝、預覽產生),全部有單元測試。接著是:

- **Plan 2 — PySide6 GUI**:深色分頁籤主視窗、樣式面板、檔案/字幕軌表格、內嵌 mpv 播放器、批次執行整合、7 項 UX 完善。消費本計畫的三個模組與 v1 核心模組。
- **Plan 3 — 打包發佈**:PyInstaller spec + Inno Setup 腳本、工具偵測式元件勾選、libmpv 內建。

這兩個計畫在本計畫合併後另行撰寫(GUI 與打包多為手動冒煙驗證,任務結構與 TDD 計畫不同)。
