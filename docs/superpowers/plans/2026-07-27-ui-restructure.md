# UI 重整實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MKV 分頁只列檔案、字幕軌選擇改由「修改既有軌道…」對話框以「語言+軌名」規則整批控制;資料夾掃描不再遞迴進子資料夾;三個工作分頁改用右側設定側欄的版面(方案 C)。

**Architecture:** 先把可獨立測試的純邏輯(`track_select.py`)與版面共用元件(`layout_helpers.py`)做出來,再依序把三個分頁換成新骨架。MKV 分頁的功能改寫與版面改寫合併在最後一個任務,避免同一個檔案被改寫兩次。`process_mkv` 單檔管線完全不動。

**Tech Stack:** Python 3.13、PySide6(Qt Widgets)、pytest。GUI 測試走 offscreen(`tests/conftest.py` 已設定)。

## Global Constraints

- 專案根目錄是 `C:\Claude_code`。每個指令前先切過去。
- **一律用 `py`,不要用 `python`**(`python` 是壞掉的 WindowsApps stub,會靜默失敗)。
- 測試指令:`py -m pytest tests -q`(從 repo root)。改動前 master 是 **423 passed**。
- 回覆用繁體中文;commit 訊息用英文。
- **`setStyleSheet` 一律要帶型別選擇器**(例:`"QComboBox { background: transparent; }"`)。裸的宣告會往下傳給子孫控件,曾把深色下拉文字對比從 13.36:1 打到 1.25:1。
- **worker 的 `cancel()` 一律從 GUI 執行緒的 slot 直接呼叫**,絕不用 signal → worker slot 的連線(worker 已 `moveToThread`,該執行緒在 `run()` 期間不跑事件迴圈,排隊的呼叫等於無效)。
- **宣稱在守某個約束的測試,要用 mutation 驗證它真的會失敗**(把程式改回壞的樣子,確認測試變紅)。計畫中標示「mutation 檢查」的步驟不可略過。
- 不動 `theme.py` 的任何配色值(`_DARK` / `_LIGHT` 的 17 個欄位)。
- 不動 `process_mkv` 單檔管線。
- 所有既有控件的屬性名(`folder_edit`、`run_button`、`scan_button`、`outdir_edit`、`scale_panel` 等)一律保留,不得改名。

規格:`docs/superpowers/specs/2026-07-27-ui-restructure-design.md`

---

## File Structure

**新增:**

| 檔案 | 責任 |
|---|---|
| `ass_style_tool/track_select.py` | 純邏輯:把 (語言, 軌名) 規則解析成逐檔軌清單、產生驗證面板資料、算未涵蓋軌數 |
| `ass_style_tool/qt/select_tracks_dialog.py` | 「修改既有軌道…」對話框(MKV 分頁專用) |
| `ass_style_tool/qt/layout_helpers.py` | 方案 C 的共用建構器與間距常數 |
| `tests/test_track_select.py` | Task 1 |
| `tests/test_layout_helpers.py` | Task 4 |
| `tests/test_select_tracks_dialog.py` | Task 8 |

**修改:**

| 檔案 | 改動 |
|---|---|
| `ass_style_tool/episode_match.py` | `find_files` 不遞迴 |
| `ass_style_tool/qt/batch_worker.py` | `MkvScanWorker` 改吃 `list[Path]` |
| `ass_style_tool/qt/theme.py` | 只調 `QGroupBox` 的 margin/padding/font-weight |
| `ass_style_tool/qt/scale_panel.py` | 改單欄版面 |
| `ass_style_tool/qt/subtitle_tab.py` | 版面方案 C + 分隔器持久化 |
| `ass_style_tool/qt/mux_tab.py` | 版面方案 C + 分隔器持久化 |
| `ass_style_tool/qt/mkv_tab.py` | 樹改清單、選軌對話框接線、版面方案 C |
| `ass_style_tool/mkv_batch.py` | 刪除 `select_same_type` |

---

## Task 1: 選軌規則的純邏輯

**Files:**
- Create: `ass_style_tool/track_select.py`
- Test: `tests/test_track_select.py`

**Interfaces:**
- Consumes: `ass_style_tool.mkv_batch.track_key`(既有,`(track) -> (language, track_name)`)、`ass_style_tool.mkv_io.SubtitleTrack`
- Produces:
  - `TrackKey = Tuple[str, str]`
  - `all_keys(files_tracks: Dict[Path, List[SubtitleTrack]]) -> Set[TrackKey]`
  - `resolve_tracks(keys: Set[TrackKey], files_tracks: Dict[Path, List[SubtitleTrack]]) -> Dict[Path, List[SubtitleTrack]]`
  - `SelectInfoRow`(dataclass:`video_name: str`、`track_ids: List[int]`)
  - `build_select_info_rows(key: TrackKey, files_tracks: Dict[Path, List[SubtitleTrack]]) -> List[SelectInfoRow]`
  - `uncovered_track_count(keys: Set[TrackKey], files_tracks: Dict[Path, List[SubtitleTrack]]) -> Tuple[int, int]`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/test_track_select.py`:

```python
from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_io import SubtitleTrack
from ass_style_tool.track_select import (all_keys, build_select_info_rows,
                                         resolve_tracks,
                                         uncovered_track_count)


def _track(tid, lang="chi", name="繁中"):
    return SubtitleTrack(tid, "S_TEXT/ASS", lang, name, False, False)


FILES = {
    Path("e1.mkv"): [_track(2, "chi", "繁中"), _track(3, "chi", "简中")],
    Path("e2.mkv"): [_track(5, "chi", "简中"), _track(7, "chi", "繁中")],
    Path("e3.mkv"): [_track(1, "jpn", "")],
    Path("e4.mkv"): [],
}


def test_resolve_tracks_matches_by_key_not_by_track_id():
    """整季裡某集多一條音訊軌會把字幕軌 ID 推掉——規則必須依語言+軌名。"""
    got = resolve_tracks({("chi", "繁中")}, FILES)
    assert {p.name: [t.track_id for t in ts] for p, ts in got.items()} == {
        "e1.mkv": [2], "e2.mkv": [7]}


def test_resolve_tracks_omits_files_without_a_match():
    got = resolve_tracks({("chi", "繁中")}, FILES)
    assert Path("e3.mkv") not in got     # 只有日文軌
    assert Path("e4.mkv") not in got     # 完全沒有 ASS 軌


def test_resolve_tracks_keeps_every_track_sharing_one_key():
    """兩條軌都是 und 且無軌名時同一個鍵會命中兩條,兩條都要納入。"""
    files = {Path("e1.mkv"): [_track(2, "und", ""), _track(3, "und", "")]}
    got = resolve_tracks({("und", "")}, files)
    assert [t.track_id for t in got[Path("e1.mkv")]] == [2, 3]


def test_resolve_tracks_empty_keys_selects_nothing():
    assert resolve_tracks(set(), FILES) == {}


def test_all_keys_collects_every_key_in_the_batch():
    assert all_keys(FILES) == {("chi", "繁中"), ("chi", "简中"), ("jpn", "")}


def test_build_select_info_rows_reports_found_missing_and_multiple():
    files = {
        Path("b.mkv"): [_track(4, "chi", "繁中")],
        Path("a.mkv"): [_track(2, "chi", "繁中"), _track(3, "chi", "繁中")],
        Path("c.mkv"): [_track(9, "jpn", "")],
    }
    rows = build_select_info_rows(("chi", "繁中"), files)
    assert [r.video_name for r in rows] == ["a.mkv", "b.mkv", "c.mkv"]
    assert rows[0].track_ids == [2, 3]   # 多條符合
    assert rows[1].track_ids == [4]      # 剛好一條
    assert rows[2].track_ids == []       # 找不到


def test_uncovered_track_count_counts_videos_and_tracks():
    """範本檔沒有的軌會被靜默略過——對話框要能把數字講出來。"""
    videos, tracks = uncovered_track_count({("chi", "繁中")}, FILES)
    assert (videos, tracks) == (3, 3)    # e1 简中 / e2 简中 / e3 jpn


