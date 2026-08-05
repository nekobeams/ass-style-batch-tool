# 軌道資訊面板 Implementation Plan

**Goal:** 讓「修改既有軌道」對話框顯示所選軌道在**每一部**已配對影片的實際狀況,並讓套用時不會把設定套到別的檔案裡同 ID 但不同類型的軌道上。

**Architecture:** 四塊。新增 `TrackScanWorker`(沿用 `MkvScanWorker` 已驗證的進度/取消模式)掃描整批影片;新增純邏輯模組 `track_info.py` 把「某軌 ID 在各檔案的狀況」組成可直接呈現的資料;`TrackEdit` 加 `track_type` 讓 `build_source_track_flags` 做型別比對;對話框改吃整批 map 並加上唯讀資訊表格,封裝分頁改成非同步掃描後才開對話框。

**Tech Stack:** Python、PySide6(QThread/Signal/QDialog/QTableWidget)、mkvmerge(`-J`)、pytest(offscreen)。

## Global Constraints

- 一律用 `py`,不要用 `python`。測試從 repo root:`py -m pytest tests -q`。目前基線 **386 passed**,實作後維持全綠(新增測試使總數上升)。
- **取消必須用獨立的 `cancelled` 訊號,不可用 `finished({})` 代替**:「掃完但沒有任何軌道」與「使用者取消」語意不同。
- **取消時丟棄已累積的部分結果**,不得回傳不完整的 map。
- **取消粒度為檔案與檔案之間**:檢查點在每個檔案開始前,執行中的那一次 `list_fn` 會先跑完;不強制中止子行程。
- **⚠ 對話框的取消訊號必須接到分頁端的 slot,由它「直接呼叫」`worker.cancel()`**,絕不可 `dialog.cancelled.connect(worker.cancel)`。worker 已 `moveToThread`,直接連線會被解析成排隊連線,而該執行緒在 `run()` 執行期間不跑事件迴圈,排隊的 `cancel()` 要等掃描結束才處理——等於取消完全無效。此坑已於掃描進度對話框那輪踩過並修正,`mkv_tab.py` 的 `_request_scan_cancel` 就是正確寫法。
- `TrackEdit.track_type` 預設 `None` 時**維持現行行為**(不比對、照舊套用),既有呼叫端與既有測試不受影響。
- 掃描範圍是**所有 `status == "matched"` 的配對影片**(不是只有已勾選的)。
- 資訊面板**唯讀**,不做每檔個別覆寫。
- commit 訊息結尾加:`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- 環境:Bash 每次 `cd /c/Claude_code`。

---

## File Structure

- `ass_style_tool/qt/batch_worker.py`(修改):新增 `TrackScanWorker`。
- `ass_style_tool/track_info.py`(新增,純邏輯無 Qt):`TrackInfoRow` + `build_track_info_rows`。
- `ass_style_tool/track_edit.py`(修改):`TrackEdit` 加 `track_type`;`build_source_track_flags` 做型別比對。
- `ass_style_tool/qt/modify_tracks_dialog.py`(修改):改吃 `tracks_by_file`、加資訊表格、`get_edits()` 填 `track_type`。
- `ass_style_tool/qt/mux_tab.py`(修改):`_on_modify_tracks` 改為非同步掃描全批。
- 測試:`tests/test_mux_worker.py`(加)、`tests/test_track_info.py`(新)、`tests/test_track_edit.py`(加)、`tests/test_modify_tracks_dialog.py`(改+加)、`tests/test_mux_tab.py`(改+加)。

---

### Task 1: `TrackScanWorker`

**Files:**
- Modify: `ass_style_tool/qt/batch_worker.py`(在 `MkvScanWorker` 之後新增一個類別)
- Test: `tests/test_mux_worker.py`

**Interfaces:**
- Consumes: `list_all_tracks(mkv_path: Path, mkvmerge: Path) -> List[MediaTrack]`(既有,已在 `mkv_io.py`)。
- Produces:
  - `TrackScanWorker(video_paths, mkvmerge, list_fn=list_all_tracks)`
  - `finished = Signal(object)`(payload 為 `dict[Path, list[MediaTrack]]`)
  - `progress = Signal(int, int)`、`cancelled = Signal()`、`cancel() -> None`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_mux_worker.py` 末端加入:

