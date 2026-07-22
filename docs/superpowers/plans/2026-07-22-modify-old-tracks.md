# Modify Old Tracks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓「封裝」分頁在封入外部 `.ass` 的同一次,依使用者設定修改來源 MKV 既有軌道(保留/丟棄、預設/forced、語言/軌名)。

**Architecture:** 五塊。`mkv_io` 加列出所有軌道;新純邏輯模組 `track_edit` 把「每軌設定」轉成 mkvmerge 旗標(含 per-video 過濾安全網);`mkv_mux` 的命令/管線接受這些旗標;新 `ModifyTracksDialog` 收集設定;封裝分頁加按鈕與掃描並把設定經 `MuxWorker` 傳進 `process_mux`。

**Tech Stack:** Python、PySide6(Qt Widgets)、mkvmerge(`-J` 列軌、封裝旗標)、pytest(offscreen)。

## Global Constraints

- 一律用 `py`,不要用 `python`。測試從 repo root:`py -m pytest tests -q`。目前基線 **326 passed**,實作後維持全綠(新增測試使總數上升)。
- 「定一次、依軌 ID 套用到全部」+ per-video 過濾:旗標只對「該影片實際存在的軌 ID」產生;`edits` 為空/None 時行為與現行完全相同(不掃描、不加旗標)。
- 屬性(default/forced/語言/軌名)只作用於**保留**的軌;丟棄的軌不產生屬性旗標。
- mkvmerge 輸入專屬旗標必須排在該輸入檔**前面**:`source_flags` 插在 `-o <out>` 與 `<video>` 之間。
- 沿用既有旗標拼法:`--default-track <id>:yes|no`、`--forced-track <id>:yes|no`、`--language <id>:<code>`、`--track-name <id>:<name>`;保留/丟棄用 `--video-tracks`/`--audio-tracks`/`--subtitle-tracks`(接保留 id)或 `--no-video`/`--no-audio`/`--no-subtitles`(全丟)。
- 掃軌失敗一律安全降級為「不做軌道修改、照常封裝」,不讓整批失敗。
- 沿用既有 subprocess 慣例:`text=True, encoding="utf-8", timeout, **no_window_kwargs()`。
- 不做:重新排序、章節/附件、清空既有軌名、全批一致性掃描(皆範圍外)。
- commit 訊息結尾加:`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- 環境:Bash 每次 `cd /c/Claude_code`。

---

## File Structure

- `ass_style_tool/mkv_io.py`(修改):加 `MediaTrack`、`parse_all_tracks`、`list_all_tracks`。
- `ass_style_tool/track_edit.py`(新增,純邏輯):`TrackEdit`、`build_source_track_flags`。
- `ass_style_tool/mkv_mux.py`(修改):`build_mux_command` 加 `source_flags`;`_default_mux`/`process_mux` 接旗標與 `edits`。
- `ass_style_tool/qt/modify_tracks_dialog.py`(新增):`ModifyTracksDialog`。
- `ass_style_tool/qt/mux_tab.py`(修改):按鈕、掃描、存設定、傳給 worker。
- `ass_style_tool/qt/batch_worker.py`(修改):`MuxWorker` 加 `edits` 轉交。
- 測試:`tests/test_mkv_io.py`、`tests/test_track_edit.py`(新)、`tests/test_mkv_mux.py`、`tests/test_modify_tracks_dialog.py`(新)、`tests/test_mux_tab.py`、`tests/test_mux_worker.py`。

---

### Task 1: `mkv_io` 列出所有軌道

**Files:**
- Modify: `ass_style_tool/mkv_io.py`
- Test: `tests/test_mkv_io.py`

**Interfaces:**
- Produces:
  - `MediaTrack` dataclass:`track_id: int, track_type: str, codec_id: str, language: str, track_name: str, default: bool, forced: bool`
  - `parse_all_tracks(identify_json: dict) -> List[MediaTrack]`
  - `list_all_tracks(mkv_path: Path, mkvmerge: Path) -> List[MediaTrack]`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_mkv_io.py` 末端加入(檔案已有 `FIXTURE`、`FakeCompleted`、`_sample()`):

```python
from ass_style_tool.mkv_io import MediaTrack, parse_all_tracks, list_all_tracks


def test_parse_all_tracks_all_types_sorted():
    tracks = parse_all_tracks(_sample())
    assert [t.track_id for t in tracks] == [0, 1, 2, 3, 4]
    assert [t.track_type for t in tracks] == [
        "video", "audio", "subtitles", "subtitles", "subtitles"]


def test_parse_all_tracks_reads_fields():
    audio = parse_all_tracks(_sample())[1]
    assert audio.track_type == "audio"
    assert audio.codec_id == "A_FLAC"
    assert audio.language == "jpn"


def test_list_all_tracks_runs_and_parses(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.mkv_io.subprocess.run",
        lambda cmd, **k: FakeCompleted(0, FIXTURE.read_text(encoding="utf-8")))
    tracks = list_all_tracks(Path("show.mkv"), Path("mkvmerge"))
    assert [t.track_id for t in tracks] == [0, 1, 2, 3, 4]


def test_list_all_tracks_nonzero_returns_empty(monkeypatch):
    monkeypatch.setattr("ass_style_tool.mkv_io.subprocess.run",
                        lambda cmd, **k: FakeCompleted(2, ""))
    assert list_all_tracks(Path("x.mkv"), Path("mkvmerge")) == []


def test_list_all_tracks_oserror_returns_empty(monkeypatch):
    def boom(cmd, **k):
        raise OSError("not found")
    monkeypatch.setattr("ass_style_tool.mkv_io.subprocess.run", boom)
    assert list_all_tracks(Path("x.mkv"), Path("mkvmerge")) == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_mkv_io.py -k "all_tracks" -q`