def test_uncovered_track_count_zero_when_every_key_selected():
    assert uncovered_track_count(all_keys(FILES), FILES) == (0, 0)
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd /c/Claude_code && py -m pytest tests/test_track_select.py -q
```

預期:全部 collection error,`ModuleNotFoundError: No module named 'ass_style_tool.track_select'`

- [ ] **Step 3: 寫實作**

建立 `ass_style_tool/track_select.py`:

```python
"""依「語言 + 軌名」把範本檔上選定的字幕軌解析到整批影片(純邏輯,無 Qt)。

MKV 分頁的字幕軌選擇改成「在範本檔上定規則、整批套用」之後,需要一組不
依賴 Qt 的函式:把規則解析成逐檔的軌清單、產生逐檔驗證面板的內容、以及
算出有多少軌沒被任何規則涵蓋(範本檔只代表一個檔案,其他檔案可能有它
沒有的軌;這些軌會被靜默略過,呼叫端要能把數字講出來)。

刻意不用軌 ID 當鍵:同一季裡某集多一條音訊軌就會把字幕軌的 ID 推掉,
依 ID 會套到另一種語言的字幕上。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple

from .mkv_batch import track_key
from .mkv_io import SubtitleTrack

#: (語言, 軌名)
TrackKey = Tuple[str, str]


def all_keys(files_tracks: Dict[Path, List[SubtitleTrack]]) -> Set[TrackKey]:
    """整批影片出現過的所有鍵。"""
    return {track_key(t) for tracks in files_tracks.values() for t in tracks}


def resolve_tracks(
    keys: Set[TrackKey],
    files_tracks: Dict[Path, List[SubtitleTrack]],
) -> Dict[Path, List[SubtitleTrack]]:
    """把鍵集合解析成逐檔要套用的軌清單。

    一個檔案有多條軌符合同一個鍵時全部納入(呼叫端的資訊面板會標 ⚠)。
    沒有任何軌符合的檔案不會出現在結果中——批次執行時等於跳過。
    """
    result: Dict[Path, List[SubtitleTrack]] = {}
    for path, tracks in files_tracks.items():
        picked = [t for t in tracks if track_key(t) in keys]
        if picked:
            result[path] = picked
    return result


@dataclass
class SelectInfoRow:
    video_name: str
    track_ids: List[int]   # 空 = 找不到;長度 > 1 = 多條符合


def build_select_info_rows(
    key: TrackKey,
    files_tracks: Dict[Path, List[SubtitleTrack]],
) -> List[SelectInfoRow]:
    """逐檔資訊面板的內容:一個鍵在每部影片解析到哪幾條軌。依檔名排序。"""
    rows: List[SelectInfoRow] = []
    for path in sorted(files_tracks, key=lambda p: p.name):
        ids = [t.track_id for t in files_tracks[path] if track_key(t) == key]
        rows.append(SelectInfoRow(video_name=path.name, track_ids=ids))
    return rows


def uncovered_track_count(
    keys: Set[TrackKey],
    files_tracks: Dict[Path, List[SubtitleTrack]],
) -> Tuple[int, int]:
    """回傳 (含未涵蓋軌的影片數, 未涵蓋軌總數)。

    「未涵蓋」= 該檔有 ASS 字幕軌,但它的鍵不在 keys 裡。
    """
    videos = 0
    tracks = 0
    for file_tracks in files_tracks.values():
        count = sum(1 for t in file_tracks if track_key(t) not in keys)
        if count:
            videos += 1
            tracks += count
    return videos, tracks
```

- [ ] **Step 4: 跑測試確認通過**

```bash
cd /c/Claude_code && py -m pytest tests/test_track_select.py -q
```

預期:`8 passed`

- [ ] **Step 5: 跑全套測試**

```bash
cd /c/Claude_code && py -m pytest tests -q
```

預期:`431 passed`(423 + 8)

- [ ] **Step 6: Commit**

```bash
cd /c/Claude_code && git add ass_style_tool/track_select.py tests/test_track_select.py && git commit -m "Add track_select: resolve subtitle tracks by language and track name"
```

---

## Task 2: 資料夾掃描不遞迴

**Files:**
- Modify: `ass_style_tool/episode_match.py:53-64`
- Test: `tests/test_episode_match.py:45-53`

**Interfaces:**
- Consumes: 無
- Produces: `find_files(folder) -> Tuple[List[Path], List[Path]]` 簽章不變,只是行為改成只掃當層

- [ ] **Step 1: 改測試(先讓它失敗)**

把 `tests/test_episode_match.py` 裡現有的 `test_find_files`(第 45-53 行)整個換成下面兩個測試:

```python
def test_find_files(tmp_path):
    (tmp_path / "a [01].ass").write_text("x", encoding="utf-8")
    (tmp_path / "b [02].ssa").write_text("x", encoding="utf-8")
    (tmp_path / "v [01].mkv").write_bytes(b"")
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    subs, videos = find_files(tmp_path)
    assert [p.name for p in subs] == ["a [01].ass", "b [02].ssa"]
    assert [p.name for p in videos] == ["v [01].mkv"]


def test_find_files_ignores_subfolders(tmp_path):
    """選資料夾固定只掃當層:子資料夾的字幕與影片一律不納入。

    使用者明確決定不加「包含子資料夾」勾選框(畫面已經太擠)。
    """
    (tmp_path / "a [01].ass").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b [02].ssa").write_text("x", encoding="utf-8")
    (tmp_path / "sub" / "v [02].mkv").write_bytes(b"")
    subs, videos = find_files(tmp_path)
    assert [p.name for p in subs] == ["a [01].ass"]
    assert videos == []
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd /c/Claude_code && py -m pytest tests/test_episode_match.py -q
```

預期:`test_find_files_ignores_subfolders` FAILED —— `assert ['a [01].ass', 'b [02].ssa'] == ['a [01].ass']`

- [ ] **Step 3: 寫實作**

`ass_style_tool/episode_match.py`,把 `find_files` 裡的 `rglob` 換成 `glob`:

```python
def find_files(folder: Path) -> Tuple[List[Path], List[Path]]:
    """列出資料夾**當層**的字幕檔與影片檔(不進子資料夾)。

    刻意不遞迴:整季素材放同一層是常態,而遞迴會把不相干的子資料夾一起
    掃進來,還讓「不同子資料夾同名影片」在以檔名當 key 的面板裡撞在一起。
    """
    subs: List[Path] = []
    videos: List[Path] = []
    for path in sorted(Path(folder).glob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext in SUB_EXTS:
            subs.append(path)
        elif ext in VIDEO_EXTS:
            videos.append(path)
    return subs, videos
```

- [ ] **Step 4: 跑測試確認通過**

```bash
cd /c/Claude_code && py -m pytest tests/test_episode_match.py -q
```

預期:`18 passed`

- [ ] **Step 5: mutation 檢查(必做)**

暫時把 `glob("*")` 改回 `rglob("*")`,重跑:

```bash
cd /c/Claude_code && py -m pytest tests/test_episode_match.py::test_find_files_ignores_subfolders -q
```

預期:**FAILED**。確認後把 `rglob` 改回 `glob`。若它照樣通過,表示這個測試沒有真的 pin 住約束,必須重寫。

- [ ] **Step 6: 跑全套測試**

```bash
cd /c/Claude_code && py -m pytest tests -q
```

預期:`432 passed`

- [ ] **Step 7: Commit**

```bash
cd /c/Claude_code && git add ass_style_tool/episode_match.py tests/test_episode_match.py && git commit -m "Scan only the chosen folder, not its subfolders"
```

---

## Task 3: MkvScanWorker 改吃檔案清單

**Files:**
- Modify: `ass_style_tool/qt/batch_worker.py:137-167`
- Modify: `ass_style_tool/qt/mkv_tab.py:203`(僅呼叫點,一行)
- Test: `tests/test_mkv_worker.py`

**Interfaces:**
- Consumes: `ass_style_tool.mkv_io.list_ass_tracks`
- Produces: `MkvScanWorker(paths: Iterable[Path], mkvmerge: Path, list_fn=list_ass_tracks)`;signals 不變(`finished(dict)` / `progress(int, int)` / `cancelled()`);**新增**建構後第一件事發 `progress(0, total)`,與 `TrackScanWorker` 一致

- [ ] **Step 1: 改測試(先讓它失敗)**

`tests/test_mkv_worker.py`:把 `test_scan_worker_lists_tracks`(第 16-33 行)換成下面兩個,並更新後面三個 `MkvScanWorker` 測試。

換掉 `test_scan_worker_lists_tracks`:

```python
def test_scan_worker_lists_tracks_for_given_paths(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvScanWorker
    a = tmp_path / "e1.mkv"
    b = tmp_path / "e2.mkv"
    a.write_bytes(b"")
    b.write_bytes(b"")

    def fake_list(path, mkvmerge):
        return [_track(2)] if path.name == "e1.mkv" else []

    worker = MkvScanWorker([a, b], Path("mkvmerge.exe"), list_fn=fake_list)
    got = {}
    worker.finished.connect(lambda d: got.update(d))
    worker.run()
    assert sorted(p.name for p in got) == ["e1.mkv", "e2.mkv"]
    assert [t.track_id for t in got[a]] == [2]
    assert got[b] == []


def test_scan_worker_only_scans_the_paths_it_was_given(qapp, tmp_path):
    """回歸:worker 不再自己 rglob 資料夾,分頁給什麼就掃什麼。

    改版前它遞迴整個資料夾,會把子資料夾與未勾選的檔案一起送進
    mkvmerge -J。
    """
    from ass_style_tool.qt.batch_worker import MkvScanWorker
    wanted = tmp_path / "e1.mkv"
    wanted.write_bytes(b"")
    (tmp_path / "e2.mkv").write_bytes(b"")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "e3.mkv").write_bytes(b"")

    seen = []

    def fake_list(path, mkvmerge):
        seen.append(path)
        return []

    worker = MkvScanWorker([wanted], Path("mkvmerge.exe"), list_fn=fake_list)
    worker.run()
    assert seen == [wanted]
```

把 `test_scan_worker_emits_progress_per_file`(第 151-160 行)換成:

```python
def test_scan_worker_emits_progress_per_file(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvScanWorker
    paths = []
    for name in ("e1.mkv", "e2.mkv", "e3.mkv"):
        p = tmp_path / name
        p.write_bytes(b"")
        paths.append(p)
    worker = MkvScanWorker(paths, Path("mkvmerge.exe"), list_fn=lambda p, m: [])
    seen = []
    worker.progress.connect(lambda done, total: seen.append((done, total)))
    worker.run()
    # 開頭那筆 (0, 3) 讓進度對話框立刻切到確定範圍,不必等第一檔掃完
    assert seen == [(0, 3), (1, 3), (2, 3), (3, 3)]
```

把 `test_scan_worker_cancel_stops_early_and_emits_cancelled`(第 163-180 行)換成:

```python
def test_scan_worker_cancel_stops_early_and_emits_cancelled(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvScanWorker
    paths = []
    for name in ("e1.mkv", "e2.mkv", "e3.mkv"):
        p = tmp_path / name
        p.write_bytes(b"")
        paths.append(p)
    calls = []

    def fake_list(path, mkvmerge):
        calls.append(path)
        worker.cancel()          # 第一個檔掃完就要求取消
        return []

    worker = MkvScanWorker(paths, Path("mkvmerge.exe"), list_fn=fake_list)
    events = []
    worker.finished.connect(lambda d: events.append("finished"))
    worker.cancelled.connect(lambda: events.append("cancelled"))
    worker.run()
    assert events == ["cancelled"]   # 取消不可發 finished
    assert len(calls) == 1           # 真的提早停,不是跑完才丟棄
```

把 `test_scan_worker_no_mkv_finishes_empty`(第 183-193 行)換成:

```python
def test_scan_worker_empty_list_finishes_empty(qapp):
    from ass_style_tool.qt.batch_worker import MkvScanWorker
    worker = MkvScanWorker([], Path("mkvmerge.exe"), list_fn=lambda p, m: [])
    got = {"finished": None, "progress": []}
    worker.finished.connect(lambda d: got.__setitem__("finished", d))
    worker.progress.connect(lambda a, b: got["progress"].append((a, b)))
    worker.run()
    assert got["finished"] == {}
    assert got["progress"] == [(0, 0)]
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd /c/Claude_code && py -m pytest tests/test_mkv_worker.py -q
```

預期:多個 FAILED(worker 仍把 list 當資料夾用,`AttributeError: 'list' object has no attribute 'rglob'` 或 progress 序列不符)

- [ ] **Step 3: 寫實作(worker)**

`ass_style_tool/qt/batch_worker.py`,把 `MkvScanWorker` 整個類別(第 137-167 行)換成:

```python
class MkvScanWorker(QObject):
    """列舉指定 MKV 清單各檔的 ASS 字幕軌;支援進度回報與取消。

    吃檔案清單而非資料夾:MKV 分頁的資料夾掃描已經改成只列檔名、不跑
    外部程序,mkvmerge -J 只在使用者真的要選軌(或按下開始處理而尚未
    設定規則)時才跑。形狀刻意與 TrackScanWorker 一致。
    """

    finished = Signal(object)      # dict[Path, list[SubtitleTrack]]
    progress = Signal(int, int)    # 已完成, 總數
    cancelled = Signal()           # 使用者取消(部分結果丟棄)

    def __init__(self, paths, mkvmerge: Path,
                 list_fn=list_ass_tracks) -> None:
        super().__init__()
        self._paths = [Path(p) for p in paths]
        self._mkvmerge = mkvmerge
        self._list_fn = list_fn
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._paths)
        result = {}
        self.progress.emit(0, total)  # 先讓對話框切到確定範圍,不是等第一檔跑完才有反應
        for i, path in enumerate(self._paths, start=1):
            # 檢查點在每個檔案之前;執行中的那一次 list_fn 會先跑完
            if self._cancelled:
                self.cancelled.emit()   # 丟棄 result,不發 finished
                return
            result[path] = self._list_fn(path, self._mkvmerge)
            self.progress.emit(i, total)
        self.finished.emit(result)
```

- [ ] **Step 4: 更新 mkv_tab 的呼叫點**

`ass_style_tool/qt/mkv_tab.py` 第 203 行,把:

```python
        self._scan_worker = MkvScanWorker(Path(folder), self._tools.mkvmerge)
```

換成(這行同時讓 MKV 分頁的列檔不再遞迴;Task 9 會把整段重寫):

```python
        self._scan_worker = MkvScanWorker(
            sorted(p for p in Path(folder).glob("*.mkv") if p.is_file()),
            self._tools.mkvmerge)
```

- [ ] **Step 5: 跑測試確認通過**

```bash
cd /c/Claude_code && py -m pytest tests/test_mkv_worker.py tests/test_mkv_tab.py -q
```

預期:全部 passed

- [ ] **Step 6: 跑全套測試**

```bash
cd /c/Claude_code && py -m pytest tests -q
```

預期:`433 passed`

- [ ] **Step 7: Commit**

```bash
cd /c/Claude_code && git add ass_style_tool/qt/batch_worker.py ass_style_tool/qt/mkv_tab.py tests/test_mkv_worker.py && git commit -m "MkvScanWorker takes an explicit file list instead of a folder"
```

---

## Task 4: 版面共用元件與群組盒樣式

**Files:**
- Create: `ass_style_tool/qt/layout_helpers.py`
- Modify: `ass_style_tool/qt/theme.py:125-132`(只有 QGroupBox 那一段)
- Test: `tests/test_layout_helpers.py`
- Test: `tests/test_theme.py`(加一個測試)

**Interfaces:**
- Consumes: 無
- Produces:
  - 常數 `MARGIN = 12`、`SPACING = 10`、`GROUP_SPACING = 8`、`SIDEBAR_MIN_WIDTH = 240`
  - `page_layout(widget: QWidget) -> QVBoxLayout`
  - `group(title: str, inner: QLayout) -> QGroupBox`
  - `settings_sidebar(*groups: QWidget) -> QWidget`
  - `main_splitter(main_area: QWidget, sidebar: QWidget) -> QSplitter`
  - `action_row(secondary: Sequence[QWidget], primary: Sequence[QWidget]) -> QHBoxLayout`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/test_layout_helpers.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from ass_style_tool.qt.layout_helpers import (GROUP_SPACING, MARGIN, SPACING,
                                              SIDEBAR_MIN_WIDTH, action_row,
                                              group, main_splitter,
                                              page_layout, settings_sidebar)


def test_group_sets_title_and_inner_spacing(qapp):
    box = group("輸出", QVBoxLayout())
    assert box.title() == "輸出"
    assert box.layout().spacing() == GROUP_SPACING
    assert box.layout().contentsMargins().left() == GROUP_SPACING


def test_settings_sidebar_has_minimum_width(qapp):
    """側欄要夠寬才塞得下 ScalePanel 與語言下拉,窄過頭等於沒做。"""
    assert settings_sidebar().minimumWidth() == SIDEBAR_MIN_WIDTH


def test_settings_sidebar_stacks_groups_then_leaves_slack(qapp):
    first = group("甲", QVBoxLayout())
    second = group("乙", QVBoxLayout())
    panel = settings_sidebar(first, second)
    layout = panel.layout()
    assert layout.itemAt(0).widget() is first
    assert layout.itemAt(1).widget() is second
    assert layout.itemAt(2).spacerItem() is not None   # 底部留白,群組不被拉開


def test_main_splitter_orders_list_then_sidebar(qapp):
    left, right = QWidget(), QWidget()
    splitter = main_splitter(left, right)
    assert splitter.widget(0) is left
    assert splitter.widget(1) is right
    assert splitter.childrenCollapsible() is False   # 側欄不可被拖到消失


def test_action_row_puts_primary_actions_on_the_right(qapp):
    scan, run, cancel = QPushButton(), QPushButton(), QPushButton()
    row = action_row([scan], [run, cancel])
    assert row.itemAt(0).widget() is scan
    assert row.itemAt(1).spacerItem() is not None
    assert row.itemAt(2).widget() is run
    assert row.itemAt(3).widget() is cancel


def test_page_layout_applies_shared_margins(qapp):
    layout = page_layout(QWidget())
    assert layout.contentsMargins().top() == MARGIN
    assert layout.spacing() == SPACING
```

在 `tests/test_theme.py` 檔尾加:

```python
def test_groupbox_title_is_emphasised_in_both_themes():
    """群組盒標題要有字重與留白,否則分組在視覺上等於沒發生。"""
    from ass_style_tool.qt.theme import qss_for
    for theme in ("dark", "light"):
        title_block = qss_for(theme).split("QGroupBox::title")[1].split("}")[0]
        assert "font-weight" in title_block
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd /c/Claude_code && py -m pytest tests/test_layout_helpers.py tests/test_theme.py -q
```

預期:`layout_helpers` collection error(模組不存在)+ `test_groupbox_title_is_emphasised_in_both_themes` FAILED

- [ ] **Step 3: 寫實作(layout_helpers)**

建立 `ass_style_tool/qt/layout_helpers.py`:

```python
"""分頁版面的共用建構器與間距常數(方案 C:右側設定側欄)。