```python
def test_track_scan_worker_emits_progress_and_map(qapp):
    from pathlib import Path
    from ass_style_tool.qt.batch_worker import TrackScanWorker
    from ass_style_tool.mkv_io import MediaTrack

    paths = [Path("a.mkv"), Path("b.mkv"), Path("c.mkv")]

    def fake_list(path, mkvmerge):
        return [MediaTrack(0, "video", "V", "und", "", True, False)]

    worker = TrackScanWorker(paths, Path("mkvmerge.exe"), list_fn=fake_list)
    seen = []
    got = {}
    worker.progress.connect(lambda d, t: seen.append((d, t)))
    worker.finished.connect(lambda m: got.update(m))
    worker.run()
    assert seen == [(1, 3), (2, 3), (3, 3)]
    assert sorted(p.name for p in got) == ["a.mkv", "b.mkv", "c.mkv"]
    assert got[Path("a.mkv")][0].track_type == "video"


def test_track_scan_worker_cancel_stops_early(qapp):
    from pathlib import Path
    from ass_style_tool.qt.batch_worker import TrackScanWorker

    paths = [Path("a.mkv"), Path("b.mkv"), Path("c.mkv")]
    calls = []

    def fake_list(path, mkvmerge):
        calls.append(path)
        worker.cancel()          # 第一個檔掃完就要求取消
        return []

    worker = TrackScanWorker(paths, Path("mkvmerge.exe"), list_fn=fake_list)
    events = []
    worker.finished.connect(lambda m: events.append("finished"))
    worker.cancelled.connect(lambda: events.append("cancelled"))
    worker.run()
    assert events == ["cancelled"]   # 取消不可發 finished
    assert len(calls) == 1           # 真的提早停,不是跑完才丟棄


def test_track_scan_worker_empty_list_finishes_empty(qapp):
    from pathlib import Path
    from ass_style_tool.qt.batch_worker import TrackScanWorker

    worker = TrackScanWorker([], Path("mkvmerge.exe"), list_fn=lambda p, m: [])
    got = {"finished": None, "progress": []}
    worker.finished.connect(lambda m: got.__setitem__("finished", m))
    worker.progress.connect(lambda a, b: got["progress"].append((a, b)))
    worker.run()
    assert got["finished"] == {}
    assert got["progress"] == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_mux_worker.py -k track_scan -q`
Expected: FAIL(`cannot import name 'TrackScanWorker'`)

- [ ] **Step 3: 實作**

在 `ass_style_tool/qt/batch_worker.py` 的 `MkvScanWorker` 類別**之後**、`MkvWorker` 之前插入:

```python
class TrackScanWorker(QObject):
    """掃描指定的影片清單,列舉每檔的所有軌道;支援進度回報與取消。"""

    finished = Signal(object)      # dict[Path, list[MediaTrack]]
    progress = Signal(int, int)    # 已完成, 總數
    cancelled = Signal()           # 使用者取消(部分結果丟棄)

    def __init__(self, video_paths, mkvmerge: Path,
                 list_fn=list_all_tracks) -> None:
        super().__init__()
        self._paths = [Path(p) for p in video_paths]
        self._mkvmerge = mkvmerge
        self._list_fn = list_fn
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._paths)
        result = {}
        for i, path in enumerate(self._paths, start=1):
            # 檢查點在每個檔案之前;執行中的那一次 list_fn 會先跑完
            if self._cancelled:
                self.cancelled.emit()   # 丟棄 result,不發 finished
                return
            result[path] = self._list_fn(path, self._mkvmerge)
            self.progress.emit(i, total)
        self.finished.emit(result)
```

在檔案頂部的 import 區,把既有的 `from ..mkv_io import list_ass_tracks` 改為:

```python
from ..mkv_io import list_all_tracks, list_ass_tracks
```

- [ ] **Step 4: 跑測試確認通過**

Run: `py -m pytest tests/test_mux_worker.py -q`
Expected: PASS(既有 + 3 個新測試)

- [ ] **Step 5: Commit**

```bash
git add ass_style_tool/qt/batch_worker.py tests/test_mux_worker.py
git commit -m "Add TrackScanWorker for scanning a list of videos

Same progress/cancel contract as MkvScanWorker but over an explicit list
of video paths rather than a folder walk, returning every track of each
file. Cancelling emits a distinct cancelled signal and discards the
partial map.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `track_info` 純邏輯模組

**Files:**
- Create: `ass_style_tool/track_info.py`
- Test: `tests/test_track_info.py`

**Interfaces:**
- Consumes: `MediaTrack`(`ass_style_tool.mkv_io`,欄位 `track_id, track_type, codec_id, language, track_name, default, forced`)。
- Produces:
  - `TrackInfoRow` dataclass:`video_name: str, found: bool, type_matches: bool, track_type: str, default: Optional[bool], forced: Optional[bool], track_name: str, language: str`
  - `build_track_info_rows(track_id: int, template_type: str, tracks_by_file: Dict[Path, List[MediaTrack]]) -> List[TrackInfoRow]`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_track_info.py`:

```python
from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_io import MediaTrack
from ass_style_tool.track_info import build_track_info_rows


def _sub(tid, lang="chi", name="繁中", default=False, forced=False):
    return MediaTrack(tid, "subtitles", "S_TEXT/ASS", lang, name,
                      default, forced)


def _audio(tid):
    return MediaTrack(tid, "audio", "A_FLAC", "jpn", "", True, False)


def _files():
    return {
        Path("b.mkv"): [_audio(1), _sub(2, name="B繁中", default=True)],
        Path("a.mkv"): [_audio(1), _sub(2, name="A繁中")],
        Path("c.mkv"): [_audio(1)],              # 沒有軌 2
        Path("d.mkv"): [_audio(1), _audio(2)],   # 軌 2 是音訊,類型不符
    }


def test_rows_sorted_by_file_name():
    rows = build_track_info_rows(2, "subtitles", _files())
    assert [r.video_name for r in rows] == ["a.mkv", "b.mkv", "c.mkv", "d.mkv"]


def test_row_for_matching_track_carries_that_files_values():
    rows = {r.video_name: r for r in build_track_info_rows(2, "subtitles",
                                                           _files())}
    b = rows["b.mkv"]
    assert b.found is True and b.type_matches is True
    assert b.track_name == "B繁中"
    assert b.language == "chi"
    assert b.default is True          # 取的是該檔自己的值
    assert b.forced is False
    assert rows["a.mkv"].track_name == "A繁中"
    assert rows["a.mkv"].default is False


def test_row_for_missing_track():
    rows = {r.video_name: r for r in build_track_info_rows(2, "subtitles",
                                                           _files())}
    c = rows["c.mkv"]
    assert c.found is False
    assert c.type_matches is False
    assert c.default is None and c.forced is None
    assert c.track_name == "" and c.language == ""


def test_row_for_type_mismatch_reports_actual_type():
    rows = {r.video_name: r for r in build_track_info_rows(2, "subtitles",
                                                           _files())}
    d = rows["d.mkv"]
    assert d.found is True            # ID 存在
    assert d.type_matches is False    # 但不是字幕
    assert d.track_type == "audio"    # 告訴使用者它實際是什麼
    assert d.default is None and d.forced is None


def test_empty_map_gives_no_rows():
    assert build_track_info_rows(2, "subtitles", {}) == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_track_info.py -q`
Expected: FAIL(`No module named 'ass_style_tool.track_info'`)

- [ ] **Step 3: 實作 `track_info.py`**

```python
"""資訊面板的資料組裝:某個軌道 ID 在各檔案的實際狀況(純邏輯,無 Qt)。

規則是依軌道 ID 套用的,但同一個 ID 在不同檔案未必是同一種軌道——
type_matches 就是用來讓使用者看出這件事。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .mkv_io import MediaTrack


@dataclass
class TrackInfoRow:
    video_name: str
    found: bool             # 該檔有沒有這個軌道 ID
    type_matches: bool      # 有,且類型與範本相同(found 為 False 時一律 False)
    track_type: str         # 該檔這個 ID 實際的類型(找不到時為 "")
    default: Optional[bool] # 類型不符或找不到時為 None
    forced: Optional[bool]
    track_name: str
    language: str


def build_track_info_rows(
    track_id: int,
    template_type: str,
    tracks_by_file: Dict[Path, List[MediaTrack]],
) -> List[TrackInfoRow]:
    """依檔名排序,回傳每部影片對這個軌道 ID 的狀況。"""
    rows: List[TrackInfoRow] = []
    for path in sorted(tracks_by_file, key=lambda p: p.name):
        track = next(
            (t for t in tracks_by_file[path] if t.track_id == track_id), None)
        if track is None:
            rows.append(TrackInfoRow(
                video_name=path.name, found=False, type_matches=False,
                track_type="", default=None, forced=None,
                track_name="", language=""))
            continue
        if track.track_type != template_type:
            # ID 在,但不是同一種軌道:該檔不會套用這條設定
            rows.append(TrackInfoRow(
                video_name=path.name, found=True, type_matches=False,
                track_type=track.track_type, default=None, forced=None,
                track_name="", language=""))
            continue
        rows.append(TrackInfoRow(
            video_name=path.name, found=True, type_matches=True,
            track_type=track.track_type, default=track.default,
            forced=track.forced, track_name=track.track_name,
            language=track.language))
    return rows
```

- [ ] **Step 4: 跑測試確認通過**

Run: `py -m pytest tests/test_track_info.py -q`
Expected: PASS(5 個測試)

- [ ] **Step 5: Commit**