Expected: FAIL(`cannot import name 'MediaTrack'`)

- [ ] **Step 3: 實作**

在 `ass_style_tool/mkv_io.py`,`parse_ass_tracks` 之後加入:

```python
@dataclass
class MediaTrack:
    track_id: int
    track_type: str        # "video" | "audio" | "subtitles"
    codec_id: str
    language: str
    track_name: str
    default: bool
    forced: bool


_MEDIA_TRACK_TYPES = {"video", "audio", "subtitles"}


def parse_all_tracks(identify_json: dict) -> List[MediaTrack]:
    """從 mkvmerge -J 的 dict 取出所有 video/audio/subtitles 軌(依 id 排序)。"""
    result: List[MediaTrack] = []
    for track in identify_json.get("tracks", []):
        ttype = track.get("type")
        if ttype not in _MEDIA_TRACK_TYPES:
            continue
        props = track.get("properties", {})
        result.append(MediaTrack(
            track_id=int(track["id"]),
            track_type=ttype,
            codec_id=props.get("codec_id", ""),
            language=props.get("language", "und"),
            track_name=props.get("track_name", ""),
            default=bool(props.get("default_track", False)),
            forced=bool(props.get("forced_track", False)),
        ))
    result.sort(key=lambda t: t.track_id)
    return result


def list_all_tracks(mkv_path: Path, mkvmerge: Path) -> List[MediaTrack]:
    """跑 mkvmerge -J 列出所有軌;任何失敗回 []。"""
    cmd = [str(mkvmerge), "-J", str(mkv_path)]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, encoding="utf-8",
            **no_window_kwargs())
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        return []
    return parse_all_tracks(data)
```

（`dataclass`、`json`、`subprocess`、`no_window_kwargs`、`List`、`Path` 皆已在檔案頂部 import。）

- [ ] **Step 4: 跑測試確認通過**

Run: `py -m pytest tests/test_mkv_io.py -q`
Expected: PASS(既有 + 5 新測試)

- [ ] **Step 5: Commit**

```bash
git add ass_style_tool/mkv_io.py tests/test_mkv_io.py
git commit -m "Add list_all_tracks: enumerate every MKV track type

MediaTrack + parse_all_tracks/list_all_tracks return all video/audio/
subtitle tracks (id-sorted) for the upcoming Modify Old Tracks feature.
Existing SubtitleTrack/list_ass_tracks untouched.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `track_edit` 設定模型 + 旗標建構

**Files:**
- Create: `ass_style_tool/track_edit.py`
- Test: `tests/test_track_edit.py`

**Interfaces:**
- Consumes: `MediaTrack`(Task 1)。
- Produces:
  - `TrackEdit` dataclass:`keep: bool = True, set_default: Optional[bool] = None, set_forced: Optional[bool] = None, language: Optional[str] = None, track_name: Optional[str] = None`
  - `build_source_track_flags(edits: Dict[int, TrackEdit], tracks: List[MediaTrack]) -> List[str]`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_track_edit.py`:

```python
from __future__ import annotations

from ass_style_tool.mkv_io import MediaTrack
from ass_style_tool.track_edit import TrackEdit, build_source_track_flags


def _tracks():
    return [
        MediaTrack(0, "video", "V_HEVC", "und", "", True, False),
        MediaTrack(1, "audio", "A_FLAC", "jpn", "", True, False),
        MediaTrack(2, "subtitles", "S_TEXT/ASS", "chi", "繁A", False, False),
        MediaTrack(3, "subtitles", "S_TEXT/ASS", "chi", "繁B", False, False),
    ]


def test_empty_edits_no_flags():
    assert build_source_track_flags({}, _tracks()) == []


def test_all_keep_no_attrs_no_flags():
    edits = {i: TrackEdit() for i in range(4)}
    assert build_source_track_flags(edits, _tracks()) == []


def test_drop_one_subtitle_lists_kept_ids():
    flags = build_source_track_flags({3: TrackEdit(keep=False)}, _tracks())
    assert "--subtitle-tracks" in flags
    assert flags[flags.index("--subtitle-tracks") + 1] == "2"
    assert "--no-video" not in flags and "--no-audio" not in flags


def test_drop_all_audio_uses_no_audio():
    flags = build_source_track_flags({1: TrackEdit(keep=False)}, _tracks())
    assert "--no-audio" in flags


def test_default_forced_language_name_on_kept_track():
    flags = build_source_track_flags(
        {2: TrackEdit(set_default=True, set_forced=False,
                      language="chi", track_name="繁體")}, _tracks())
    assert flags[flags.index("--default-track") + 1] == "2:yes"
    assert flags[flags.index("--forced-track") + 1] == "2:no"
    assert flags[flags.index("--language") + 1] == "2:chi"
    assert flags[flags.index("--track-name") + 1] == "2:繁體"


def test_attrs_not_emitted_for_dropped_track():
    flags = build_source_track_flags(
        {2: TrackEdit(keep=False, set_default=True)}, _tracks())
    assert "--default-track" not in flags        # 丟棄軌不設屬性
    assert flags[flags.index("--subtitle-tracks") + 1] == "3"


def test_none_and_blank_attrs_not_emitted():
    flags = build_source_track_flags(
        {2: TrackEdit(set_default=None, language="", track_name="")}, _tracks())
    assert flags == []


def test_only_ids_present_in_tracks_produce_flags():
    # id 9 不在 tracks 內 → 忽略(per-video 過濾)
    flags = build_source_track_flags(
        {9: TrackEdit(keep=False, set_default=True)}, _tracks())
    assert flags == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_track_edit.py -q`