三個工作分頁(字幕檔 / MKV / 封裝)採用同一個骨架:

    來源列(橫跨全寬)
    QSplitter(水平) → 左:清單或表格   右:設定側欄
    動作列(次要靠左 → 留白 → 主要靠右)
    進度列

把常數與建構器集中在這裡,而不是三個分頁各寫一份——三份平行的版面碼
很容易在日後只改一邊而慢慢分岔。
"""
from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLayout, QSplitter,
                               QVBoxLayout, QWidget)

MARGIN = 12              # 分頁最外層外距
SPACING = 10             # 主要區塊之間
GROUP_SPACING = 8        # 群組盒內部
SIDEBAR_MIN_WIDTH = 240  # 設定側欄:塞得下 ScalePanel 與語言下拉的下限


def page_layout(widget: QWidget) -> QVBoxLayout:
    """分頁最外層的垂直版面,統一外距與間距。"""
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
    layout.setSpacing(SPACING)
    return layout


def group(title: str, inner: QLayout) -> QGroupBox:
    """把一段版面包成有標題的群組盒(統一內距與間距)。"""
    inner.setContentsMargins(GROUP_SPACING, GROUP_SPACING,
                             GROUP_SPACING, GROUP_SPACING)
    inner.setSpacing(GROUP_SPACING)
    box = QGroupBox(title)
    box.setLayout(inner)
    return box


def settings_sidebar(*groups: QWidget) -> QWidget:
    """右側設定側欄:群組盒由上而下排,底部留白讓它們保持自然高度。"""
    panel = QWidget()
    column = QVBoxLayout(panel)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(SPACING)
    for box in groups:
        column.addWidget(box)
    column.addStretch(1)
    panel.setMinimumWidth(SIDEBAR_MIN_WIDTH)
    return panel


def main_splitter(main_area: QWidget, sidebar: QWidget) -> QSplitter:
    """左清單 / 右側欄。左邊拿三倍伸縮權重,側欄不隨視窗放大而變胖。"""
    splitter = QSplitter(Qt.Horizontal)
    splitter.addWidget(main_area)
    splitter.addWidget(sidebar)
    splitter.setStretchFactor(0, 3)
    splitter.setStretchFactor(1, 1)
    splitter.setChildrenCollapsible(False)
    return splitter


def action_row(secondary: Sequence[QWidget],
               primary: Sequence[QWidget]) -> QHBoxLayout:
    """動作列:次要動作靠左,主要動作與取消靠右。"""
    row = QHBoxLayout()
    for button in secondary:
        row.addWidget(button)
    row.addStretch(1)
    for button in primary:
        row.addWidget(button)
    return row
```

- [ ] **Step 4: 寫實作(theme QGroupBox)**

`ass_style_tool/qt/theme.py`,把 `_QSS_TEMPLATE` 裡的 QGroupBox 段落(第 125-132 行)換成:

```
QGroupBox {
    border: 1px solid $border; border-radius: 4px;
    margin-top: 14px; padding-top: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 10px; padding: 0 6px; color: $text_dim;
    font-weight: 600;
}
```

**不要動任何 `$` 配色欄位**——只有 margin-top、padding-top、border-radius、left、padding、font-weight 這幾個數值改變。

- [ ] **Step 5: 跑測試確認通過**

```bash
cd /c/Claude_code && py -m pytest tests/test_layout_helpers.py tests/test_theme.py -q
```

預期:全部 passed

- [ ] **Step 6: 跑全套測試**

```bash
cd /c/Claude_code && py -m pytest tests -q
```

預期:`440 passed`

- [ ] **Step 7: Commit**

```bash
cd /c/Claude_code && git add ass_style_tool/qt/layout_helpers.py ass_style_tool/qt/theme.py tests/test_layout_helpers.py tests/test_theme.py && git commit -m "Add shared layout helpers and emphasise group box titles"
```

---

## Task 5: ScalePanel 改單欄版面

**Files:**
- Modify: `ass_style_tool/qt/scale_panel.py`(整個 `__init__`)
- Test: `tests/test_scale_gui.py`(加一個測試)

**Interfaces:**
- Consumes: `layout_helpers.SIDEBAR_MIN_WIDTH`(僅測試用)
- Produces: `ScalePanel` 的公開屬性與 `get_options()` 完全不變(`factor_radio`、`factor_edit`、`target_radio`、`target_edit`、`base_edit`、`deco_check`、`inline_check`、`fscxy_check`)

- [ ] **Step 1: 寫失敗的測試**

在 `tests/test_scale_gui.py` 的既有 ScalePanel 測試之後加:

```python
def test_scale_panel_fits_the_settings_sidebar(qapp):
    """單欄版面:面板寬度要塞得進 240px 的設定側欄。

    原本是 4 欄 QGridLayout(倍率、基準 Style、三個核取方塊橫排),
    在側欄裡會把整個分頁撐寬。
    """
    from ass_style_tool.qt.layout_helpers import SIDEBAR_MIN_WIDTH
    from ass_style_tool.qt.scale_panel import ScalePanel
    panel = ScalePanel()
    assert panel.sizeHint().width() <= SIDEBAR_MIN_WIDTH
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd /c/Claude_code && py -m pytest tests/test_scale_gui.py -q
```

預期:`test_scale_panel_fits_the_settings_sidebar` FAILED(sizeHint 寬度超過 240)

- [ ] **Step 3: 寫實作**

把 `ass_style_tool/qt/scale_panel.py` 整個檔案換成:

```python
"""縮放字級模式的參數面板(單欄版面,塞得進 240px 的設定側欄)。"""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit,
                               QRadioButton, QVBoxLayout, QWidget)

from ..scale_engine import ScaleError, ScaleOptions


class ScalePanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 4)
        root.setSpacing(6)

        factor_row = QHBoxLayout()
        self.factor_radio = QRadioButton("倍率 ×")
        self.factor_radio.setChecked(True)
        self.factor_edit = QLineEdit("1.25")
        self.factor_edit.setMaximumWidth(80)
        factor_row.addWidget(self.factor_radio)
        factor_row.addWidget(self.factor_edit)
        factor_row.addStretch(1)
        root.addLayout(factor_row)

        target_row = QHBoxLayout()
        self.target_radio = QRadioButton("主 Style 設為")
        self.target_edit = QLineEdit("72")
        self.target_edit.setMaximumWidth(80)
        target_row.addWidget(self.target_radio)
        target_row.addWidget(self.target_edit)
        target_row.addStretch(1)
        root.addLayout(target_row)

        base_row = QHBoxLayout()
        base_row.addWidget(QLabel("基準 Style"))
        self.base_edit = QLineEdit("Default")
        base_row.addWidget(self.base_edit, 1)
        root.addLayout(base_row)

        self.deco_check = QCheckBox("同步縮放外框/陰影")
        self.deco_check.setChecked(True)
        self.inline_check = QCheckBox("縮放對白內 \\fs")
        self.inline_check.setChecked(True)
        # 標題縮短、細節移到 tooltip:側欄只有 240px,長標籤會把分頁撐寬
        self.fscxy_check = QCheckBox("同步縮放 \\fscx/\\fscy")
        self.fscxy_check.setToolTip("會改變字幅比例")
        for check in (self.deco_check, self.inline_check, self.fscxy_check):
            root.addWidget(check)

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

- [ ] **Step 4: 跑測試確認通過**

```bash
cd /c/Claude_code && py -m pytest tests/test_scale_gui.py -q
```

預期:`9 passed`

若 `test_scale_panel_fits_the_settings_sidebar` 仍失敗,把最寬的核取方塊標籤再縮短、細節移到 `setToolTip`;**不要**改測試裡的 240 門檻。

- [ ] **Step 5: 跑全套測試**

```bash
cd /c/Claude_code && py -m pytest tests -q
```

預期:`441 passed`

- [ ] **Step 6: Commit**

```bash
cd /c/Claude_code && git add ass_style_tool/qt/scale_panel.py tests/test_scale_gui.py && git commit -m "Lay out ScalePanel in a single column so it fits the sidebar"
```

---

## Task 6: 字幕檔分頁改用方案 C

**Files:**
- Modify: `ass_style_tool/qt/subtitle_tab.py:42-127`(整個版面建構)、`:326-339`(設定持久化)
- Test: `tests/test_subtitle_tab.py`

**Interfaces:**
- Consumes: `layout_helpers` 的 `page_layout` / `group` / `settings_sidebar` / `main_splitter` / `action_row`
- Produces: `SubtitleFileTab.splitter`(QSplitter);其餘公開屬性不變

- [ ] **Step 1: 寫失敗的測試**

在 `tests/test_subtitle_tab.py` 檔尾加。注意這個檔案**沒有** `_tab()` 建構輔助函式(不同於 `test_mkv_tab.py` / `test_mux_tab.py`),每個測試自己 import 並建構 —— 下面的測試沿用該檔既有的寫法,不要為此新增 helper:

```python
def test_settings_live_in_the_sidebar_not_under_the_table(qapp):
    """方案 C:設定控件在分隔器右側的側欄裡,不再堆在表格下方搶垂直空間。"""
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    assert tab.splitter.widget(0) is tab.table
    sidebar = tab.splitter.widget(1)
    for widget in (tab.apply_mode_radio, tab.scale_mode_radio, tab.scale_panel,
                   tab.inplace_radio, tab.outdir_radio, tab.outdir_edit):
        assert sidebar.isAncestorOf(widget), f"{widget} 不在設定側欄裡"


def test_save_settings_records_splitter_state(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    tab.save_settings(settings)
    assert settings.value("subtitle/splitter") is not None


def test_restore_settings_without_saved_splitter_is_safe(qapp, tmp_path):
    """沒存過分隔器狀態時不得把 None 丟給 restoreState。"""
    from PySide6.QtCore import QSettings
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values
    settings = QSettings(str(tmp_path / "empty.ini"), QSettings.Format.IniFormat)
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    tab.restore_settings(settings)      # 不可拋例外
    assert tab.splitter.count() == 2
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd /c/Claude_code && py -m pytest tests/test_subtitle_tab.py -q
```

預期:三個新測試 FAILED(`AttributeError: 'SubtitleFileTab' object has no attribute 'splitter'`)

- [ ] **Step 3: 寫實作(版面)**

`ass_style_tool/qt/subtitle_tab.py`:在 import 區加

```python
from .layout_helpers import (action_row, group, main_splitter, page_layout,
                             settings_sidebar)
```

把 `__init__` 裡從 `root = QVBoxLayout(self)`(第 42 行)到 `root.addWidget(self.progress)`(第 127 行)之間**整段**換成:

```python
        root = page_layout(self)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("資料夾:"))
        self.folder_edit = QLineEdit()
        # 貼上/輸入路徑後(Enter 或失焦)自動掃描
        self.folder_edit.editingFinished.connect(self._auto_scan)
        folder_row.addWidget(self.folder_edit, 1)
        browse = QPushButton("瀏覽…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(browse)
        root.addLayout(folder_row)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)

        # ----- 設定側欄:操作模式 -----
        mode_box = QVBoxLayout()
        self.apply_mode_radio = QRadioButton("套用樣式")
        self.apply_mode_radio.setChecked(True)
        self.scale_mode_radio = QRadioButton("縮放字級")
        mode_box.addWidget(self.apply_mode_radio)
        mode_box.addWidget(self.scale_mode_radio)
        self.scale_panel = ScalePanel()
        self.scale_panel.setHidden(True)
        mode_box.addWidget(self.scale_panel)
        self.scale_mode_radio.toggled.connect(self._on_mode_changed)

        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.apply_mode_radio)
        self._mode_group.addButton(self.scale_mode_radio)

        # ----- 設定側欄:輸出 -----
        out_box = QVBoxLayout()
        self.inplace_radio = QRadioButton("原地覆蓋(備份 .bak)")
        self.inplace_radio.setChecked(True)
        self.outdir_radio = QRadioButton("輸出到資料夾")
        out_box.addWidget(self.inplace_radio)
        out_box.addWidget(self.outdir_radio)
        outdir_row = QHBoxLayout()
        self.outdir_edit = QLineEdit()
        out_browse = QPushButton("…")
        out_browse.setMaximumWidth(32)
        out_browse.clicked.connect(self._browse_out)
        outdir_row.addWidget(self.outdir_edit, 1)
        outdir_row.addWidget(out_browse)
        out_box.addLayout(outdir_row)

        self._output_group = QButtonGroup(self)
        self._output_group.addButton(self.inplace_radio)
        self._output_group.addButton(self.outdir_radio)

        self.splitter = main_splitter(
            self.table,
            settings_sidebar(group("操作模式", mode_box),
                             group("輸出", out_box)))
        root.addWidget(self.splitter, 1)

        self.scan_button = QPushButton("重新掃描")
        self.scan_button.clicked.connect(self._on_scan)
        self.dry_run_button = QPushButton("試算預覽(不寫檔)")
        self.dry_run_button.setEnabled(False)
        self.dry_run_button.clicked.connect(self._on_dry_run)
        self.open_out_button = QPushButton("開啟輸出資料夾")
        self.open_out_button.clicked.connect(self._open_output)
        self.run_button = QPushButton("開始套用樣式")
        self.run_button.setProperty("accent", True)
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._on_run)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        root.addLayout(action_row(
            [self.scan_button, self.dry_run_button, self.open_out_button],
            [self.run_button, self.cancel_button]))

        self.progress = QProgressBar()
        root.addWidget(self.progress)
```

`QVBoxLayout` 已在既有 import 中,不需另外加。

- [ ] **Step 4: 寫實作(分隔器持久化)**

把 `save_settings` / `restore_settings`(第 326-339 行)換成:

```python
    def save_settings(self, settings: QSettings) -> None:
        settings.setValue("subtitle/folder", self.folder_edit.text())
        settings.setValue(
            "subtitle/output_mode",
            "outdir" if self.outdir_radio.isChecked() else "inplace")
        settings.setValue("subtitle/outdir", self.outdir_edit.text())
        settings.setValue("subtitle/splitter", self.splitter.saveState())

    def restore_settings(self, settings: QSettings) -> None:
        self.folder_edit.setText(settings.value("subtitle/folder", ""))
        self.outdir_edit.setText(settings.value("subtitle/outdir", ""))
        if settings.value("subtitle/output_mode", "inplace") == "outdir":
            self.outdir_radio.setChecked(True)
        else:
            self.inplace_radio.setChecked(True)
        state = settings.value("subtitle/splitter")
        if state is not None:
            self.splitter.restoreState(state)
```

- [ ] **Step 5: 跑測試確認通過**

```bash
cd /c/Claude_code && py -m pytest tests/test_subtitle_tab.py tests/test_scale_gui.py tests/test_main_window.py -q
```

預期:全部 passed

- [ ] **Step 6: 跑全套測試**

```bash
cd /c/Claude_code && py -m pytest tests -q
```

預期:`444 passed`

- [ ] **Step 7: Commit**

```bash
cd /c/Claude_code && git add ass_style_tool/qt/subtitle_tab.py tests/test_subtitle_tab.py && git commit -m "Move subtitle tab settings into a right-hand sidebar"
```

---

## Task 7: 封裝分頁改用方案 C

**Files:**
- Modify: `ass_style_tool/qt/mux_tab.py:63-189`(整個版面建構)、`:529-544`(設定持久化)
- Test: `tests/test_mux_tab.py`

**Interfaces:**
- Consumes: `layout_helpers`
- Produces: `MuxTab.splitter`;其餘公開屬性不變(含 `modify_tracks_button`)

- [ ] **Step 1: 寫失敗的測試**

在 `tests/test_mux_tab.py` 檔尾加(`_tab(monkeypatch)` 是該檔既有的建構輔助函式):

```python
def test_settings_live_in_the_sidebar_not_under_the_table(qapp, monkeypatch):
    """方案 C:封裝分頁原本 9 條裸露橫列把表格擠成兩三列高,設定改進側欄。"""
    tab = _tab(monkeypatch)
    assert tab.splitter.widget(0) is tab.table
    sidebar = tab.splitter.widget(1)
    for widget in (tab.direct_mode_radio, tab.apply_mode_radio,
                   tab.scale_mode_radio, tab.scale_panel,
                   tab.language_combo, tab.trackname_edit,
                   tab.default_check, tab.forced_check,
                   tab.modify_tracks_button,
                   tab.outdir_radio, tab.outdir_edit, tab.replace_radio):
        assert sidebar.isAncestorOf(widget), f"{widget} 不在設定側欄裡"


def test_save_settings_records_splitter_state(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    tab = _tab(monkeypatch)
    tab.save_settings(settings)
    assert settings.value("mux/splitter") is not None


def test_restore_settings_without_saved_splitter_is_safe(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "empty.ini"), QSettings.Format.IniFormat)
    tab = _tab(monkeypatch)
    tab.restore_settings(settings)      # 不可拋例外
    assert tab.splitter.count() == 2
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd /c/Claude_code && py -m pytest tests/test_mux_tab.py -q
```

預期:三個新測試 FAILED(`AttributeError: ... 'splitter'`)

- [ ] **Step 3: 寫實作(版面)**

`ass_style_tool/qt/mux_tab.py`:在 import 區加

```python
from .layout_helpers import (action_row, group, main_splitter, page_layout,
                             settings_sidebar)
```

把 `__init__` 裡從 `root = QVBoxLayout(self)`(第 63 行)到 `b.setEnabled(False)`(第 189 行)之間**整段**換成:

```python
        root = page_layout(self)
        if not self.tools_available:
            warn = QLabel("⚠ 找不到 mkvmerge:請安裝 MKVToolNix 後重新啟動"
                          "(封裝功能已停用)")
            warn.setStyleSheet("QLabel { color: #d08a00; }")
            root.addWidget(warn)

        vrow = QHBoxLayout()
        vrow.addWidget(QLabel("影片資料夾:"))
        self.video_edit = QLineEdit()
        self.video_edit.editingFinished.connect(self._auto_scan)
        vrow.addWidget(self.video_edit, 1)
        vbrowse = QPushButton("瀏覽…")
        vbrowse.clicked.connect(self._browse_video)
        vrow.addWidget(vbrowse)
        root.addLayout(vrow)

        srow = QHBoxLayout()
        srow.addWidget(QLabel("字幕資料夾:"))
        self.subtitle_edit = QLineEdit()
        self.subtitle_edit.editingFinished.connect(self._auto_scan)
        srow.addWidget(self.subtitle_edit, 1)
        sbrowse = QPushButton("瀏覽…")
        sbrowse.clicked.connect(self._browse_subtitle)
        srow.addWidget(sbrowse)
        root.addLayout(srow)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

        # ----- 側欄:封裝前處理 -----
        pre_box = QVBoxLayout()
        self.direct_mode_radio = QRadioButton("原字幕直接封")
        self.direct_mode_radio.setChecked(True)
        self.apply_mode_radio = QRadioButton("先套用目前樣式")
        self.scale_mode_radio = QRadioButton("先縮放字級")
        for radio in (self.direct_mode_radio, self.apply_mode_radio,
                      self.scale_mode_radio):
            pre_box.addWidget(radio)
        self.scale_panel = ScalePanel()
        self.scale_panel.setHidden(True)
        pre_box.addWidget(self.scale_panel)
        self.scale_mode_radio.toggled.connect(
            lambda on: self.scale_panel.setHidden(not on))

        self._preprocess_group = QButtonGroup(self)
        for radio in (self.direct_mode_radio, self.apply_mode_radio,
                      self.scale_mode_radio):
            self._preprocess_group.addButton(radio)

        # ----- 側欄:新字幕軌 -----
        meta_box = QVBoxLayout()
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("語言"))
        self.language_combo = QComboBox()
        for label, code in _LANGUAGES:
            self.language_combo.addItem(f"{label} ({code})", code)
        lang_row.addWidget(self.language_combo, 1)
        meta_box.addLayout(lang_row)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("軌名"))
        self.trackname_edit = QLineEdit()
        name_row.addWidget(self.trackname_edit, 1)
        meta_box.addLayout(name_row)
        flag_row = QHBoxLayout()
        self.default_check = QCheckBox("預設軌")
        self.forced_check = QCheckBox("強制軌")
        flag_row.addWidget(self.default_check)
        flag_row.addWidget(self.forced_check)
        flag_row.addStretch(1)
        meta_box.addLayout(flag_row)

        # ----- 側欄:既有軌道 -----
        old_box = QVBoxLayout()
        self.modify_tracks_button = QPushButton("修改既有軌道…")
        self.modify_tracks_button.setEnabled(False)
        self.modify_tracks_button.clicked.connect(self._on_modify_tracks)
        old_box.addWidget(self.modify_tracks_button)

        # ----- 側欄:輸出 -----
        out_box = QVBoxLayout()
        self.outdir_radio = QRadioButton("輸出到資料夾")
        self.outdir_radio.setChecked(True)
        out_box.addWidget(self.outdir_radio)
        outdir_row = QHBoxLayout()
        self.outdir_edit = QLineEdit()
        out_browse = QPushButton("…")
        out_browse.setMaximumWidth(32)
        out_browse.clicked.connect(self._browse_out)
        outdir_row.addWidget(self.outdir_edit, 1)
        outdir_row.addWidget(out_browse)
        out_box.addLayout(outdir_row)
        self.replace_radio = QRadioButton("取代原影片(驗證後覆蓋)")
        out_box.addWidget(self.replace_radio)

        self._output_group = QButtonGroup(self)
        self._output_group.addButton(self.outdir_radio)
        self._output_group.addButton(self.replace_radio)

        self.splitter = main_splitter(
            self.table,
            settings_sidebar(group("封裝前處理", pre_box),
                             group("新字幕軌", meta_box),
                             group("既有軌道", old_box),
                             group("輸出", out_box)))
        root.addWidget(self.splitter, 1)

        self.scan_button = QPushButton("重新掃描")
        self.scan_button.clicked.connect(self._on_scan)
        self.run_button = QPushButton("開始封裝")
        self.run_button.setProperty("accent", True)
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._on_run)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        root.addLayout(action_row([self.scan_button],
                                  [self.run_button, self.cancel_button]))

        prow = QHBoxLayout()
        self.progress = QProgressBar()
        self.file_progress = QProgressBar()
        self.file_progress.setRange(0, 100)
        prow.addWidget(QLabel("整批:"))
        prow.addWidget(self.progress, 2)
        prow.addWidget(QLabel("當前檔:"))
        prow.addWidget(self.file_progress, 1)
        root.addLayout(prow)

        if not self.tools_available:
            for b in (self.scan_button, self.run_button,
                      self.modify_tracks_button):
                b.setEnabled(False)
```

注意警告標籤的 `setStyleSheet` 已加上 `QLabel` 型別選擇器(原本是裸的 `color: #d08a00;`,會往下傳給子孫控件)。

- [ ] **Step 4: 寫實作(分隔器持久化)**

把 `save_settings` / `restore_settings`(第 529-544 行)換成:

```python
    def save_settings(self, settings: QSettings) -> None:
        settings.setValue("mux/video_folder", self.video_edit.text())
        settings.setValue("mux/subtitle_folder", self.subtitle_edit.text())
        settings.setValue(
            "mux/output_mode",
            "replace" if self.replace_radio.isChecked() else "outdir")
        settings.setValue("mux/outdir", self.outdir_edit.text())
        settings.setValue("mux/splitter", self.splitter.saveState())

    def restore_settings(self, settings: QSettings) -> None:
        self.video_edit.setText(settings.value("mux/video_folder", ""))
        self.subtitle_edit.setText(settings.value("mux/subtitle_folder", ""))
        self.outdir_edit.setText(settings.value("mux/outdir", ""))
        if settings.value("mux/output_mode", "outdir") == "replace":
            self.replace_radio.setChecked(True)
        else:
            self.outdir_radio.setChecked(True)
        state = settings.value("mux/splitter")
        if state is not None:
            self.splitter.restoreState(state)
```

- [ ] **Step 5: 跑測試確認通過**

```bash
cd /c/Claude_code && py -m pytest tests/test_mux_tab.py tests/test_modify_tracks_dialog.py tests/test_main_window.py -q
```

預期:全部 passed

- [ ] **Step 6: 跑全套測試**

```bash
cd /c/Claude_code && py -m pytest tests -q
```

預期:`447 passed`

- [ ] **Step 7: Commit**

```bash
cd /c/Claude_code && git add ass_style_tool/qt/mux_tab.py tests/test_mux_tab.py && git commit -m "Move mux tab settings into a right-hand sidebar"
```

---

## Task 8:「修改既有軌道」對話框(MKV 分頁)

**Files:**
- Create: `ass_style_tool/qt/select_tracks_dialog.py`
- Test: `tests/test_select_tracks_dialog.py`

**Interfaces:**
- Consumes: `track_select.build_select_info_rows` / `uncovered_track_count` / `TrackKey`、`mkv_batch.track_key`、`mkv_io.SubtitleTrack`
- Produces: `SelectTracksDialog(files_tracks: Dict[Path, List[SubtitleTrack]], existing: Optional[Set[TrackKey]] = None, parent=None)`,方法 `get_keys() -> Set[TrackKey]`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/test_select_tracks_dialog.py`:

```python
from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_io import SubtitleTrack
from ass_style_tool.qt.select_tracks_dialog import SelectTracksDialog


def _track(tid, lang="chi", name="繁中"):
    return SubtitleTrack(tid, "S_TEXT/ASS", lang, name, False, False)


FILES = {
    Path("e1.mkv"): [_track(2, "chi", "繁中"), _track(3, "chi", "简中")],
    Path("e2.mkv"): [_track(5, "chi", "简中"), _track(7, "chi", "繁中")],
    Path("e3.mkv"): [_track(1, "jpn", "")],
}


def test_defaults_to_every_track_checked(qapp):
    """existing=None 代表從未設定過:維持舊行為(掃完全部勾起來)。"""
    dialog = SelectTracksDialog(FILES)
    assert dialog.get_keys() == {("chi", "繁中"), ("chi", "简中")}


def test_prefills_from_existing_selection(qapp):
    dialog = SelectTracksDialog(FILES, existing={("chi", "繁中")})
    assert dialog.get_keys() == {("chi", "繁中")}


def test_unchecking_removes_the_key(qapp):
    dialog = SelectTracksDialog(FILES)
    dialog._checks[1].setChecked(False)      # 範本檔的第二列(简中)
    assert dialog.get_keys() == {("chi", "繁中")}


def test_template_skips_files_with_no_ass_tracks(qapp):
    """排最前面的檔案讀不到軌時不能讓整個對話框空白(否則按確定會清光設定)。"""
    files = {
        Path("a_broken.mkv"): [],
        Path("b_good.mkv"): [_track(4, "chi", "繁中")],
    }
    dialog = SelectTracksDialog(files)
    assert [t.track_id for t in dialog._tracks] == [4]
    assert dialog.get_keys() == {("chi", "繁中")}


def test_no_tracks_at_all_yields_empty_selection(qapp):
    dialog = SelectTracksDialog({Path("a.mkv"): []})
    assert dialog._tracks == []
    assert dialog.get_keys() == set()


def test_info_table_marks_found_missing_and_multiple(qapp):
    files = {
        Path("a.mkv"): [_track(2, "chi", "繁中"), _track(3, "chi", "繁中")],
        Path("b.mkv"): [_track(4, "chi", "繁中")],
        Path("c.mkv"): [_track(9, "jpn", "")],
    }
    dialog = SelectTracksDialog(files)
    dialog.table.selectRow(0)                # 範本 a.mkv 的第一列(繁中)
    texts = [dialog.info_table.item(r, 1).text()
             for r in range(dialog.info_table.rowCount())]
    assert texts[0].startswith("⚠")          # a.mkv 有兩條符合
    assert "軌 2" in texts[0] and "軌 3" in texts[0]
    assert texts[1] == "✓ 軌 4"
    assert texts[2] == "✗ 沒有符合的軌"


def test_summary_warns_about_tracks_no_rule_covers(qapp):
    """範本檔沒有的軌會被靜默略過——數字必須講出來。"""
    dialog = SelectTracksDialog(FILES)        # 範本 e1 沒有 jpn 軌
    assert "1 部影片" in dialog.summary.text()
    assert "1 條" in dialog.summary.text()


def test_summary_is_empty_when_everything_is_covered(qapp):
    files = {Path("a.mkv"): [_track(2, "chi", "繁中")],
             Path("b.mkv"): [_track(5, "chi", "繁中")]}
    assert SelectTracksDialog(files).summary.text() == ""


def test_summary_updates_when_a_track_is_unchecked(qapp):
    files = {Path("a.mkv"): [_track(2, "chi", "繁中"), _track(3, "chi", "简中")]}
    dialog = SelectTracksDialog(files)
    assert dialog.summary.text() == ""
    dialog._checks[1].setChecked(False)
    assert "1 條" in dialog.summary.text()
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd /c/Claude_code && py -m pytest tests/test_select_tracks_dialog.py -q
```

預期:collection error,`ModuleNotFoundError: ... select_tracks_dialog`

- [ ] **Step 3: 寫實作**

建立 `ass_style_tool/qt/select_tracks_dialog.py`:

```python
"""「修改既有軌道」對話框(MKV 分頁):選出哪幾條舊字幕軌要重新套樣式。