```bash
git add ass_style_tool/track_info.py tests/test_track_info.py
git commit -m "Add build_track_info_rows for the per-file track panel

Pure assembly of "what does each file actually have for this track id" --
missing, present-and-same-type (carrying that file's own default/forced/
name/language), or present-but-a-different-type, which is the case the
panel exists to surface.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `TrackEdit.track_type` 型別比對

**Files:**
- Modify: `ass_style_tool/track_edit.py`
- Test: `tests/test_track_edit.py`

**Interfaces:**
- Consumes: `MediaTrack`(既有)。
- Produces:
  - `TrackEdit` 新增欄位 `track_type: Optional[str] = None`(排在既有欄位之後,不影響既有的關鍵字/位置用法)
  - `build_source_track_flags` 行為:`track_type` 有值且與該檔該 ID 的實際類型不同 → 該設定視為不存在。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_track_edit.py` 末端加入(檔案已有 `_tracks()` helper):

```python
def _audio_at_2():
    """軌 2 是音訊的檔案——與範本(字幕)不同類型。"""
    return [
        MediaTrack(0, "video", "V_HEVC", "und", "", True, False),
        MediaTrack(1, "audio", "A_FLAC", "jpn", "", True, False),
        MediaTrack(2, "audio", "A_AC3", "eng", "", False, False),
    ]


def test_type_mismatch_does_not_drop_the_wrong_track():
    # 使用者把「字幕軌 2」設為丟棄;這個檔案的軌 2 卻是音訊 → 不可丟音訊
    edits = {2: TrackEdit(keep=False, track_type="subtitles")}
    flags = build_source_track_flags(edits, _audio_at_2())
    assert "--no-audio" not in flags
    assert "--audio-tracks" not in flags
    assert flags == []          # 這個檔案完全不受影響


def test_type_mismatch_does_not_emit_attributes():
    edits = {2: TrackEdit(set_default=True, language="chi",
                          track_name="繁中", track_type="subtitles")}
    flags = build_source_track_flags(edits, _audio_at_2())
    assert flags == []


def test_type_match_still_applies():
    edits = {2: TrackEdit(set_default=True, track_type="subtitles")}
    flags = build_source_track_flags(edits, _tracks())   # 軌 2 是字幕
    assert flags[flags.index("--default-track") + 1] == "2:yes"


def test_track_type_none_keeps_old_behaviour():
    # 沒記錄類型 → 不比對,維持既有行為(回歸保護)
    edits = {2: TrackEdit(keep=False)}
    flags = build_source_track_flags(edits, _audio_at_2())
    assert "--no-audio" in flags or "--audio-tracks" in flags
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_track_edit.py -k "type_mismatch or type_match or track_type_none" -q`
Expected: FAIL(`TrackEdit.__init__() got an unexpected keyword argument 'track_type'`)

- [ ] **Step 3: 加欄位**

在 `ass_style_tool/track_edit.py` 的 `TrackEdit` dataclass 末端加一個欄位:

```python
@dataclass
class TrackEdit:
    keep: bool = True                    # False = 丟棄此軌
    set_default: Optional[bool] = None   # None = 不變
    set_forced: Optional[bool] = None    # None = 不變
    language: Optional[str] = None       # None/"" = 不變
    track_name: Optional[str] = None     # None/"" = 不變
    track_type: Optional[str] = None     # 這條設定是為哪種軌道建立的;
                                         # None = 不比對(維持舊行為)
```

- [ ] **Step 4: 加型別比對**

在 `build_source_track_flags` 內加一個小 helper,並在兩處使用它。把函式主體(從 `if not edits:` 之後)改為:

```python
    if not edits:
        return []

    def _edit_for(track: MediaTrack) -> Optional[TrackEdit]:
        """回傳可套用到這條軌的設定;類型不符則視為沒有設定。"""
        edit = edits.get(track.track_id)
        if edit is None:
            return None
        if edit.track_type is not None and edit.track_type != track.track_type:
            return None      # 同一個 ID 在這個檔案是別種軌道,不可套用
        return edit

    flags: List[str] = []
    # 保留/丟棄(依 type 分組)
    for ttype, (keep_flag, no_flag) in _TYPE_FLAGS.items():
        typed = [t for t in tracks if t.track_type == ttype]
        if not typed:
            continue
        kept = []
        for t in typed:
            edit = _edit_for(t)
            if edit is None or edit.keep:
                kept.append(t.track_id)
        if len(kept) == len(typed):
            continue                      # 全保留 → 不下旗標
        if not kept:
            flags.append(no_flag)         # 全丟 → --no-<type>
        else:
            flags += [keep_flag, ",".join(str(i) for i in kept)]
    # 屬性(只作用於保留軌)
    for t in tracks:
        e = _edit_for(t)
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

- [ ] **Step 5: 跑測試確認通過**

Run: `py -m pytest tests/test_track_edit.py -q`
Expected: PASS(既有 8 個 + 4 個新測試全綠——既有測試證明未帶 `track_type` 的行為沒變)

- [ ] **Step 6: Commit**

```bash
git add ass_style_tool/track_edit.py tests/test_track_edit.py
git commit -m "Only apply a track edit when the track type matches