Expected: FAIL(`No module named 'ass_style_tool.track_edit'`)

- [ ] **Step 3: 實作 `track_edit.py`**

```python
"""封裝時修改來源既有軌道:設定模型 + mkvmerge 旗標建構(純邏輯,無 Qt)。

「定一次、依軌 ID 套用到全部」;build_source_track_flags 只對傳入 tracks 內
實際存在的 track_id 產生旗標(per-video 過濾安全網)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .mkv_io import MediaTrack


@dataclass
class TrackEdit:
    keep: bool = True                    # False = 丟棄此軌
    set_default: Optional[bool] = None   # None = 不變
    set_forced: Optional[bool] = None    # None = 不變
    language: Optional[str] = None       # None/"" = 不變
    track_name: Optional[str] = None     # None/"" = 不變


_TYPE_FLAGS = {
    "video": ("--video-tracks", "--no-video"),
    "audio": ("--audio-tracks", "--no-audio"),
    "subtitles": ("--subtitle-tracks", "--no-subtitles"),
}


def build_source_track_flags(
    edits: Dict[int, TrackEdit],
    tracks: List[MediaTrack],
) -> List[str]:
    """把每軌設定轉成套在來源影片輸入「前面」的 mkvmerge 旗標。"""
    if not edits:
        return []
    flags: List[str] = []
    # 保留/丟棄(依 type 分組)
    for ttype, (keep_flag, no_flag) in _TYPE_FLAGS.items():
        ids = [t.track_id for t in tracks if t.track_type == ttype]
        if not ids:
            continue
        kept = [i for i in ids if edits.get(i, TrackEdit()).keep]
        if len(kept) == len(ids):
            continue                      # 全保留 → 不下旗標
        if not kept:
            flags.append(no_flag)         # 全丟 → --no-<type>
        else:
            flags += [keep_flag, ",".join(str(i) for i in kept)]
    # 屬性(只作用於保留軌)
    for t in tracks:
        e = edits.get(t.track_id)
        if e is None or not e.keep:
            continue
        if e.set_default is not None:
            flags += ["--default-track",
                      f"{t.track_id}:{'yes' if e.set_default else 'no'}"]
        if e.set_forced is not None:
            flags += ["--forced-track",
                      f"{t.track_id}:{'yes' if e.set_forced else 'no'}"]
        if e.language:
            flags += ["--language", f"{t.track_id}:{e.language}"]
        if e.track_name:
            flags += ["--track-name", f"{t.track_id}:{e.track_name}"]
    return flags
```

- [ ] **Step 4: 跑測試確認通過**

Run: `py -m pytest tests/test_track_edit.py -q`
Expected: PASS(8 個測試)

- [ ] **Step 5: Commit**

```bash
git add ass_style_tool/track_edit.py tests/test_track_edit.py
git commit -m "Add track_edit: per-track config to mkvmerge source flags

TrackEdit + build_source_track_flags convert keep/drop + default/forced/
language/name choices into mkvmerge flags, emitting only for track ids
present in the given file (per-video filter) and attributes only on kept
tracks.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `mkv_mux` 命令與管線接受軌道旗標

**Files:**
- Modify: `ass_style_tool/mkv_mux.py`
- Test: `tests/test_mkv_mux.py`

**Interfaces:**
- Consumes: `list_all_tracks`(Task 1)、`build_source_track_flags`/`TrackEdit`(Task 2)。
- Produces:
  - `build_mux_command(..., source_flags: Optional[List[str]] = None)`
  - `process_mux(..., edits: Optional[Dict[int, TrackEdit]] = None, track_list_fn=list_all_tracks)`
  - `mux_fn` 協定尾端加 `source_flags: Optional[List[str]] = None`。

- [ ] **Step 1: 更新既有假 mux_fn + 寫新測試(先失敗)**

在 `tests/test_mkv_mux.py`:

先把所有既有假函式簽章補上 `source_flags=None`——用整檔取代:把每個 `def fake_mux(video, subtitle, out, meta, mkvmerge, progress_cb=None):` 改成 `def fake_mux(video, subtitle, out, meta, mkvmerge, progress_cb=None, source_flags=None):`,把每個 `def fake_mux(v, s, out, meta, mkvmerge, progress_cb=None):` 改成 `def fake_mux(v, s, out, meta, mkvmerge, progress_cb=None, source_flags=None):`。(共 6 個具名 fake_mux;`lambda *a, **k` 的兩個不需改。)

然後在檔尾加入新測試:

```python
def test_build_mux_command_source_flags_before_video():
    from ass_style_tool.mkv_mux import build_mux_command
    cmd = build_mux_command(
        Path("v.mkv"), Path("s.ass"), Path("o.mkv"), _meta(),
        Path("mkvmerge"), source_flags=["--no-audio", "--subtitle-tracks", "2"])
    assert cmd.index("--no-audio") > cmd.index("o.mkv")      # 在 -o out 之後
    assert cmd.index("--no-audio") < cmd.index("v.mkv")      # 在 video 之前
    assert cmd.index("--subtitle-tracks") < cmd.index("v.mkv")