刻意與封裝分頁的 ModifyTracksDialog 同一種心智模型——上半在範本檔上定
規則、下半逐檔驗證。差別在這裡的鍵是 (語言, 軌名) 而不是軌 ID:同一季裡
某集多一條音訊軌就會把字幕軌的 ID 推掉,依 ID 會套到別的語言上。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Set

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog,
                               QDialogButtonBox, QHBoxLayout, QHeaderView,
                               QLabel, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..mkv_batch import track_key
from ..mkv_io import SubtitleTrack
from ..track_select import (TrackKey, build_select_info_rows,
                            uncovered_track_count)

_COLS = ["套樣式", "軌 ID", "語言", "軌名"]
_INFO_COLS = ["影片", "解析結果"]


class SelectTracksDialog(QDialog):
    def __init__(self, files_tracks: Dict[Path, List[SubtitleTrack]],
                 existing: Optional[Set[TrackKey]] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("修改既有軌道")
        self._files_tracks = dict(files_tracks)
        # 範本取排序後、實際有 ASS 字幕軌的第一個檔案:跳過讀不到軌的壞檔,
        # 否則剛好排最前面的那個壞檔會讓對話框空白,按確定後清光所有設定。
        first = next(
            (p for p in sorted(self._files_tracks, key=lambda p: p.name)
             if self._files_tracks[p]),
            None)
        self._tracks: List[SubtitleTrack] = (
            list(self._files_tracks[first]) if first is not None else [])
        self._checks: List[QCheckBox] = []

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "勾選要重新套用樣式的字幕軌。規則依「語言 + 軌名」套用到整批影片。"))

        self.table = QTableWidget(len(self._tracks), len(_COLS))
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch)
        for r, track in enumerate(self._tracks):
            check = QCheckBox()
            # existing 為 None = 從未設定過 -> 預設全勾(維持舊行為:掃完
            # 全部勾起來,想排除哪條再自己取消)
            check.setChecked(True if existing is None
                             else track_key(track) in existing)
            check.toggled.connect(self._refresh_summary)
            self.table.setCellWidget(r, 0, self._center(check))
            self._checks.append(check)
            self.table.setItem(r, 1, QTableWidgetItem(str(track.track_id)))
            self.table.setItem(r, 2, QTableWidgetItem(track.language or "und"))
            self.table.setItem(r, 3, QTableWidgetItem(track.track_name or "-"))
        root.addWidget(self.table)

        self.info_table = QTableWidget(0, len(_INFO_COLS))
        self.info_table.setHorizontalHeaderLabels(_INFO_COLS)
        self.info_table.setAlternatingRowColors(True)
        self.info_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.info_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.info_table.verticalHeader().setVisible(False)
        self.info_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        root.addWidget(self.info_table)
        self.table.itemSelectionChanged.connect(self._refresh_info_table)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        if self._tracks:
            self.table.selectRow(0)      # 開啟時就有內容
        self._refresh_info_table()
        self._refresh_summary()

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _center(self, w: QWidget) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("QWidget { background: transparent; }")
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(w)
        return wrap

    def _selected_track(self) -> Optional[SubtitleTrack]:
        row = self.table.currentRow()
        if 0 <= row < len(self._tracks):
            return self._tracks[row]
        return None

    def _refresh_info_table(self) -> None:
        track = self._selected_track()
        if track is None:
            self.info_table.setRowCount(0)
            return
        rows = build_select_info_rows(track_key(track), self._files_tracks)
        self.info_table.setRowCount(len(rows))
        for r, info in enumerate(rows):
            if not info.track_ids:
                text = "✗ 沒有符合的軌"
            elif len(info.track_ids) == 1:
                text = f"✓ 軌 {info.track_ids[0]}"
            else:
                # 這正是面板要讓使用者看見的情況:同一個鍵命中多條軌
                ids = "、".join(f"軌 {i}" for i in info.track_ids)
                text = f"⚠ 有 {len(info.track_ids)} 條符合({ids}),都會套用"
            self.info_table.setItem(r, 0, QTableWidgetItem(info.video_name))
            self.info_table.setItem(r, 1, QTableWidgetItem(text))

    def _refresh_summary(self) -> None:
        videos, tracks = uncovered_track_count(self.get_keys(),
                                               self._files_tracks)
        self.summary.setText(
            "" if not tracks else
            f"⚠ {videos} 部影片另有 {tracks} 條未勾選的 ASS 字幕軌,不會被套用")

    def get_keys(self) -> Set[TrackKey]:
        return {track_key(track)
                for track, check in zip(self._tracks, self._checks)
                if check.isChecked()}