Edits were keyed purely by track id, so a rule made for a subtitle track
could drop or relabel an audio track in a file whose ids differ. TrackEdit
now records the type it was made for and mismatches are treated as no
edit at all. track_type=None keeps the previous behaviour.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: 對話框改吃整批 map + 資訊表格

**Files:**
- Modify: `ass_style_tool/qt/modify_tracks_dialog.py`
- Test: `tests/test_modify_tracks_dialog.py`

**Interfaces:**
- Consumes: `build_track_info_rows`/`TrackInfoRow`(Task 2)、`TrackEdit.track_type`(Task 3)。
- Produces:
  - `ModifyTracksDialog(tracks_by_file: Dict[Path, List[MediaTrack]], existing=None, parent=None)`
  - `self.info_table`(QTableWidget,6 欄)
  - `get_edits()` 產生的每個 `TrackEdit` 都帶 `track_type`

- [ ] **Step 1: 改既有測試 + 寫新測試**

`tests/test_modify_tracks_dialog.py` 目前用 `ModifyTracksDialog(_tracks())` 建構。把檔案頂部的 helper 區塊加入一個 map helper,並把**所有** `ModifyTracksDialog(_tracks()...)` 呼叫改成傳 map。在 `_tracks()` 之後加入:

```python
from pathlib import Path


def _files():
    """單一檔案的 map——既有測試沿用這個,行為與原本傳 list 相同。"""
    return {Path("a.mkv"): _tracks()}
```

然後把既有測試中的 `ModifyTracksDialog(_tracks())` 改為 `ModifyTracksDialog(_files())`,`ModifyTracksDialog(_tracks(), existing={...})` 改為 `ModifyTracksDialog(_files(), existing={...})`(共 4 處:`test_get_edits_defaults_keep_all`、`test_get_edits_reads_widgets`、`test_existing_prefill`、`test_table_has_alternating_rows`)。

再加新測試:

```python
def test_get_edits_records_track_type(qapp):
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_files())
    edits = d.get_edits()
    # _tracks() 是 video(0) / audio(1) / subtitles(2)
    assert edits[0].track_type == "video"
    assert edits[1].track_type == "audio"
    assert edits[2].track_type == "subtitles"


def test_info_table_shows_one_row_per_file(qapp):
    from pathlib import Path
    from ass_style_tool.mkv_io import MediaTrack
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog

    files = {
        Path("a.mkv"): _tracks(),
        Path("b.mkv"): [MediaTrack(0, "video", "V", "und", "", True, False)],
    }
    d = ModifyTracksDialog(files)
    assert d.info_table.rowCount() == 2
    assert d.info_table.item(0, 0).text() == "a.mkv"
    assert d.info_table.item(1, 0).text() == "b.mkv"


def test_info_table_follows_selected_track_row(qapp):
    from pathlib import Path
    from ass_style_tool.mkv_io import MediaTrack
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog

    files = {
        Path("a.mkv"): _tracks(),                                  # 軌2=字幕
        Path("b.mkv"): [MediaTrack(2, "audio", "A", "jpn", "", True, False)],
    }
    d = ModifyTracksDialog(files)
    d.table.selectRow(2)                       # 選字幕軌(ID 2)
    b_row = 1 if d.info_table.item(1, 0).text() == "b.mkv" else 0
    assert "類型不符" in d.info_table.item(b_row, 1).text()

    d.table.selectRow(0)                       # 改選視訊軌(ID 0)
    b_row = 1 if d.info_table.item(1, 0).text() == "b.mkv" else 0
    assert "✗" in d.info_table.item(b_row, 1).text()   # b.mkv 沒有軌 0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_modify_tracks_dialog.py -q`
Expected: FAIL(`'dict' object has no attribute ...` 或 `has no attribute 'info_table'`)

- [ ] **Step 3: 改建構參數與範本來源**

在 `ass_style_tool/qt/modify_tracks_dialog.py`:

import 區加入:

```python
from pathlib import Path

from ..track_info import build_track_info_rows
```

把 `__init__` 的簽章與開頭改為(用排序後的第一個檔案當範本):

```python
    def __init__(self, tracks_by_file: Dict[Path, List[MediaTrack]],
                 existing: Optional[Dict[int, TrackEdit]] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("修改既有軌道")
        self._tracks_by_file = dict(tracks_by_file)
        # 範本取排序後的第一個檔案——與資訊面板的排序一致,不會各自為政
        first = (sorted(self._tracks_by_file, key=lambda p: p.name)[0]
                 if self._tracks_by_file else None)
        self._tracks = list(self._tracks_by_file[first]) if first else []
```