def test_build_mux_command_no_source_flags_unchanged():
    from ass_style_tool.mkv_mux import build_mux_command
    cmd = build_mux_command(Path("v.mkv"), Path("s.ass"), Path("o.mkv"),
                            _meta(), Path("mkvmerge"))
    # video 緊接在 -o out 之後(無來源旗標)
    assert cmd[cmd.index("o.mkv") + 1] == "v.mkv"


def test_process_mux_applies_track_edits(tmp_path):
    from ass_style_tool.mkv_io import MediaTrack
    from ass_style_tool.track_edit import TrackEdit
    captured = {}

    def fake_mux(v, s, out, meta, mkvmerge, progress_cb=None, source_flags=None):
        captured["flags"] = source_flags
        Path(out).write_bytes(b"MUXED")
        return True

    def fake_tracks(video, mkvmerge):
        return [MediaTrack(0, "video", "V", "und", "", True, False),
                MediaTrack(1, "audio", "A", "jpn", "", True, False),
                MediaTrack(2, "subtitles", "S", "chi", "", False, False)]

    video = tmp_path / "show.mkv"
    video.write_bytes(b"X")
    pair = MuxPair(video, _write_ass(tmp_path), 1, "matched")
    report = process_mux(pair, _meta(), None, TOOLS,
                         out_path=tmp_path / "o" / "show.mkv",
                         mux_fn=fake_mux, edits={1: TrackEdit(keep=False)},
                         track_list_fn=fake_tracks)
    assert report.status == "ok"
    assert "--no-audio" in captured["flags"]


def test_process_mux_no_edits_empty_flags(tmp_path):
    captured = {}

    def fake_mux(v, s, out, meta, mkvmerge, progress_cb=None, source_flags=None):
        captured["flags"] = source_flags
        Path(out).write_bytes(b"M")
        return True

    video = tmp_path / "show.mkv"
    video.write_bytes(b"X")
    pair = MuxPair(video, _write_ass(tmp_path), 1, "matched")
    process_mux(pair, _meta(), None, TOOLS, out_path=tmp_path / "o" / "show.mkv",
                mux_fn=fake_mux)
    assert captured["flags"] == []


def test_process_mux_track_scan_failure_degrades(tmp_path):
    from ass_style_tool.track_edit import TrackEdit
    captured = {}

    def fake_mux(v, s, out, meta, mkvmerge, progress_cb=None, source_flags=None):
        captured["flags"] = source_flags
        Path(out).write_bytes(b"M")
        return True

    def boom(video, mkvmerge):
        raise OSError("scan fail")

    video = tmp_path / "show.mkv"
    video.write_bytes(b"X")
    pair = MuxPair(video, _write_ass(tmp_path), 1, "matched")
    process_mux(pair, _meta(), None, TOOLS, out_path=tmp_path / "o" / "show.mkv",
                mux_fn=fake_mux, edits={1: TrackEdit(keep=False)},
                track_list_fn=boom)
    assert captured["flags"] == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_mkv_mux.py -k "source_flags or track_edits or scan_failure or no_edits" -q`
Expected: FAIL(`build_mux_command() got an unexpected keyword argument 'source_flags'` 等)

- [ ] **Step 3: 改 `build_mux_command`**

在 `ass_style_tool/mkv_mux.py`,把 `build_mux_command` 改為:

```python
def build_mux_command(
    video_path: Path, subtitle_path: Path, out_path: Path,
    meta: MuxMeta, mkvmerge: Path,
    source_flags: Optional[List[str]] = None,
) -> List[str]:
    """影片所有軌保留(除非 source_flags 另有指定),外部字幕以附加軌加入(檔內為 track 0)。"""
    cmd: List[str] = [str(mkvmerge), "-o", str(out_path)]
    cmd += list(source_flags or [])          # 來源影片專屬旗標,須排在 video 之前
    cmd.append(str(video_path))
    cmd += ["--language", f"0:{meta.language}"]
    if meta.track_name:
        cmd += ["--track-name", f"0:{meta.track_name}"]
    cmd += ["--default-track", f"0:{'yes' if meta.default else 'no'}"]
    cmd += ["--forced-track", f"0:{'yes' if meta.forced else 'no'}"]
    cmd.append(str(subtitle_path))
    return cmd