```

- [ ] **Step 4: 跑測試確認通過**

```bash
cd /c/Claude_code && py -m pytest tests/test_select_tracks_dialog.py -q
```

預期:`9 passed`

- [ ] **Step 5: 跑全套測試**

```bash
cd /c/Claude_code && py -m pytest tests -q
```

預期:`456 passed`

- [ ] **Step 6: Commit**

```bash
cd /c/Claude_code && git add ass_style_tool/qt/select_tracks_dialog.py tests/test_select_tracks_dialog.py && git commit -m "Add SelectTracksDialog for picking which old subtitle tracks get restyled"
```

---

## Task 9: MKV 分頁改寫(清單 + 對話框接線 + 方案 C)

**Files:**
- Modify: `ass_style_tool/qt/mkv_tab.py`(整個檔案重寫)
- Modify: `ass_style_tool/mkv_batch.py:30-38`(刪除 `select_same_type`)
- Test: `tests/test_mkv_tab.py`(重寫)
- Test: `tests/test_mkv_batch.py`(刪除 `select_same_type` 的兩個測試與 import)

**Interfaces:**
- Consumes: `track_select.resolve_tracks` / `all_keys`、`select_tracks_dialog.SelectTracksDialog`、`layout_helpers`、`batch_worker.MkvScanWorker`(已改吃 list)
- Produces: `MkvTab` 的新公開介面 —— `file_table`(QTableWidget)、`splitter`、`modify_tracks_button`、`populate(files: List[Path])`、`checked_files() -> List[Path]`、`current_jobs() -> List[Tuple[Path, List[SubtitleTrack]]]`;`MkvTab(get_profile)` 建構簽章不變(`main_window` 不需改)

- [ ] **Step 1: 寫失敗的測試**

把 `tests/test_mkv_tab.py` 整個檔案換成:

```python
from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_io import SubtitleTrack
from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values


def _track(tid, lang="chi", name="繁中"):
    return SubtitleTrack(tid, "S_TEXT/ASS", lang, name, False, False)


def _tab(monkeypatch, available=True):
    fake = (lambda: Path("x.exe")) if available else (lambda: None)
    monkeypatch.setattr("ass_style_tool.qt.mkv_tab.mkvmerge_path", fake)
    monkeypatch.setattr("ass_style_tool.qt.mkv_tab.mkvextract_path", fake)
    from ass_style_tool.qt.mkv_tab import MkvTab
    return MkvTab(lambda: profile_from_values(DEFAULT_VALUES))


FILES = [Path("e1.mkv"), Path("e2.mkv"), Path("e3.mkv")]

TRACKS = {
    Path("e1.mkv"): [_track(2, "chi", "繁中"), _track(3, "chi", "简中")],
    Path("e2.mkv"): [_track(5, "chi", "简中"), _track(7, "chi", "繁中")],
    Path("e3.mkv"): [],
}


# ---------- 主畫面只列檔案 ----------