（其餘 `existing = existing or {}` 與五個 widget list 的初始化維持不變。)

- [ ] **Step 4: 加資訊表格**

在 `root.addWidget(self.table)` 之後、按鈕列之前插入:

```python
        self.info_table = QTableWidget(0, len(_INFO_COLS))
        self.info_table.setHorizontalHeaderLabels(_INFO_COLS)
        self.info_table.setAlternatingRowColors(True)
        self.info_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.info_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.info_table.verticalHeader().setVisible(False)
        self.info_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        root.addWidget(self.info_table)
        self.table.itemSelectionChanged.connect(self._refresh_info_table)
        if self._tracks:
            self.table.selectRow(0)      # 開啟時就有內容
        self._refresh_info_table()
```

在 `_COLS` 常數之後加入欄位名稱:

```python
_INFO_COLS = ["影片", "找到", "預設", "強制", "軌名", "語言"]
_TRISTATE_TEXT = {True: "是", False: "否", None: ""}
```

- [ ] **Step 5: 加刷新方法**

在 `get_edits` 之前加入:

```python
    def _selected_track(self) -> Optional[MediaTrack]:
        row = self.table.currentRow()
        if 0 <= row < len(self._tracks):
            return self._tracks[row]
        return None

    def _refresh_info_table(self) -> None:
        track = self._selected_track()
        if track is None:
            self.info_table.setRowCount(0)
            return
        rows = build_track_info_rows(
            track.track_id, track.track_type, self._tracks_by_file)
        self.info_table.setRowCount(len(rows))
        for r, info in enumerate(rows):
            if not info.found:
                found_text = "✗"
            elif not info.type_matches:
                # 這正是面板要讓使用者看見的情況:同一個 ID 是別種軌道
                found_text = (f"⚠ 類型不符({_TYPE_LABELS.get(track.track_type, track.track_type)}"
                              f" → {_TYPE_LABELS.get(info.track_type, info.track_type)}),不會套用")
            else:
                found_text = "✓"
            values = [
                info.video_name, found_text,
                _TRISTATE_TEXT[info.default], _TRISTATE_TEXT[info.forced],
                info.track_name, info.language,
            ]
            for c, text in enumerate(values):
                self.info_table.setItem(r, c, QTableWidgetItem(text))
```

- [ ] **Step 6: `get_edits` 填入 track_type**

把 `get_edits` 內建立 `TrackEdit` 的部分加上 `track_type=t.track_type`:

```python
            edits[t.track_id] = TrackEdit(
                keep=self._keep_checks[r].isChecked(),
                set_default=self._default_combos[r].currentData(),
                set_forced=self._forced_combos[r].currentData(),
                language=lang or None,
                track_name=name or None,
                track_type=t.track_type,
            )
```

- [ ] **Step 7: 跑測試確認通過**

Run: `py -m pytest tests/test_modify_tracks_dialog.py -q`
Expected: PASS(既有 4 個改過的 + 3 個新測試)

- [ ] **Step 8: Commit**

```bash
git add ass_style_tool/qt/modify_tracks_dialog.py tests/test_modify_tracks_dialog.py
git commit -m "Show per-file track info in the modify-tracks dialog

The dialog now takes every scanned file rather than one template list and
adds a read-only table showing, for the selected track, what each video
actually has: missing, matching (with that file's own flags), or the same
id holding a different kind of track, which is called out as not applying.
get_edits() records each edit's track type so the type check can work.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: 封裝分頁改為非同步掃描全批

**Files:**
- Modify: `ass_style_tool/qt/mux_tab.py`
- Test: `tests/test_mux_tab.py`

**Interfaces:**
- Consumes: `TrackScanWorker`(Task 1)、`ModifyTracksDialog(tracks_by_file, ...)`(Task 4)、既有的 `ScanProgressDialog`。
- Produces: `MuxTab._track_scan_thread`、`_track_scan_worker`、`_track_scan_dialog`、`_request_track_scan_cancel()`、`_finish_track_scan()`、`_on_track_scan_done(map)`、`_on_track_scan_cancelled()`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_mux_tab.py` 末端加入:

```python
def test_track_scan_done_opens_dialog_with_map(qapp, monkeypatch):
    import ass_style_tool.qt.mux_tab as mux_tab_mod
    from pathlib import Path
    from ass_style_tool.mkv_io import MediaTrack
    from ass_style_tool.track_edit import TrackEdit

    monkeypatch.setattr(mux_tab_mod, "mkvmerge_path", lambda: Path("mkvmerge"))
    monkeypatch.setattr(mux_tab_mod, "mkvextract_path", lambda: Path("mkvx"))
    tab = mux_tab_mod.MuxTab(lambda: None)

    seen = {}

    class FakeDialog:
        def __init__(self, tracks_by_file, existing, parent):
            seen["map"] = tracks_by_file
        def exec(self):
            return 1
        def get_edits(self):
            return {2: TrackEdit(keep=False, track_type="subtitles")}

    monkeypatch.setattr(mux_tab_mod, "ModifyTracksDialog", FakeDialog)
    scanned = {Path("a.mkv"): [MediaTrack(2, "subtitles", "S", "chi", "",
                                          False, False)]}
    tab._on_track_scan_done(scanned)
    assert seen["map"] == scanned                  # 整份 map 傳進對話框
    assert tab._track_edits == {2: TrackEdit(keep=False,
                                             track_type="subtitles")}


def test_track_scan_cancelled_leaves_edits_untouched(qapp, monkeypatch):
    import ass_style_tool.qt.mux_tab as mux_tab_mod
    from pathlib import Path

    monkeypatch.setattr(mux_tab_mod, "mkvmerge_path", lambda: Path("mkvmerge"))
    monkeypatch.setattr(mux_tab_mod, "mkvextract_path", lambda: Path("mkvx"))
    tab = mux_tab_mod.MuxTab(lambda: None)

    def boom(*a, **k):
        raise AssertionError("取消後不該開啟對話框")

    monkeypatch.setattr(mux_tab_mod, "ModifyTracksDialog", boom)
    tab._track_edits = {}
    tab._on_track_scan_cancelled()
    assert tab._track_edits == {}


def test_empty_scan_result_does_not_open_dialog(qapp, monkeypatch):
    import ass_style_tool.qt.mux_tab as mux_tab_mod
    from pathlib import Path

    monkeypatch.setattr(mux_tab_mod, "mkvmerge_path", lambda: Path("mkvmerge"))
    monkeypatch.setattr(mux_tab_mod, "mkvextract_path", lambda: Path("mkvx"))
    tab = mux_tab_mod.MuxTab(lambda: None)

    def boom(*a, **k):
        raise AssertionError("沒有任何軌道時不該開啟對話框")

    monkeypatch.setattr(mux_tab_mod, "ModifyTracksDialog", boom)
    tab._on_track_scan_done({Path("a.mkv"): []})    # 全部讀不到軌道
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `py -m pytest tests/test_mux_tab.py -k track_scan -q`
Expected: FAIL(`'MuxTab' object has no attribute '_on_track_scan_done'`)

- [ ] **Step 3: 加 import 與狀態**

在 `ass_style_tool/qt/mux_tab.py`:

import 區補上(`ScanProgressDialog` 與 `TrackScanWorker`;`list_all_tracks` 不再直接使用可保留亦可移除,本步驟保留):

```python
from .batch_worker import MuxScanWorker, MuxWorker, TrackScanWorker
from .scan_progress_dialog import ScanProgressDialog
```

在 `__init__` 的狀態初始化區(`self._track_edits: dict = {}` 附近)加入:

```python
        self._track_scan_thread: Optional[QThread] = None
        self._track_scan_worker = None
        self._track_scan_dialog: Optional[ScanProgressDialog] = None
```

- [ ] **Step 4: 改寫 `_on_modify_tracks`**

把整個 `_on_modify_tracks` 方法換成:

```python
    def _on_modify_tracks(self) -> None:
        if self._track_scan_thread is not None:
            self.log.emit("軌道掃描進行中")
            return
        matched = [p for p in self._pairs if p.status == "matched"]
        if not matched:
            self.log.emit("沒有可用的來源影片可掃描軌道")
            return
        self._track_scan_thread = QThread()
        self._track_scan_worker = TrackScanWorker(
            [p.video_path for p in matched], self._tools.mkvmerge)
        self._track_scan_worker.moveToThread(self._track_scan_thread)
        self._track_scan_thread.started.connect(self._track_scan_worker.run)
        self._track_scan_worker.finished.connect(self._on_track_scan_done)
        self._track_scan_worker.cancelled.connect(
            self._on_track_scan_cancelled)
        self._track_scan_dialog = ScanProgressDialog(self)
        self._track_scan_worker.progress.connect(
            self._track_scan_dialog.set_progress)
        self._track_scan_dialog.cancelled.connect(
            self._request_track_scan_cancel)
        self._track_scan_dialog.show()   # 非 exec():維持非同步流程
        self._track_scan_thread.start()

    def _request_track_scan_cancel(self) -> None:
        """直接呼叫 worker.cancel(),不用 signal→worker slot 的連線。

        worker 已 moveToThread,但該執行緒在 run() 執行期間不會跑事件迴圈,
        排隊的 cancel() 要等掃描結束才會被處理——等於完全沒有作用。
        """
        if self._track_scan_worker is not None:
            self._track_scan_worker.cancel()

    def _finish_track_scan(self) -> None:
        """完成/取消共用的收尾:關對話框、收執行緒。"""
        if self._track_scan_dialog is not None:
            self._track_scan_dialog.hide()
            self._track_scan_dialog.deleteLater()
            self._track_scan_dialog = None
        if self._track_scan_thread is not None:
            self._track_scan_thread.quit()
            self._track_scan_thread.wait()
        self._track_scan_thread = None
        self._track_scan_worker = None

    def _on_track_scan_done(self, tracks_by_file: dict) -> None:
        self._finish_track_scan()
        if not any(tracks_by_file.values()):
            self.log.emit("所有影片都讀不到軌道資訊")
            return
        dialog = ModifyTracksDialog(tracks_by_file, self._track_edits, self)
        if dialog.exec():
            self._track_edits = dialog.get_edits()
            self.modify_tracks_button.setText(
                "修改既有軌道…(已設定)" if self._has_track_edits()
                else "修改既有軌道…")

    def _on_track_scan_cancelled(self) -> None:
        self._finish_track_scan()
        self.log.emit("軌道掃描已取消")