```

- [ ] **Step 4: 改 `_default_mux` + `process_mux`**

把 `_default_mux` 簽章與呼叫改為:

```python
def _default_mux(video_path, subtitle_path, out_path, meta, mkvmerge,
                 progress_cb=None, source_flags=None) -> bool:
    from .mkv_io import parse_progress
    cmd = build_mux_command(video_path, subtitle_path, out_path, meta, mkvmerge,
                            source_flags)
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            **no_window_kwargs())
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

在檔案頂部 import 區加入:

```python
from .mkv_io import list_all_tracks
from .track_edit import build_source_track_flags
```

把 `process_mux` 簽章改為(加 `edits`、`track_list_fn`):

```python
def process_mux(
    pair: MuxPair,
    meta: MuxMeta,
    operation,
    tools: MkvTools,
    out_path: Optional[Path] = None,
    progress_cb: Optional[Callable[[int], None]] = None,
    mux_fn: Callable = _default_mux,
    verify_fn: Callable = identify_ok,
    edits: Optional[Dict[int, "TrackEdit"]] = None,
    track_list_fn: Callable = list_all_tracks,
) -> MkvFileReport:
```

在 `process_mux` 內、`if not mux_fn(...)` 呼叫之前(即 target 決定之後)插入來源旗標計算,並把 `source_flags` 傳進 `mux_fn`。把原本:

```python
        if out_path is not None:
            target = Path(out_path)
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            target = video.with_name(video.name + ".tmp.mkv")

        if not mux_fn(video, subtitle, target, meta, tools.mkvmerge,
                      progress_cb):
```

改為:

```python
        if out_path is not None:
            target = Path(out_path)
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            target = video.with_name(video.name + ".tmp.mkv")

        source_flags: List[str] = []
        if edits:
            try:
                tracks = track_list_fn(video, tools.mkvmerge)
                source_flags = build_source_track_flags(edits, tracks)
            except Exception:
                source_flags = []      # 掃軌失敗 → 不做軌道修改,照常封裝

        if not mux_fn(video, subtitle, target, meta, tools.mkvmerge,
                      progress_cb, source_flags):
```

（`Dict` 已在 `from typing import ... Dict ...` 匯入;`TrackEdit` 僅用於型別註解字串,不需實際 import。）

- [ ] **Step 5: 跑測試確認通過**

Run: `py -m pytest tests/test_mkv_mux.py -q`
Expected: PASS(既有 + 5 新測試,含更新後的 6 個假 mux_fn)

- [ ] **Step 6: Commit**

```bash
git add ass_style_tool/mkv_mux.py tests/test_mkv_mux.py
git commit -m "Thread source-track flags through the mux pipeline

build_mux_command takes source_flags (placed before the video input);
process_mux gains edits + track_list_fn, scanning each video's tracks and
building per-video flags (degrading to none on scan failure). edits=None
keeps current behavior byte-for-byte.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `ModifyTracksDialog`

**Files:**
- Create: `ass_style_tool/qt/modify_tracks_dialog.py`
- Test: `tests/test_modify_tracks_dialog.py`

**Interfaces:**
- Consumes: `MediaTrack`(Task 1)、`TrackEdit`(Task 2)。
- Produces:
  - `ModifyTracksDialog(tracks: List[MediaTrack], existing: Optional[Dict[int, TrackEdit]] = None, parent=None)`
  - `get_edits() -> Dict[int, TrackEdit]`
  - 屬性:`_keep_checks`、`_lang_edits`、`_name_edits`、`_default_combos`、`_forced_combos`(供測試操作)。

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_modify_tracks_dialog.py`:

```python
from __future__ import annotations

from ass_style_tool.mkv_io import MediaTrack
from ass_style_tool.track_edit import TrackEdit


def _tracks():
    return [
        MediaTrack(0, "video", "V_HEVC", "und", "", True, False),
        MediaTrack(1, "audio", "A_FLAC", "jpn", "", True, False),
        MediaTrack(2, "subtitles", "S_TEXT/ASS", "chi", "繁中", False, False),
    ]


def test_get_edits_defaults_keep_all(qapp):
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_tracks())
    edits = d.get_edits()
    assert set(edits) == {0, 1, 2}
    assert all(e.keep for e in edits.values())
    assert edits[2].set_default is None
    assert edits[2].language is None and edits[2].track_name is None


def test_get_edits_reads_widgets(qapp):
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_tracks())
    d._keep_checks[1].setChecked(False)          # 丟音訊
    d._default_combos[2].setCurrentIndex(1)      # 字幕預設=是
    d._lang_edits[2].setText("chi")
    d._name_edits[2].setText("繁體")
    edits = d.get_edits()
    assert edits[1].keep is False
    assert edits[2].set_default is True
    assert edits[2].language == "chi"
    assert edits[2].track_name == "繁體"


def test_existing_prefill(qapp):
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(
        _tracks(), existing={2: TrackEdit(keep=False, set_forced=True,
                                          language="eng")})
    assert d._keep_checks[2].isChecked() is False
    assert d._forced_combos[2].currentData() is True
    assert d._lang_edits[2].text() == "eng"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_modify_tracks_dialog.py -q`