def test_populate_lists_files_all_checked(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    assert tab.file_table.rowCount() == 3
    assert [tab.file_table.item(r, 0).text() for r in range(3)] == [
        "e1.mkv", "e2.mkv", "e3.mkv"]
    assert all(tab.file_table.item(r, 0).checkState() == Qt.CheckState.Checked
               for r in range(3))
    assert tab.checked_files() == FILES


def test_track_column_is_blank_before_any_track_scan(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    assert [tab.file_table.item(r, 1).text() for r in range(3)] == ["", "", ""]


def test_checked_files_respects_unchecking(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab.file_table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    assert tab.checked_files() == [Path("e1.mkv"), Path("e3.mkv")]


# ---------- 規則解析 ----------

def test_jobs_use_every_ass_track_when_no_rule_was_set(qapp, monkeypatch):
    """從未開過對話框 = 所有 ASS 字幕軌都套(維持舊的預設行為)。"""
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)
    jobs = dict(tab.current_jobs())
    assert {t.track_id for t in jobs[Path("e1.mkv")]} == {2, 3}
    assert {t.track_id for t in jobs[Path("e2.mkv")]} == {5, 7}
    assert Path("e3.mkv") not in jobs        # 無軌檔不成 job


def test_jobs_follow_the_selected_rule_across_files(qapp, monkeypatch):
    """規則依語言+軌名,不是軌 ID:e1 的繁中是軌 2,e2 的繁中是軌 7。"""
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)
    tab._track_keys = {("chi", "繁中")}
    jobs = dict(tab.current_jobs())
    assert {t.track_id for t in jobs[Path("e1.mkv")]} == {2}
    assert {t.track_id for t in jobs[Path("e2.mkv")]} == {7}


def test_track_column_shows_resolution_per_file(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)
    tab._track_keys = {("chi", "繁中")}
    tab._refresh_track_column()
    assert tab.file_table.item(0, 1).text() == "✓ 軌 2"
    assert tab.file_table.item(1, 1).text() == "✓ 軌 7"
    assert tab.file_table.item(2, 1).text() == "✗ 無符合的軌"


def test_track_column_flags_multiple_matches(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate([Path("e1.mkv")])
    tab._files_tracks = {
        Path("e1.mkv"): [_track(2, "und", ""), _track(3, "und", "")]}
    tab._track_keys = {("und", "")}
    tab._refresh_track_column()
    assert tab.file_table.item(0, 1).text() == "⚠ 軌 2、軌 3"


def test_rescan_clears_the_previous_rule(qapp, monkeypatch, tmp_path):
    """換資料夾後舊規則必須失效——軌 ID 與軌組成都可能完全不同。"""
    tab = _tab(monkeypatch)
    (tmp_path / "a.mkv").write_bytes(b"")
    tab._files_tracks = dict(TRACKS)
    tab._track_keys = {("chi", "繁中")}
    tab.folder_edit.setText(str(tmp_path))
    tab._on_scan()
    assert tab._track_keys is None
    assert tab._files_tracks == {}
    assert tab.modify_tracks_button.text() == "修改既有軌道…"


def test_modify_button_shows_the_selected_count(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab._apply_keys({("chi", "繁中"), ("chi", "简中")})
    assert tab.modify_tracks_button.text() == "修改既有軌道…(已選 2 條)"


# ---------- 掃描資料夾只列檔案,不跑外部程序 ----------

def test_scan_lists_mkv_files_without_running_mkvmerge(qapp, monkeypatch, tmp_path):
    """回歸:選資料夾不應該對每個檔跑一次 mkvmerge -J。"""
    from ass_style_tool.qt import mkv_tab as mkv_tab_module
    started = []
    monkeypatch.setattr(mkv_tab_module, "MkvScanWorker",
                        lambda *a, **k: started.append(1))
    (tmp_path / "e1.mkv").write_bytes(b"")
    (tmp_path / "e2.mkv").write_bytes(b"")
    (tmp_path / "note.txt").write_text("x")
    tab = _tab(monkeypatch)
    tab.folder_edit.setText(str(tmp_path))
    tab._on_scan()
    assert started == []
    assert tab.file_table.rowCount() == 2


def test_scan_ignores_subfolders(qapp, monkeypatch, tmp_path):
    (tmp_path / "e1.mkv").write_bytes(b"")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "e2.mkv").write_bytes(b"")
    tab = _tab(monkeypatch)
    tab.folder_edit.setText(str(tmp_path))
    tab._on_scan()
    assert [tab.file_table.item(r, 0).text()
            for r in range(tab.file_table.rowCount())] == ["e1.mkv"]


# ---------- 掃軌完成後的分派 ----------

def test_track_scan_done_opens_the_dialog(qapp, monkeypatch):
    opened = []
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    monkeypatch.setattr(tab, "_open_select_dialog",
                        lambda: opened.append(1))
    tab._pending_action = "dialog"
    tab._on_track_scan_done(TRACKS)
    assert opened == [1]
    assert tab._files_tracks == TRACKS


def test_track_scan_done_starts_the_batch(qapp, monkeypatch):
    started = []
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    monkeypatch.setattr(tab, "_start_batch", lambda: started.append(1))
    tab._pending_action = "run"
    tab._on_track_scan_done(TRACKS)
    assert started == [1]


def test_track_scan_cancelled_does_neither(qapp, monkeypatch):
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    calls = []
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    monkeypatch.setattr(tab, "_open_select_dialog", lambda: calls.append("d"))
    monkeypatch.setattr(tab, "_start_batch", lambda: calls.append("r"))
    tab._pending_action = "run"
    tab._scan_dialog = ScanProgressDialog(tab)
    tab._on_track_scan_cancelled()
    assert calls == []
    assert tab._scan_dialog is None
    assert tab._pending_action is None


# ---------- 既有控件與行為 ----------

def test_mode_switch_toggles_scale_panel(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.scale_panel.isHidden() is True
    tab.scale_mode_radio.setChecked(True)
    assert tab.scale_panel.isHidden() is False


def test_tools_missing_disables_controls(qapp, monkeypatch):
    tab = _tab(monkeypatch, available=False)
    assert tab.tools_available is False
    assert tab.scan_button.isEnabled() is False
    assert tab.run_button.isEnabled() is False
    assert tab.modify_tracks_button.isEnabled() is False


def test_run_button_enabled_after_populate(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.run_button.isEnabled() is False
    tab.populate(FILES)
    assert tab.run_button.isEnabled() is True


def test_radio_groups_do_not_interfere(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.scale_mode_radio.setChecked(True)
    tab.replace_radio.setChecked(True)
    assert tab.scale_mode_radio.isChecked() is True
    tab.outdir_radio.setChecked(True)
    assert tab.scale_mode_radio.isChecked() is True


def test_file_table_has_alternating_rows(qapp, monkeypatch):
    # QSS 的 alternate-background-color 只有在控件端開啟時才生效
    tab = _tab(monkeypatch)
    assert tab.file_table.alternatingRowColors() is True


def test_run_button_tagged_accent(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.run_button.property("accent") is True


# ---------- 自動掃描 ----------

def test_auto_scan_triggers_on_folder_chosen(qapp, monkeypatch, tmp_path):
    tab = _tab(monkeypatch)
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab._folder_chosen(str(tmp_path))
    assert calls == [1]
    assert tab.folder_edit.text() == str(tmp_path)


def test_auto_scan_skips_same_folder(qapp, monkeypatch, tmp_path):
    tab = _tab(monkeypatch)
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab._scanned_folder = str(tmp_path)
    tab.folder_edit.setText(str(tmp_path))
    tab._auto_scan()
    assert calls == []


def test_auto_scan_skips_when_tools_missing(qapp, monkeypatch, tmp_path):
    tab = _tab(monkeypatch, available=False)
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab._folder_chosen(str(tmp_path))
    assert calls == []


def test_auto_scan_skips_during_run(qapp, monkeypatch, tmp_path):
    tab = _tab(monkeypatch)
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab._thread = object()
    tab._folder_chosen(str(tmp_path))
    assert calls == []


# ---------- 版面方案 C ----------

def test_settings_live_in_the_sidebar_not_under_the_list(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.splitter.widget(0) is tab.file_table
    sidebar = tab.splitter.widget(1)
    for widget in (tab.apply_mode_radio, tab.scale_mode_radio, tab.scale_panel,
                   tab.modify_tracks_button, tab.outdir_radio, tab.outdir_edit,
                   tab.replace_radio):
        assert sidebar.isAncestorOf(widget), f"{widget} 不在設定側欄裡"


# ---------- 設定持久化 ----------

def test_save_and_restore_settings_roundtrip(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab_a = _tab(monkeypatch)
    tab_a.folder_edit.setText(r"C:\mkv\show")
    tab_a.replace_radio.setChecked(True)
    tab_a.outdir_edit.setText(r"C:\mkv\out")
    tab_a.save_settings(settings)

    tab_b = _tab(monkeypatch)
    tab_b.restore_settings(settings)
    assert tab_b.folder_edit.text() == r"C:\mkv\show"
    assert tab_b.replace_radio.isChecked() is True
    assert tab_b.outdir_edit.text() == r"C:\mkv\out"


def test_save_settings_records_splitter_state(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    tab = _tab(monkeypatch)
    tab.save_settings(settings)
    assert settings.value("mkv/splitter") is not None


def test_restore_settings_without_saved_splitter_is_safe(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "empty.ini"), QSettings.Format.IniFormat)
    tab = _tab(monkeypatch)
    tab.restore_settings(settings)
    assert tab.splitter.count() == 2


def test_restore_settings_does_not_trigger_scan(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    settings.setValue("mkv/folder", str(tmp_path))
    settings.setValue("mkv/output_mode", "outdir")
    settings.setValue("mkv/outdir", "")

    tab = _tab(monkeypatch)
    tab.restore_settings(settings)
    assert tab._scanned_folder is None


def test_restore_settings_defaults_outdir_when_unset(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    tab = _tab(monkeypatch)
    tab.restore_settings(settings)
    assert tab.folder_edit.text() == ""
    assert tab.outdir_radio.isChecked() is True


# ---------- 取消掃描與關閉分頁(既有回歸,路徑改成掃軌) ----------

def test_dialog_cancel_actually_aborts_track_scan(qapp, monkeypatch, tmp_path):
    """重點測試:走真正的使用者路徑(對話框 Cancel/Esc/X)取消掃軌。

    本檔其餘測試全是單執行緒的同步呼叫,這正是這類 bug 完全不會被抓到的
    原因:signal→worker slot 的連線在 worker 已 moveToThread 後會被 Qt
    解析成 queued connection,而 worker 所在的執行緒在 run() 執行期間不跑
    事件迴圈,queued 的 cancel() 因此完全不會被處理。

    這裡不自建 worker/thread,而是讓 MkvTab 自己的接線建立真正的 QThread。
    """
    import time

    from ass_style_tool.qt.batch_worker import MkvScanWorker

    calls = []

    def slow_list_fn(path, mkvmerge):
        calls.append(path)
        time.sleep(0.05)
        return []

    def factory(paths, mkvmerge, list_fn=None):
        return MkvScanWorker(paths, mkvmerge, list_fn=slow_list_fn)

    monkeypatch.setattr("ass_style_tool.qt.mkv_tab.MkvScanWorker", factory)

    total_files = 20
    for i in range(total_files):
        (tmp_path / f"e{i:02d}.mkv").write_bytes(b"")

    tab = _tab(monkeypatch)
    tab.folder_edit.setText(str(tmp_path))
    tab._on_scan()
    assert tab.file_table.rowCount() == total_files
    tab._on_modify_tracks()
    thread = tab._scan_thread
    try:
        deadline = time.monotonic() + 5.0
        while not calls and time.monotonic() < deadline:
            qapp.processEvents()
        assert calls, "worker 在逾時內未開始掃描(環境問題,非本測試目的)"

        # 使用者按下 Cancel/Esc/X -> dialog.reject() -> cancelled 訊號
        # -> _request_scan_cancel -> 直接呼叫 worker.cancel()
        tab._scan_dialog.reject()

        deadline = time.monotonic() + 5.0
        while tab._scan_thread is not None and time.monotonic() < deadline:
            qapp.processEvents()

        assert len(calls) < total_files, (
            f"掃描未被中止:{len(calls)}/{total_files} 個檔案已掃描")
        assert tab._files_tracks == {}, "取消後的掃描結果仍被採用"
    finally:
        if thread is not None:
            thread.quit()
            thread.wait(3000)


def test_shutdown_closes_orphaned_scan_dialog(qapp, monkeypatch):
    """掃描中途關閉整個分頁時,shutdown() 要把模態的 ScanProgressDialog
    真的關掉——打包版是 console=False,主視窗關閉後 quitOnLastWindowClosed
    因為這個還可見的對話框永遠不成立,process 會卡著不退出。"""
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    tab = _tab(monkeypatch)
    dialog = ScanProgressDialog(tab)
    dialog.show()
    tab._scan_dialog = dialog
    assert dialog.isVisible() is True

    tab.shutdown()

    assert dialog.isVisible() is False
    assert tab._scan_dialog is None
    assert tab._scan_thread is None
    assert tab._scan_worker is None
```

同時修改 `tests/test_mkv_batch.py`:

- 把第 8-10 行的 import 改成(移除 `select_same_type`):

```python
from ass_style_tool.mkv_batch import (MkvFileReport, MkvTools, process_mkv,
                                      track_key, transform_track_file)
```

- 刪除 `test_select_same_type_matches_by_lang_and_name`(第 28-38 行)與 `test_select_same_type_multiple_reference`(第 41-44 行)。`test_track_key` 保留。

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd /c/Claude_code && py -m pytest tests/test_mkv_tab.py -q
```

預期:大量 FAILED(`AttributeError: 'MkvTab' object has no attribute 'file_table'` 等)

- [ ] **Step 3: 刪除 select_same_type**

`ass_style_tool/mkv_batch.py`,刪除第 30-38 行的整個 `select_same_type` 函式,並把上方的區段註解(第 23 行)從

```python
# ---------- 一鍵選整季同類型軌 ----------
```

改成

```python
# ---------- 軌道比對鍵 ----------
```

`track_key` 保留——它現在是 `track_select` 的規則鍵函式。同時把 `Set` 從第 15 行的 typing import 移除(不再有使用者):

```python
from typing import Callable, Dict, List, Optional, Tuple
```

- [ ] **Step 4: 寫實作(mkv_tab 整檔重寫)**

把 `ass_style_tool/qt/mkv_tab.py` 整個檔案換成:

```python
"""「MKV」分頁:列出資料夾內的 MKV、用規則選定要重新套樣式的舊字幕軌、批次重封裝。

分頁主畫面只列檔案。「要對哪幾條舊字幕軌套樣式」由「修改既有軌道…」對話框
控制:在範本檔上勾選,規則以 (語言, 軌名) 套用到整批影片。mkvmerge -J 只在
真的需要軌道資訊時才跑(開對話框、或尚未設定規則就按開始處理),選資料夾
本身不跑任何外部程序。
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import Qt, QSettings, QThread, Signal
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QFileDialog,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QRadioButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..mkv_batch import MkvTools, track_key
from ..mkv_io import SubtitleTrack, extract_track
from ..profile import Profile
from ..scale_engine import ScaleError
from ..tools import mkvextract_path, mkvmerge_path
from ..track_select import TrackKey, resolve_tracks
from .batch_worker import MkvScanWorker, MkvWorker
from .layout_helpers import (action_row, group, main_splitter, page_layout,
                             settings_sidebar)
from .scale_panel import ScalePanel
from .scan_progress_dialog import ScanProgressDialog
from .select_tracks_dialog import SelectTracksDialog

_HEADERS = ["MKV", "將套用的軌"]


class MkvTab(QWidget):
    log = Signal(str)
    preview_requested = Signal(object, object)  # (暫存字幕路徑, MKV 路徑)

    def __init__(self, get_profile: Callable[[], Profile]) -> None:
        super().__init__()
        self._get_profile = get_profile
        self._files: List[Path] = []
        self._files_tracks: Dict[Path, List[SubtitleTrack]] = {}
        self._track_keys: Optional[Set[TrackKey]] = None  # None = 從未設定
        self._pending_action: Optional[str] = None        # "dialog" | "run"
        self._thread: Optional[QThread] = None
        self._worker = None
        self._scan_thread: Optional[QThread] = None
        self._scan_worker = None
        self._scan_dialog: Optional[ScanProgressDialog] = None
        self._scanned_folder: Optional[str] = None
        self._closing = False
        self._preview_dir = Path(tempfile.mkdtemp(prefix="ass_mkv_preview_"))
        self.setAcceptDrops(True)

        mkvmerge = mkvmerge_path()
        mkvextract = mkvextract_path()
        self.tools_available = mkvmerge is not None and mkvextract is not None
        self._tools = (MkvTools(mkvmerge, mkvextract)
                       if self.tools_available else None)

        root = page_layout(self)

        if not self.tools_available:
            warn = QLabel("⚠ 找不到 mkvmerge/mkvextract:請安裝 MKVToolNix "
                          "後重新啟動(功能已停用,不影響其他分頁)")
            warn.setStyleSheet("QLabel { color: #d08a00; }")
            root.addWidget(warn)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("資料夾:"))
        self.folder_edit = QLineEdit()
        # 貼上/輸入路徑後(Enter 或失焦)自動掃描
        self.folder_edit.editingFinished.connect(self._auto_scan)
        folder_row.addWidget(self.folder_edit, 1)
        browse = QPushButton("瀏覽…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(browse)
        root.addLayout(folder_row)

        self.file_table = QTableWidget(0, len(_HEADERS))
        self.file_table.setAlternatingRowColors(True)
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.file_table.setHorizontalHeaderLabels(_HEADERS)
        self.file_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)

        # ----- 側欄:操作模式 -----
        mode_box = QVBoxLayout()
        self.apply_mode_radio = QRadioButton("套用樣式")
        self.apply_mode_radio.setChecked(True)
        self.scale_mode_radio = QRadioButton("縮放字級")
        mode_box.addWidget(self.apply_mode_radio)
        mode_box.addWidget(self.scale_mode_radio)
        self.scale_panel = ScalePanel()
        self.scale_panel.setHidden(True)
        mode_box.addWidget(self.scale_panel)
        self.scale_mode_radio.toggled.connect(
            lambda on: self.scale_panel.setHidden(not on))

        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.apply_mode_radio)
        self._mode_group.addButton(self.scale_mode_radio)

        # ----- 側欄:字幕軌 -----
        track_box = QVBoxLayout()
        self.modify_tracks_button = QPushButton("修改既有軌道…")
        self.modify_tracks_button.clicked.connect(self._on_modify_tracks)
        track_box.addWidget(self.modify_tracks_button)
        self.preview_button = QPushButton("送進預覽")
        self.preview_button.clicked.connect(self._on_send_preview)
        track_box.addWidget(self.preview_button)

        # ----- 側欄:輸出 -----
        out_box = QVBoxLayout()
        self.outdir_radio = QRadioButton("輸出到資料夾")
        self.outdir_radio.setChecked(True)
        out_box.addWidget(self.outdir_radio)
        outdir_row = QHBoxLayout()
        self.outdir_edit = QLineEdit()
        out_browse = QPushButton("…")
        out_browse.setMaximumWidth(32)
        out_browse.clicked.connect(self._browse_out)
        outdir_row.addWidget(self.outdir_edit, 1)
        outdir_row.addWidget(out_browse)
        out_box.addLayout(outdir_row)
        self.replace_radio = QRadioButton("取代原檔(驗證後覆蓋,不留備份)")
        out_box.addWidget(self.replace_radio)

        self._output_group = QButtonGroup(self)
        self._output_group.addButton(self.outdir_radio)
        self._output_group.addButton(self.replace_radio)

        self.splitter = main_splitter(
            self.file_table,
            settings_sidebar(group("操作模式", mode_box),
                             group("字幕軌", track_box),
                             group("輸出", out_box)))
        root.addWidget(self.splitter, 1)

        self.scan_button = QPushButton("重新掃描")
        self.scan_button.clicked.connect(self._on_scan)
        self.run_button = QPushButton("開始處理")
        self.run_button.setProperty("accent", True)
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._on_run)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        root.addLayout(action_row([self.scan_button],
                                  [self.run_button, self.cancel_button]))

        progress_row = QHBoxLayout()
        self.progress = QProgressBar()          # 整批
        self.file_progress = QProgressBar()     # 當前檔 mkvmerge %
        self.file_progress.setRange(0, 100)
        progress_row.addWidget(QLabel("整批:"))
        progress_row.addWidget(self.progress, 2)
        progress_row.addWidget(QLabel("當前檔:"))
        progress_row.addWidget(self.file_progress, 1)
        root.addLayout(progress_row)

        if not self.tools_available:
            for b in (self.scan_button, self.modify_tracks_button,
                      self.preview_button, self.run_button):
                b.setEnabled(False)

    # ---------- 拖放 / 檔案選擇 ----------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and Path(path).is_dir():
                self._folder_chosen(path)
                break

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇含 MKV 的資料夾")
        if path:
            self._folder_chosen(path)

    def _folder_chosen(self, path: str) -> None:
        """選好資料夾(瀏覽/拖放)→ 設定路徑並自動掃描。"""
        self.folder_edit.setText(path)
        self._auto_scan()

    def _auto_scan(self) -> None:
        """資料夾有效且與上次不同、無掃描/批次進行中、工具齊全時自動掃描。"""
        if not self.tools_available:
            return
        folder = self.folder_edit.text().strip()
        if (not folder or not Path(folder).is_dir()
                or folder == self._scanned_folder):
            return
        if self._scan_thread is not None or self._thread is not None:
            return
        self._on_scan()

    def _browse_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇輸出資料夾")
        if path:
            self.outdir_edit.setText(path)
            self.outdir_radio.setChecked(True)

    # ---------- 列檔(同步,不跑外部程序) ----------
    def _on_scan(self) -> None:
        if self._thread is not None:
            self.log.emit("批次處理進行中,請稍後再掃描")
            return
        folder = self.folder_edit.text().strip()
        if not folder or not Path(folder).is_dir():
            self.log.emit("請先選擇有效的資料夾")
            return
        self._scanned_folder = folder
        # 只掃當層。掃到軌道資訊要等使用者按「修改既有軌道…」或直接開始處理。
        files = sorted(p for p in Path(folder).glob("*.mkv") if p.is_file())
        self._files_tracks = {}
        self._apply_keys(None)
        self.populate(files)
        self.log.emit(f"找到 {len(files)} 個 MKV")

    def populate(self, files: List[Path]) -> None:
        self._files = list(files)
        self.file_table.setRowCount(len(self._files))
        for row, path in enumerate(self._files):
            name = QTableWidgetItem(path.name)
            name.setFlags(name.flags() | Qt.ItemIsUserCheckable)
            name.setCheckState(Qt.CheckState.Checked)
            self.file_table.setItem(row, 0, name)
            self.file_table.setItem(row, 1, QTableWidgetItem(""))
        self._refresh_track_column()
        if self._thread is None:
            self.run_button.setEnabled(bool(self._files)
                                       and self.tools_available)

    def checked_files(self) -> List[Path]:
        return [path for row, path in enumerate(self._files)
                if self.file_table.item(row, 0).checkState()
                == Qt.CheckState.Checked]

    # ---------- 規則 ----------
    def _apply_keys(self, keys: Optional[Set[TrackKey]]) -> None:
        """設定(或清除)規則,並同步按鈕文字與清單的「將套用的軌」欄。"""
        self._track_keys = keys
        self.modify_tracks_button.setText(
            "修改既有軌道…" if keys is None
            else f"修改既有軌道…(已選 {len(keys)} 條)")
        self._refresh_track_column()

    def _tracks_for(self, path: Path) -> Optional[List[SubtitleTrack]]:
        """該檔依目前規則要套用的軌;尚未掃過軌時回 None。"""
        tracks = self._files_tracks.get(path)
        if tracks is None:
            return None
        if self._track_keys is None:
            return list(tracks)
        return [t for t in tracks if track_key(t) in self._track_keys]

    def _refresh_track_column(self) -> None:
        for row, path in enumerate(self._files):
            picked = self._tracks_for(path)
            if picked is None:
                text = ""
            elif not picked:
                text = "✗ 無符合的軌"
            elif len(picked) == 1:
                text = f"✓ 軌 {picked[0].track_id}"
            else:
                text = "⚠ " + "、".join(f"軌 {t.track_id}" for t in picked)
            item = self.file_table.item(row, 1)
            if item is not None:
                item.setText(text)

    def current_jobs(self) -> List[Tuple[Path, List[SubtitleTrack]]]:
        """已勾選檔案依目前規則解析出的 (檔案, 軌清單);無軌者不列入。"""
        available = {p: self._files_tracks[p] for p in self.checked_files()
                     if p in self._files_tracks}
        if self._track_keys is None:
            resolved = {p: list(ts) for p, ts in available.items() if ts}
        else:
            resolved = resolve_tracks(self._track_keys, available)
        return sorted(resolved.items())

    # ---------- 掃軌(唯一會跑 mkvmerge -J 的路徑) ----------
    def _needs_track_scan(self) -> bool:
        return any(p not in self._files_tracks for p in self.checked_files())

    def _start_track_scan(self, pending: str) -> None:
        if self._scan_thread is not None:
            self.log.emit("軌道掃描進行中")
            return
        files = self.checked_files()
        if not files:
            self.log.emit("沒有勾選任何 MKV")
            return
        self._pending_action = pending
        self.scan_button.setEnabled(False)
        self._scan_thread = QThread()
        self._scan_worker = MkvScanWorker(files, self._tools.mkvmerge)
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_track_scan_done)
        self._scan_worker.cancelled.connect(self._on_track_scan_cancelled)
        self._scan_dialog = ScanProgressDialog(self)
        self._scan_worker.progress.connect(self._scan_dialog.set_progress)
        self._scan_dialog.cancelled.connect(self._request_scan_cancel)
        self._scan_dialog.show()      # 非 exec():維持既有非同步流程
        self._scan_thread.start()

    def _request_scan_cancel(self) -> None:
        """直接呼叫 worker.cancel(),不用 signal→worker slot 的連線。

        worker 已 moveToThread,但該執行緒在 run() 執行期間不會跑事件迴圈,
        排隊的 cancel() 要等掃描結束才會被處理——等於完全沒有作用。
        """
        if self._scan_worker is not None:
            self._scan_worker.cancel()

    def _finish_scan(self) -> None:
        """完成/取消共用的收尾:關對話框、收執行緒、恢復掃描鈕。"""
        if self._scan_dialog is not None:
            self._scan_dialog.hide()
            self._scan_dialog.deleteLater()
            self._scan_dialog = None
        if self._scan_thread is not None:
            self._scan_thread.quit()
            self._scan_thread.wait()
        self._scan_thread = None
        self._scan_worker = None
        self.scan_button.setEnabled(True)

    def _on_track_scan_done(self, files_tracks: dict) -> None:
        if self._closing:
            return
        pending = self._pending_action
        self._pending_action = None
        self._finish_scan()
        self._files_tracks.update(files_tracks)
        self._refresh_track_column()
        total = sum(len(v) for v in files_tracks.values())
        self.log.emit(f"掃描完成:{len(files_tracks)} 個 MKV,"
                      f"共 {total} 條 ASS 字幕軌")
        if pending == "dialog":
            self._open_select_dialog()
        elif pending == "run":
            self._start_batch()

    def _on_track_scan_cancelled(self) -> None:
        if self._closing:
            return
        # 取消 = 兩條路都不繼續:不開對話框、不啟動批次,已勾選的清單與
        # 上次的規則都保持原狀。
        self._pending_action = None
        self._finish_scan()
        self.log.emit("軌道掃描已取消")

    # ---------- 選軌對話框 ----------
    def _on_modify_tracks(self) -> None:
        if self._needs_track_scan():
            self._start_track_scan("dialog")
            return
        if not self.checked_files():
            self.log.emit("沒有勾選任何 MKV")
            return
        self._open_select_dialog()

    def _open_select_dialog(self) -> None:
        available = {p: self._files_tracks[p] for p in self.checked_files()
                     if p in self._files_tracks}
        if not any(available.values()):
            self.log.emit("所有勾選的 MKV 都讀不到 ASS 字幕軌")
            return
        dialog = SelectTracksDialog(available, self._track_keys, self)
        if dialog.exec():
            self._apply_keys(dialog.get_keys())

    # ---------- 送進預覽 ----------
    def _current_file(self) -> Optional[Path]:
        row = self.file_table.currentRow()
        if 0 <= row < len(self._files):
            return self._files[row]
        return None

    def _on_send_preview(self) -> None:
        path = self._current_file()
        if path is None:
            self.log.emit("請先選取一個 MKV 檔")
            return
        picked = self._tracks_for(path)
        if picked is None:
            self.log.emit("這個檔還沒掃過字幕軌,請先按「修改既有軌道…」")
            return
        if not picked:
            self.log.emit("這個檔沒有符合目前選擇的字幕軌")
            return
        track = picked[0]
        temp = self._preview_dir / f"{path.stem}_track{track.track_id}.ass"
        if not extract_track(path, track.track_id, temp,
                             self._tools.mkvextract):
            self.log.emit(f"抽取軌 {track.track_id} 失敗,無法預覽")
            return
        self.preview_requested.emit(temp, path)

    # ---------- 執行 ----------
    def _output_dir(self) -> Optional[Path]:
        if self.replace_radio.isChecked():
            return None
        text = self.outdir_edit.text().strip()
        return Path(text) if text else None

    def _on_run(self) -> None:
        if self._scan_thread is not None or self._thread is not None:
            self.log.emit("掃描或處理進行中,請稍候")
            return
        if not self.checked_files():
            self.log.emit("沒有勾選任何 MKV")
            return
        if self._needs_track_scan():
            # 從沒開過對話框就直接按開始處理:先掃軌,掃完接著跑批次
            self._start_track_scan("run")
            return
        self._start_batch()

    def _start_batch(self) -> None:
        jobs = self.current_jobs()
        if not jobs:
            self.log.emit("沒有勾選任何字幕軌")
            return
        if self.scale_mode_radio.isChecked():
            try:
                operation = self.scale_panel.get_options()
            except ScaleError as exc:
                self.log.emit(f"參數錯誤: {exc}")
                return
        else:
            try:
                operation = self._get_profile()
            except ValueError as exc:
                self.log.emit(f"欄位錯誤: {exc}")
                return
        output_dir = self._output_dir()
        if self.outdir_radio.isChecked() and output_dir is None:
            self.log.emit("請先選擇輸出資料夾")
            return

        self.progress.setValue(0)
        self.file_progress.setValue(0)
        self.scan_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.modify_tracks_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        self._thread = QThread()
        self._worker = MkvWorker(jobs, operation, self._tools, output_dir)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_progress.connect(self.file_progress.setValue)
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
        self.log.emit(f"MKV 批次完成:成功 {ok},跳過 {skipped},錯誤 {error}")
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self.scan_button.setEnabled(True)
        self.run_button.setEnabled(True)
        self.modify_tracks_button.setEnabled(self.tools_available)
        self.cancel_button.setEnabled(False)

    # ---------- 清理 ----------
    def shutdown(self) -> None:
        self._closing = True
        for worker in (self._worker, self._scan_worker):
            if worker is not None:
                worker.cancel()
        for thread in (self._thread, self._scan_thread):
            if thread is not None:
                thread.quit()
                thread.wait()
        # 沒有這行的話,取消/掃描完成時開出的模態 ScanProgressDialog 會留在
        # 畫面上、_scan_dialog 也留著沒清——套件化的 console=False 版本裡,
        # 主視窗關閉後 quitOnLastWindowClosed 因為這個還可見的對話框而永遠
        # 不會成立,process 會卡著不退出。
        self._finish_scan()
        import shutil
        shutil.rmtree(self._preview_dir, ignore_errors=True)

    # ---------- 設定持久化 ----------
    def save_settings(self, settings: QSettings) -> None:
        settings.setValue("mkv/folder", self.folder_edit.text())
        settings.setValue(
            "mkv/output_mode",
            "replace" if self.replace_radio.isChecked() else "outdir")
        settings.setValue("mkv/outdir", self.outdir_edit.text())
        settings.setValue("mkv/splitter", self.splitter.saveState())

    def restore_settings(self, settings: QSettings) -> None:
        self.folder_edit.setText(settings.value("mkv/folder", ""))
        self.outdir_edit.setText(settings.value("mkv/outdir", ""))
        if settings.value("mkv/output_mode", "outdir") == "replace":
            self.replace_radio.setChecked(True)
        else:
            self.outdir_radio.setChecked(True)
        state = settings.value("mkv/splitter")
        if state is not None:
            self.splitter.restoreState(state)
```

- [ ] **Step 5: 跑測試確認通過**

```bash
cd /c/Claude_code && py -m pytest tests/test_mkv_tab.py tests/test_mkv_batch.py -q
```

預期:全部 passed

- [ ] **Step 6: mutation 檢查(必做)**

驗證取消掃軌的接線測試真的在守約束。把 `_start_track_scan` 裡的取消接線暫時改成 signal→worker slot 的壞寫法:

```python
        self._scan_dialog.cancelled.connect(self._scan_worker.cancel)
```

重跑:

```bash
cd /c/Claude_code && py -m pytest tests/test_mkv_tab.py::test_dialog_cancel_actually_aborts_track_scan -q
```

預期:**FAILED**(20/20 檔全掃完)。確認後把接線改回 `self._scan_dialog.cancelled.connect(self._request_scan_cancel)`。

- [ ] **Step 7: 跑全套測試**

```bash
cd /c/Claude_code && py -m pytest tests -q
```

預期:`464 passed`(456 − 23 個舊的 MKV 分頁測試 + 33 個新的 − 2 個 select_same_type 測試;數字若略有出入以執行結果為準,但**不得有 failed**)

- [ ] **Step 8: 手動冒煙測**

```bash
cd /c/Claude_code && py -m ass_style_tool
```

依序確認:

1. 四個分頁都能開,沒有例外
2. 三個工作分頁都是「來源列 → 左清單/右側欄 → 動作列 → 進度列」
3. MKV 分頁選一個含 MKV 的資料夾:**立刻**列出檔名(不該有等待),「將套用的軌」欄空白
4. 按「修改既有軌道…」:出現進度視窗 → 對話框,範本表格預設全勾,下半資訊面板有內容
5. 取消勾選一條 → 底部出現「⚠ N 部影片另有 M 條未勾選的 ASS 字幕軌」
6. 按確定 → 按鈕變成「修改既有軌道…(已選 N 條)」,清單的「將套用的軌」欄填入 ✓/✗/⚠
7. 拖曳分隔器改變側欄寬度 → 關閉程式 → 重開,寬度有還原
8. 切到深色與淺色主題各看一次,群組盒標題與邊框在兩個主題下都清楚可讀

- [ ] **Step 9: Commit**

```bash
cd /c/Claude_code && git add ass_style_tool/qt/mkv_tab.py ass_style_tool/mkv_batch.py tests/test_mkv_tab.py tests/test_mkv_batch.py && git commit -m "Rebuild the MKV tab around a file list and a track selection dialog"
```

---

## 完成後的最終驗證

- [ ] **全套測試**

```bash
cd /c/Claude_code && py -m pytest tests -q
```

- [ ] **連跑三次確認穩定**(Qt 測試對銷毀順序敏感)

```bash
cd /c/Claude_code && for i in 1 2 3; do py -m pytest tests -q | tail -1; done
```

- [ ] **最終全分支審查**:用最強模型(opus)做 merge-base 到 HEAD 的完整審查。

  這個專案的血淚教訓:per-task 審查常常全部通過,但最終全分支審查抓到真正的 Critical(已發生多次)。審查時**要實際跑 offscreen 探針驗證行為**,不要只讀程式碼說「看起來對」。本輪特別要驗證的三件事:

  1. **版面**:實際建構三個分頁並量測——設定控件真的在 `splitter.widget(1)` 的子孫裡、側欄最小寬度生效、`ScalePanel` 沒把分頁撐寬。
  2. **規則解析**:用真實形狀的假資料(某集軌 ID 被音訊軌推移)確認 `current_jobs()` 抓到的是正確語言的軌,而不是同一個 ID。
  3. **取消路徑**:重跑 Step 6 的 mutation 檢查,確認測試真的會因為壞接線而失敗。

---

## Self-Review

**Spec coverage:**

| Spec 段落 | 對應任務 |
|---|---|
| 第 1 部分 · 主畫面單層清單 + 將套用的軌欄 | Task 9 |
| 第 1 部分 · 選軌對話框(範本 + 逐檔面板 + 總結) | Task 8 |
| 第 1 部分 · 純邏輯層 `track_select.py` | Task 1 |
| 第 1 部分 · 掃軌時機與取消行為 | Task 3(worker)、Task 9(接線) |
| 第 1 部分 · 狀態管理與按鈕文字 | Task 9(`_apply_keys`) |
| 第 1 部分 · 送進預覽 | Task 9(`_on_send_preview`) |
| 第 1 部分 · 移除樹/一鍵選整季/`select_same_type` | Task 9 |
| 第 2 部分 · `find_files` 不遞迴 | Task 2 |
| 第 2 部分 · MKV 分頁不遞迴 | Task 3(過渡)、Task 9(最終) |
| 第 2 部分 · 保留檔名衝突保護 | 不改動即達成(三個 worker 的 `seen_basenames` 未被觸碰) |
| 第 3 部分 · 共同骨架與間距 | Task 4 |
| 第 3 部分 · 三分頁側欄內容 | Task 6 / 7 / 9 |
| 第 3 部分 · `ScalePanel` 單欄 | Task 5 |
| 第 3 部分 · 分隔器持久化 | Task 6 / 7 / 9 |
| 第 3 部分 · theme QGroupBox 微調 | Task 4 |
| 測試策略 · 新增測試檔 | Task 1 / 4 / 8 |
| 測試策略 · 既有測試遷移 | Task 2 / 3 / 9 |

無缺口。

**型別一致性:**`TrackKey` 在 Task 1 定義,Task 8、Task 9 沿用同一個名稱;`resolve_tracks` / `build_select_info_rows` / `uncovered_track_count` 的簽章在三個任務間一致;`MkvScanWorker(paths, mkvmerge, list_fn=...)` 在 Task 3 定案,Task 9 依此呼叫;`_apply_keys` / `_tracks_for` / `_refresh_track_column` / `current_jobs` 只在 Task 9 內部使用,測試與實作用同一組名稱。

**「樣式與預覽」分頁**未被任何任務觸碰,符合 spec 的範圍界線。