```

- [ ] **Step 5: 關閉視窗時收掉掃描執行緒**

在既有的 `shutdown` 方法中,把要收的執行緒清單加入軌道掃描執行緒。把:

```python
    def shutdown(self) -> None:
        for thread in (self._thread, self._scan_thread):
```

改為:

```python
    def shutdown(self) -> None:
        for worker in (self._worker, self._scan_worker,
                       self._track_scan_worker):
            if worker is not None:
                worker.cancel()
        for thread in (self._thread, self._scan_thread,
                       self._track_scan_thread):
```

（`MuxScanWorker` 沒有 `cancel()`,因此上面的迴圈只對有該方法的 worker 呼叫——實作時請用 `if worker is not None and hasattr(worker, "cancel")` 保護,避免關閉時拋例外。)

- [ ] **Step 6: 跑新測試 + 相關全套**

Run: `py -m pytest tests/test_mux_tab.py tests/test_mux_worker.py tests/test_modify_tracks_dialog.py -q`
Expected: PASS(全綠)

- [ ] **Step 7: 全套回歸**

Run: `py -m pytest tests -q`
Expected: PASS(386 + 新增測試,全綠)

- [ ] **Step 8: Commit**

```bash
git add ass_style_tool/qt/mux_tab.py tests/test_mux_tab.py
git commit -m "Scan every matched video before opening the tracks dialog

Replaces the synchronous single-file scan with a cancellable batch scan
over all matched videos, so the dialog can show what each file actually
has. Cancel routes through a tab-side slot that calls the worker directly
-- a queued connection into a thread with no running event loop would
never be processed. Completion and cancellation share one teardown.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- `TrackScanWorker`(進度/取消/獨立 cancelled/丟棄部分結果/指定清單)→ Task 1 ✓
- `build_track_info_rows` 三種情況 + 依檔名排序 → Task 2 ✓
- `TrackEdit.track_type` + 型別比對(保留/丟棄與屬性兩處)+ None 維持舊行為 → Task 3 ✓
- 對話框改吃 map、範本取排序後第一個檔案、資訊表格、選取列連動、`get_edits` 填類型 → Task 4 ✓
- 封裝分頁非同步掃描、取消 slot 的正確接法、共用收尾、全空結果不開對話框 → Task 5 ✓
- 掃描範圍為所有 matched → Task 5 Step 4 ✓
- 面板唯讀 → Task 4 `setEditTriggers(NoEditTriggers)` ✓
- 測試計畫各項(含「不得誤丟音訊」具體案例)→ Task 3 `test_type_mismatch_does_not_drop_the_wrong_track` ✓

**2. Placeholder scan:** 無 TBD/TODO;每個 code step 均含完整程式碼與可執行指令。Task 5 Step 5 的 `hasattr` 保護已明確寫出理由與作法。

**3. Type consistency:** `TrackInfoRow` 欄位(Task 2)在 Task 4 `_refresh_info_table` 以 `info.video_name/found/type_matches/track_type/default/forced/track_name/language` 使用一致;`build_track_info_rows(track_id, template_type, tracks_by_file)` 簽章跨 Task 2/4 一致;`TrackEdit.track_type`(Task 3)在 Task 4 `get_edits` 與 Task 5 測試中使用一致;`TrackScanWorker(video_paths, mkvmerge, list_fn)` 與其三個訊號在 Task 1/5 一致;`ModifyTracksDialog(tracks_by_file, existing, parent)` 在 Task 4/5 一致。

## 範圍外(本計畫不做)

- 每檔個別覆寫、軌道重新排序、章節/附件修改、區分「掃描失敗」與「真的沒有軌道」、依面板結果自動調整勾選。