Expected: FAIL(`No module named 'ass_style_tool.qt.modify_tracks_dialog'`)

- [ ] **Step 3: 實作 `modify_tracks_dialog.py`**

```python
"""「修改既有軌道」對話框:純 UI over 一批 MediaTrack,回傳 Dict[int, TrackEdit]。"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QDialog, QDialogButtonBox, QHBoxLayout,
                               QHeaderView, QLineEdit, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..mkv_io import MediaTrack
from ..track_edit import TrackEdit

_TYPE_LABELS = {"video": "影片", "audio": "音訊", "subtitles": "字幕"}
_TRISTATE = [("不變", None), ("是", True), ("否", False)]
_COLS = ["保留", "類型", "編碼", "語言", "軌名", "預設", "強制"]


class ModifyTracksDialog(QDialog):
    def __init__(self, tracks: List[MediaTrack],
                 existing: Optional[Dict[int, TrackEdit]] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("修改既有軌道")
        self._tracks = list(tracks)
        existing = existing or {}
        self._keep_checks: List[QCheckBox] = []
        self._lang_edits: List[QLineEdit] = []
        self._name_edits: List[QLineEdit] = []
        self._default_combos: List[QComboBox] = []
        self._forced_combos: List[QComboBox] = []

        root = QVBoxLayout(self)
        self.table = QTableWidget(len(self._tracks), len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        for r, t in enumerate(self._tracks):
            e = existing.get(t.track_id, TrackEdit())
            keep = QCheckBox()
            keep.setChecked(e.keep)
            self.table.setCellWidget(r, 0, self._center(keep))
            self._keep_checks.append(keep)
            self.table.setItem(
                r, 1, QTableWidgetItem(_TYPE_LABELS.get(t.track_type,
                                                        t.track_type)))
            self.table.setItem(r, 2, QTableWidgetItem(t.codec_id))
            lang = QLineEdit(e.language or "")
            lang.setPlaceholderText(t.language or "und")
            self.table.setCellWidget(r, 3, lang)
            self._lang_edits.append(lang)
            name = QLineEdit(e.track_name or "")
            name.setPlaceholderText(t.track_name)
            self.table.setCellWidget(r, 4, name)
            self._name_edits.append(name)
            dcombo = self._tristate_combo(e.set_default)
            self.table.setCellWidget(r, 5, dcombo)
            self._default_combos.append(dcombo)
            fcombo = self._tristate_combo(e.set_forced)
            self.table.setCellWidget(r, 6, fcombo)
            self._forced_combos.append(fcombo)
        root.addWidget(self.table)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _center(self, w: QWidget) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(w)
        return wrap

    def _tristate_combo(self, value: Optional[bool]) -> QComboBox:
        combo = QComboBox()
        for label, val in _TRISTATE:
            combo.addItem(label, val)
        combo.setCurrentIndex([v for _, v in _TRISTATE].index(value))
        return combo

    def get_edits(self) -> Dict[int, TrackEdit]:
        edits: Dict[int, TrackEdit] = {}
        for r, t in enumerate(self._tracks):
            lang = self._lang_edits[r].text().strip()
            name = self._name_edits[r].text().strip()
            edits[t.track_id] = TrackEdit(
                keep=self._keep_checks[r].isChecked(),
                set_default=self._default_combos[r].currentData(),
                set_forced=self._forced_combos[r].currentData(),
                language=lang or None,
                track_name=name or None,
            )
        return edits
```

- [ ] **Step 4: 跑測試確認通過**

Run: `py -m pytest tests/test_modify_tracks_dialog.py -q`
Expected: PASS(3 個測試)

- [ ] **Step 5: Commit**

```bash
git add ass_style_tool/qt/modify_tracks_dialog.py tests/test_modify_tracks_dialog.py
git commit -m "Add ModifyTracksDialog for editing existing MKV tracks

A pure UI over a list of MediaTrack: per-track keep checkbox, editable
language/name, and tri-state default/forced combos; get_edits() returns
Dict[int, TrackEdit]. Takes existing edits to pre-fill on reopen.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: 封裝分頁接線 + `MuxWorker` 轉交

**Files:**
- Modify: `ass_style_tool/qt/mux_tab.py`
- Modify: `ass_style_tool/qt/batch_worker.py`
- Test: `tests/test_mux_tab.py`, `tests/test_mux_worker.py`

**Interfaces:**
- Consumes: `list_all_tracks`(Task 1)、`TrackEdit`(Task 2)、`process_mux` 的 `edits`(Task 3)、`ModifyTracksDialog`(Task 4)。
- Produces: `MuxTab._track_edits: Dict[int, TrackEdit]`;`MuxWorker(..., edits=None)`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_mux_worker.py` 末端加:

```python
def test_mux_worker_forwards_edits(qapp):
    from ass_style_tool.qt.batch_worker import MuxWorker
    from ass_style_tool.mkv_mux import MuxMeta, MuxPair
    from ass_style_tool.track_edit import TrackEdit
    captured = {}

    def fake_process(pair, meta, operation, tools, out_path=None,
                     progress_cb=None, edits=None):
        captured["edits"] = edits
        from ass_style_tool.mkv_batch import MkvFileReport
        return MkvFileReport(pair.video_path, "ok")

    pairs = [MuxPair(__import__("pathlib").Path("v.mkv"),
                     __import__("pathlib").Path("s.ass"), 1, "matched")]
    edits = {1: TrackEdit(keep=False)}
    worker = MuxWorker(pairs, MuxMeta(), None, None, None,
                       process_fn=fake_process, edits=edits)
    worker.run()
    assert captured["edits"] == edits
```

在 `tests/test_mux_tab.py` 末端加(檔案已有 qapp fixture 用法;若需要建 tab 的既有 helper 請沿用):

```python
def test_modify_tracks_stores_edits(qapp, monkeypatch):
    import ass_style_tool.qt.mux_tab as mux_tab_mod
    from ass_style_tool.qt.mux_tab import MuxTab
    from ass_style_tool.mkv_io import MediaTrack
    from ass_style_tool.mkv_mux import MuxPair
    from ass_style_tool.track_edit import TrackEdit

    # 讓 tools 視為可用
    monkeypatch.setattr(mux_tab_mod, "mkvmerge_path", lambda: __import__("pathlib").Path("mkvmerge"))
    monkeypatch.setattr(mux_tab_mod, "mkvextract_path", lambda: __import__("pathlib").Path("mkvextract"))
    tab = MuxTab(lambda: None)

    # 有一部 matched 影片
    tab._pairs = [MuxPair(__import__("pathlib").Path("v.mkv"), None, 1, "matched")]

    monkeypatch.setattr(
        mux_tab_mod, "list_all_tracks",
        lambda video, mkvmerge: [MediaTrack(1, "audio", "A", "jpn", "", True, False)])

    class FakeDialog:
        def __init__(self, tracks, existing, parent):
            pass
        def exec(self):
            return 1
        def get_edits(self):
            return {1: TrackEdit(keep=False)}

    monkeypatch.setattr(mux_tab_mod, "ModifyTracksDialog", FakeDialog)
    tab._on_modify_tracks()
    assert tab._track_edits == {1: TrackEdit(keep=False)}
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_mux_worker.py::test_mux_worker_forwards_edits tests/test_mux_tab.py::test_modify_tracks_stores_edits -q`
Expected: FAIL(`MuxWorker() got an unexpected keyword argument 'edits'` / `MuxTab' object has no attribute '_on_modify_tracks'`)

- [ ] **Step 3: `MuxWorker` 加 `edits`**

在 `ass_style_tool/qt/batch_worker.py` 的 `MuxWorker`,把 `__init__` 簽章末端加 `edits=None`(排在 `process_fn` 之後,避免破壞既有位置參數):

```python
    def __init__(self, pairs, meta: MuxMeta, operation, tools,
                 output_dir: Optional[Path], process_fn=process_mux,
                 edits=None) -> None:
        super().__init__()
        self._pairs = list(pairs)
        self._meta = meta
        self._operation = operation
        self._tools = tools
        self._output_dir = output_dir
        self._process_fn = process_fn
        self._edits = edits
        self._cancelled = False
```

在 `MuxWorker.run()` 內呼叫 `self._process_fn(...)` 的地方,加上 `edits=self._edits`:

```python
            try:
                report = self._process_fn(
                    pair, self._meta, self._operation, self._tools,
                    out_path=out, progress_cb=self.file_progress.emit,
                    edits=self._edits)
```

- [ ] **Step 4: `MuxTab` 加按鈕、掃描、存設定、傳給 worker**

在 `ass_style_tool/qt/mux_tab.py`:

import 區加入:

```python
from PySide6.QtWidgets import QApplication
from ..mkv_io import list_all_tracks
from ..track_edit import TrackEdit
from .modify_tracks_dialog import ModifyTracksDialog
```

（`QApplication` 併進既有 `PySide6.QtWidgets` import;`Qt` 已匯入。）

在 `__init__` 開頭的狀態初始化區(例如 `self._pairs: List[MuxPair] = []` 之後)加:

```python
        self._track_edits: dict = {}
```

在 `action_row` 建立處,於 `scan_button` 與 `run_button` 之間插入「修改既有軌道…」按鈕。把原本:

```python
        action_row = QHBoxLayout()
        self.scan_button = QPushButton("重新掃描")
        self.scan_button.clicked.connect(self._on_scan)
        self.run_button = QPushButton("開始封裝")
```

改為:

```python
        action_row = QHBoxLayout()
        self.scan_button = QPushButton("重新掃描")
        self.scan_button.clicked.connect(self._on_scan)
        self.modify_tracks_button = QPushButton("修改既有軌道…")
        self.modify_tracks_button.setEnabled(False)
        self.modify_tracks_button.clicked.connect(self._on_modify_tracks)
        self.run_button = QPushButton("開始封裝")
```

並把 `modify_tracks_button` 加進 `action_row`。把原本:

```python
        for b in (self.scan_button, self.run_button, self.cancel_button):
            action_row.addWidget(b)
```

改為:

```python
        for b in (self.scan_button, self.modify_tracks_button,
                  self.run_button, self.cancel_button):
            action_row.addWidget(b)
```

在 `__init__` 結尾「tools 不可用時停用按鈕」的迴圈把 modify 也停用。把原本:

```python
        if not self.tools_available:
            for b in (self.scan_button, self.run_button):
                b.setEnabled(False)
```

改為:

```python
        if not self.tools_available:
            for b in (self.scan_button, self.run_button,
                      self.modify_tracks_button):
                b.setEnabled(False)
```

新增啟用邏輯與處理方法(放在 `_on_run` 之前的區塊,例如「軌資訊 / 操作」段附近):

```python
    def _refresh_modify_button(self) -> None:
        self.modify_tracks_button.setEnabled(
            self.tools_available
            and any(p.status == "matched" for p in self._pairs)
            and self._thread is None)

    def _has_track_edits(self) -> bool:
        return any(
            (not e.keep) or e.set_default is not None or e.set_forced is not None
            or e.language or e.track_name
            for e in self._track_edits.values())

    def _on_modify_tracks(self) -> None:
        matched = [p for p in self._pairs if p.status == "matched"]
        if not matched:
            self.log.emit("沒有可用的來源影片可掃描軌道")
            return
        video = matched[0].video_path
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            tracks = list_all_tracks(video, self._tools.mkvmerge)
        finally:
            QApplication.restoreOverrideCursor()
        if not tracks:
            self.log.emit(f"無法讀取軌道: {video.name}")
            return
        dialog = ModifyTracksDialog(tracks, self._track_edits, self)
        if dialog.exec():
            self._track_edits = dialog.get_edits()
            self.modify_tracks_button.setText(
                "修改既有軌道…(已設定)" if self._has_track_edits()
                else "修改既有軌道…")
```

在 `populate()` 結尾(設定 `run_button` 啟用後)與 `set_row_subtitle()` 結尾、`_on_finished()` 結尾各加一行 `self._refresh_modify_button()`。在 `_on_run()` 停用按鈕區(與 `self.run_button.setEnabled(False)` 同處)加 `self.modify_tracks_button.setEnabled(False)`。

最後把 `_on_run` 內建立 worker 的那行:

```python
        self._worker = MuxWorker(pairs, self.current_meta(), operation,
                                 self._tools, output_dir)
```

改為:

```python
        self._worker = MuxWorker(pairs, self.current_meta(), operation,
                                 self._tools, output_dir,
                                 edits=self._track_edits)
```

- [ ] **Step 5: 跑新測試 + 相關全套**

Run: `py -m pytest tests/test_mux_tab.py tests/test_mux_worker.py tests/test_mkv_mux.py -q`
Expected: PASS(全綠)

- [ ] **Step 6: 全套回歸**

Run: `py -m pytest tests -q`
Expected: PASS(326 + 新增測試,全綠)

- [ ] **Step 7: Commit**

```bash
git add ass_style_tool/qt/mux_tab.py ass_style_tool/qt/batch_worker.py tests/test_mux_tab.py tests/test_mux_worker.py
git commit -m "Wire Modify Old Tracks into the mux tab

Adds a 修改既有軌道… button that scans the first matched video, opens
ModifyTracksDialog, and stores the edits; MuxWorker forwards them to
process_mux so every muxed file gets the per-video source-track flags.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- 列出所有軌道 → Task 1 ✓
- 設定模型 + 旗標建構(保留/丟棄、default/forced/語言/軌名、屬性只作用保留軌、per-video 過濾)→ Task 2 ✓
- 命令 source_flags 插在 out 與 video 之間、process_mux edits + 掃軌降級 → Task 3 ✓
- 對話框(七欄、tri-state、get_edits、existing 預填)→ Task 4 ✓
- 封裝分頁按鈕/掃第一部/存設定/MuxWorker 轉交 → Task 5 ✓
- edits 為空維持現行行為 → Task 3 `test_process_mux_no_edits_empty_flags` + build_mux_command `source_flags=None` ✓
- 掃軌失敗降級 → Task 3 `test_process_mux_track_scan_failure_degrades` ✓
- 既有假 mux_fn 更新 → Task 3 Step 1 ✓
- 測試計畫各項 → 各 Task 涵蓋 ✓

**2. Placeholder scan:** 無 TBD/TODO;每個 code step 均含完整程式碼與指令。

**3. Type consistency:** `MediaTrack` 欄位(Task 1)在 Task 2/4 使用一致;`TrackEdit`(keep/set_default/set_forced/language/track_name)在 Task 2/3/4/5 一致;`build_source_track_flags(edits, tracks)`、`list_all_tracks(mkv_path, mkvmerge)`、`process_mux(..., edits, track_list_fn)`、`build_mux_command(..., source_flags)`、`MuxWorker(..., edits)` 簽章跨 Task 一致;`mux_fn` 尾端 `source_flags=None` 與 process_mux 的位置參數呼叫一致。

## 範圍外(本計畫不做)

- 重新排序軌道、章節/附件修改、清空既有軌名、全批一致性掃描 + 掃描進度動畫(下一個功能)。
