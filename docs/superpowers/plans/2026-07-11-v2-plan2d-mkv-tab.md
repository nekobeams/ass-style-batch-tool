# v2 Plan 2d — MKV 分頁 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成「MKV」分頁——掃描資料夾列出每個 MKV 的 ASS 字幕軌(勾選)、一鍵選整季同類型軌、抽軌→套用樣式或縮放字級→重封裝(其他軌與字型附件原封保留)、輸出到新資料夾或取代原檔(驗證後覆蓋)、mkvmerge 進度、取消、以及「送進預覽」一鍵把 MKV+選定軌載入預覽分頁。

**Architecture:** `mkv_batch.py` 是純邏輯批次協調(單檔管線:抽取→轉換→重封裝→驗證取代),所有外部程序函式可注入,完整 TDD;`MkvWorker`/`MkvScanWorker` 是薄薄的 QThread 包裝;`qt/mkv_tab.py` 用 QTreeWidget(檔案→軌)呈現,操作模式沿用既有 ScalePanel 與 StyleEditor 的 profile。輸出檔名衝突保護直接內建於 worker(比照 BatchWorker/ScaleWorker 的既有 `seen_basenames` 模式)。

**Tech Stack:** PySide6、MKVToolNix(mkvmerge/mkvextract,經 `tools.py` 偵測)、pytest(offscreen Qt)。

**Spec:** `docs/superpowers/specs/2026-07-08-ass-style-tool-v2-design.md` 的「MKV 字幕軌處理」節(含 2026-07-11 增補:雙操作模式、送進預覽)

## Global Constraints

- 工作目錄/repo root:`C:\Claude_code`,git branch 由執行者依 subagent-driven 流程建立
- **環境重點**:`python` 是壞的 Windows Store stub,一律用 `py`:`py -m pytest tests -v`
- Python 3.9+ 相容;每個新模組頂端加 `from __future__ import annotations`
- **測試絕不可真的執行 mkvmerge/mkvextract**:`mkv_batch` 的外部程序函式全部以參數注入,測試傳假函式;worker 測試注入假 `process_fn`;GUI 測試用假軌道資料
- 重封裝語意沿用 `mkv_io.build_remux_command`(只排除被替換軌、還原旗標);**未修改的勾選軌以原抽出內容放回**(不可遺失)
- 取代原檔模式:寫同目錄暫存 → `mkvmerge -J` 重新解析驗證通過 → `os.replace` 覆蓋;任一步失敗保留原檔並回報錯誤、清理暫存
- 輸出資料夾模式:**內建 basename 衝突保護**(只在確認成功寫出後記名,重複名回報 error 跳過——比照 BatchWorker 既有模式)
- 單檔失敗不中斷整批;取消 = 當前檔案跑完後停止
- 缺 mkvmerge/mkvextract → 分頁顯示缺工具提示並停用控制,不閃退
- Qt 測試用既有 `tests/conftest.py` 的 offscreen `qapp` fixture
- 測試指令:`py -m pytest tests -v`(從 repo root;目前基準 191 passed)
- Commit 訊息用 conventional commits

### 既有介面(本計畫會用到,已實作且測試)

- `ass_style_tool.mkv_io`:`SubtitleTrack`(track_id, codec_id, language, track_name, default, forced)、`list_ass_tracks(mkv_path, mkvmerge) -> list[SubtitleTrack]`、`extract_track(mkv_path, track_id, out_path, mkvextract) -> bool`、`Replacement(track, styled_path)`、`remux(mkv_path, out_path, replacements, mkvmerge, progress_cb=None) -> bool`
- `ass_style_tool.tools`:`mkvmerge_path() -> Path|None`、`mkvextract_path() -> Path|None`
- `ass_style_tool.ass_style`:`load_subs/save_subs/apply_profile`
- `ass_style_tool.scale_engine`:`ScaleOptions`、`scale_file(path, options, out_path) -> ScaleReport`(report 有 style_changes/inline_fs_count)
- `ass_style_tool.profile.Profile`
- `qt.scale_panel.ScalePanel`(`get_options() -> ScaleOptions`,非法丟 ScaleError)
- `qt.main_window.MainWindow`:`_open_in_preview(sub_path, video_path)`(載入預覽並切分頁)、MKV 佔位分頁、`append_log`
- 測試輔助:`tests.test_ass_style.SAMPLE_ASS`、`tests.test_profile.make_profile`、`tests.test_profile_fields.DEFAULT_VALUES/profile_from_values`

## File Structure

```
ass_style_tool/
└── mkv_batch.py        # 純邏輯:track_key/select_same_type、transform_track_file、identify_ok、process_mkv
ass_style_tool/qt/
├── batch_worker.py     # (修改)附加 MkvScanWorker、MkvWorker
├── mkv_tab.py          # (新)MKV 分頁 UI
└── main_window.py      # (修改)接入 MkvTab
tests/
├── test_mkv_batch.py
├── test_mkv_worker.py
└── test_mkv_tab.py
```

---

### Task 1: mkv_batch.py — 批次協調純邏輯

**Files:**
- Create: `ass_style_tool/mkv_batch.py`
- Test: `tests/test_mkv_batch.py`

**Interfaces:**
- Consumes: `mkv_io.SubtitleTrack/Replacement/extract_track/remux`、`ass_style.load_subs/save_subs/apply_profile`、`scale_engine.ScaleOptions/scale_file`
- Produces:
  - `track_key(track) -> tuple[str, str]` —(language, track_name)
  - `select_same_type(reference: list[SubtitleTrack], files_tracks: dict[Path, list[SubtitleTrack]]) -> dict[Path, set[int]]` — 以 reference 的 key 集合挑出各檔對應軌 id
  - `transform_track_file(src: Path, dst: Path, operation) -> tuple[bool, list[str]]` — operation 為 `Profile` 或 `ScaleOptions`;回傳 (有修改?, 訊息);Profile 找不到目標 Style 回 (False, 訊息) 且不寫 dst
  - `identify_ok(mkv_path: Path, mkvmerge: Path) -> bool` — `mkvmerge -J` 可解析且有 tracks(取代原檔前的驗證;subprocess encoding utf-8)
  - `MkvTools` dataclass:`mkvmerge: Path, mkvextract: Path`
  - `MkvFileReport` dataclass:`mkv_path: Path, status: str, messages: list[str]`(status: ok|skipped|error)
  - `process_mkv(mkv_path, tracks, operation, tools, out_path=None, progress_cb=None, extract_fn=..., remux_fn=..., verify_fn=...) -> MkvFileReport` — 單檔完整管線;`out_path=None` 表取代原檔;外部程序函式可注入

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_mkv_batch.py`:

```python
from __future__ import annotations

from pathlib import Path

import pysubs2

from ass_style_tool.mkv_io import SubtitleTrack
from ass_style_tool.mkv_batch import (MkvFileReport, MkvTools, process_mkv,
                                      select_same_type, track_key,
                                      transform_track_file)
from ass_style_tool.scale_engine import ScaleOptions
from tests.test_ass_style import SAMPLE_ASS
from tests.test_profile import make_profile

TOOLS = MkvTools(mkvmerge=Path("mkvmerge.exe"), mkvextract=Path("mkvextract.exe"))


def _track(tid, lang="chi", name="繁中"):
    return SubtitleTrack(tid, "S_TEXT/ASS", lang, name, False, False)


# ---------- 一鍵選整季 ----------

def test_track_key():
    assert track_key(_track(2)) == ("chi", "繁中")


def test_select_same_type_matches_by_lang_and_name():
    reference = [_track(2, "chi", "繁中")]
    files = {
        Path("e1.mkv"): [_track(2, "chi", "繁中"), _track(3, "chi", "简中")],
        Path("e2.mkv"): [_track(5, "chi", "简中"), _track(7, "chi", "繁中")],
        Path("e3.mkv"): [_track(1, "jpn", "")],
    }
    result = select_same_type(reference, files)
    assert result[Path("e1.mkv")] == {2}
    assert result[Path("e2.mkv")] == {7}   # 依 key 而非軌號
    assert result[Path("e3.mkv")] == set()


def test_select_same_type_multiple_reference():
    reference = [_track(2, "chi", "繁中"), _track(3, "chi", "简中")]
    files = {Path("e1.mkv"): [_track(4, "chi", "简中"), _track(5, "chi", "繁中")]}
    assert select_same_type(reference, files)[Path("e1.mkv")] == {4, 5}


# ---------- transform_track_file ----------

def _write_ass(tmp_path, name="in.ass"):
    p = tmp_path / name
    p.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    return p


def test_transform_profile_modifies(tmp_path):
    src = _write_ass(tmp_path)
    dst = tmp_path / "out.ass"
    changed, msgs = transform_track_file(src, dst, make_profile())
    assert changed is True
    subs = pysubs2.SSAFile.from_string(dst.read_text(encoding="utf-8-sig"))
    assert subs.styles["Default"].fontname == "思源黑體 CN"


def test_transform_profile_missing_style_not_changed(tmp_path):
    src = _write_ass(tmp_path)
    dst = tmp_path / "out.ass"
    changed, msgs = transform_track_file(
        src, dst, make_profile(target_style_names=["沒有這個"]))
    assert changed is False
    assert not dst.exists()


def test_transform_scale(tmp_path):
    src = _write_ass(tmp_path)
    dst = tmp_path / "out.ass"
    changed, msgs = transform_track_file(src, dst, ScaleOptions(factor=2))
    assert changed is True
    assert "Style: Default,Arial,80," in dst.read_text(encoding="utf-8-sig")


# ---------- process_mkv ----------

def _fake_extract_ok(tmp_path):
    def fn(mkv, tid, out, mkvextract):
        Path(out).write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
        return True
    return fn


def test_process_mkv_outdir_ok(tmp_path):
    calls = {}

    def fake_remux(mkv, out, replacements, mkvmerge, progress_cb=None):
        calls["out"] = Path(out)
        calls["repl"] = replacements
        Path(out).write_bytes(b"fake mkv")
        if progress_cb:
            progress_cb(100)
        return True

    out = tmp_path / "outdir" / "show.mkv"
    report = process_mkv(
        Path("show.mkv"), [_track(2)], make_profile(), TOOLS,
        out_path=out,
        extract_fn=_fake_extract_ok(tmp_path), remux_fn=fake_remux)
    assert report.status == "ok"
    assert calls["out"] == out
    assert len(calls["repl"]) == 1
    assert calls["repl"][0].track.track_id == 2
    assert out.exists()


def test_process_mkv_unchanged_track_kept(tmp_path):
    """未修改的勾選軌以原抽出內容放回,不可遺失。"""
    seen = {}

    def fake_remux(mkv, out, replacements, mkvmerge, progress_cb=None):
        seen["repl"] = list(replacements)
        Path(out).write_bytes(b"x")
        return True

    profile = make_profile(target_style_names=["沒有這個"])
    report = process_mkv(
        Path("s.mkv"), [_track(2)], profile, TOOLS,
        out_path=tmp_path / "o.mkv",
        extract_fn=_fake_extract_ok(tmp_path), remux_fn=fake_remux)
    # 唯一勾選軌未被修改 → 無需重封裝,整檔 skipped
    assert report.status == "skipped"
    assert "repl" not in seen


def test_process_mkv_mixed_changed_and_unchanged(tmp_path):
    """兩軌其一有改:重封裝需包含兩軌(未改軌用原內容)。"""
    def fake_extract(mkv, tid, out, mkvextract):
        text = SAMPLE_ASS if tid == 2 else SAMPLE_ASS.replace(
            "Style: Default", "Style: Other")
        Path(out).write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
        return True

    seen = {}

    def fake_remux(mkv, out, replacements, mkvmerge, progress_cb=None):
        seen["ids"] = [r.track.track_id for r in replacements]
        Path(out).write_bytes(b"x")
        return True

    report = process_mkv(
        Path("s.mkv"), [_track(2), _track(3)], make_profile(), TOOLS,
        out_path=tmp_path / "o.mkv",
        extract_fn=fake_extract, remux_fn=fake_remux)
    assert report.status == "ok"
    assert sorted(seen["ids"]) == [2, 3]


def test_process_mkv_extract_fail_is_error(tmp_path):
    report = process_mkv(
        Path("s.mkv"), [_track(2)], make_profile(), TOOLS,
        out_path=tmp_path / "o.mkv",
        extract_fn=lambda *a: False,
        remux_fn=lambda *a, **k: True)
    assert report.status == "error"


def test_process_mkv_remux_fail_is_error(tmp_path):
    report = process_mkv(
        Path("s.mkv"), [_track(2)], make_profile(), TOOLS,
        out_path=tmp_path / "o.mkv",
        extract_fn=_fake_extract_ok(tmp_path),
        remux_fn=lambda *a, **k: False)
    assert report.status == "error"


def test_process_mkv_replace_original_verify_and_swap(tmp_path):
    original = tmp_path / "show.mkv"
    original.write_bytes(b"ORIGINAL")

    def fake_remux(mkv, out, replacements, mkvmerge, progress_cb=None):
        Path(out).write_bytes(b"NEW CONTENT")
        return True

    report = process_mkv(
        original, [_track(2)], make_profile(), TOOLS,
        out_path=None,                      # 取代原檔模式
        extract_fn=_fake_extract_ok(tmp_path),
        remux_fn=fake_remux,
        verify_fn=lambda p, m: True)
    assert report.status == "ok"
    assert original.read_bytes() == b"NEW CONTENT"   # 已覆蓋
    assert not original.with_name(original.name + ".tmp.mkv").exists()


def test_process_mkv_replace_original_verify_fail_keeps_original(tmp_path):
    original = tmp_path / "show.mkv"
    original.write_bytes(b"ORIGINAL")

    def fake_remux(mkv, out, replacements, mkvmerge, progress_cb=None):
        Path(out).write_bytes(b"BROKEN")
        return True

    report = process_mkv(
        original, [_track(2)], make_profile(), TOOLS,
        out_path=None,
        extract_fn=_fake_extract_ok(tmp_path),
        remux_fn=fake_remux,
        verify_fn=lambda p, m: False)       # 驗證失敗
    assert report.status == "error"
    assert original.read_bytes() == b"ORIGINAL"      # 原檔保留
    assert not original.with_name(original.name + ".tmp.mkv").exists()  # 暫存已清
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_mkv_batch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.mkv_batch'`

- [ ] **Step 3: 實作 mkv_batch.py**

建立 `ass_style_tool/mkv_batch.py`:

```python
"""MKV 批次協調(純邏輯):單檔管線 抽取→轉換→重封裝→(驗證取代)。

外部程序(mkvextract/mkvmerge/驗證)一律以函式參數注入,預設綁定
mkv_io 的實作;測試注入假函式,不真的執行外部程式。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from .ass_style import apply_profile, load_subs, save_subs
from .mkv_io import Replacement, SubtitleTrack, extract_track, remux
from .profile import Profile
from .scale_engine import ScaleOptions, scale_file


# ---------- 一鍵選整季同類型軌 ----------

def track_key(track: SubtitleTrack) -> Tuple[str, str]:
    """同類型軌的比對鍵:(語言, 軌名)。"""
    return (track.language, track.track_name)


def select_same_type(
    reference: List[SubtitleTrack],
    files_tracks: Dict[Path, List[SubtitleTrack]],
) -> Dict[Path, Set[int]]:
    keys = {track_key(t) for t in reference}
    return {
        path: {t.track_id for t in tracks if track_key(t) in keys}
        for path, tracks in files_tracks.items()
    }


# ---------- 單軌轉換 ----------

def transform_track_file(src: Path, dst: Path, operation) -> Tuple[bool, List[str]]:
    """把 operation(Profile 或 ScaleOptions)套用到 src,寫出 dst。

    回傳 (有修改?, 訊息)。未修改時不寫 dst(呼叫端用原檔放回)。
    """
    if isinstance(operation, ScaleOptions):
        report = scale_file(src, operation, dst)
        msgs = [f"{c.name}: {c.old_size} → {c.new_size}"
                for c in report.style_changes]
        msgs.append(f"inline \\fs 修改 {report.inline_fs_count} 處"
                    f"(倍率 {report.factor_used:.3f})")
        changed = bool(report.style_changes) or report.inline_fs_count > 0
        return changed, msgs
    subs = load_subs(src)
    modified = apply_profile(subs, operation)
    if not modified:
        return False, ["找不到目標 Style,未修改"]
    save_subs(subs, dst)
    return True, [f"已套用樣式到: {', '.join(modified)}"]


# ---------- 取代原檔前的驗證 ----------

def identify_ok(mkv_path: Path, mkvmerge: Path) -> bool:
    """輸出檔可被 mkvmerge -J 重新解析且含軌道,才允許覆蓋原檔。"""
    cmd = [str(mkvmerge), "-J", str(mkv_path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return False
    return bool(data.get("tracks"))


# ---------- 單檔管線 ----------

@dataclass
class MkvTools:
    mkvmerge: Path
    mkvextract: Path


@dataclass
class MkvFileReport:
    mkv_path: Path
    status: str  # ok | skipped | error
    messages: List[str] = field(default_factory=list)


def process_mkv(
    mkv_path: Path,
    tracks: List[SubtitleTrack],
    operation,
    tools: MkvTools,
    out_path: Optional[Path] = None,
    progress_cb: Optional[Callable[[int], None]] = None,
    extract_fn: Callable = extract_track,
    remux_fn: Callable = remux,
    verify_fn: Callable = identify_ok,
) -> MkvFileReport:
    """單一 MKV 的完整管線。out_path=None 表「取代原檔」。

    未修改的勾選軌以原抽出內容放回(重封裝仍包含它,不可遺失);
    所有勾選軌皆未修改 → skipped、不重封裝。
    """
    report = MkvFileReport(mkv_path=Path(mkv_path), status="ok")
    workdir = Path(tempfile.mkdtemp(prefix="ass_mkv_"))
    try:
        replacements: List[Replacement] = []
        any_modified = False
        for track in tracks:
            raw = workdir / f"track_{track.track_id}.ass"
            if not extract_fn(mkv_path, track.track_id, raw, tools.mkvextract):
                return MkvFileReport(
                    Path(mkv_path), "error",
                    report.messages + [f"抽取軌 {track.track_id} 失敗"])
            styled = workdir / f"track_{track.track_id}.styled.ass"
            try:
                changed, msgs = transform_track_file(raw, styled, operation)
            except Exception as exc:  # 單軌失敗視為整檔錯誤,不中斷整批
                return MkvFileReport(
                    Path(mkv_path), "error",
                    report.messages + [f"軌 {track.track_id} 處理失敗: {exc}"])
            report.messages += [f"[軌 {track.track_id}] {m}" for m in msgs]
            if changed:
                any_modified = True
            else:
                styled = raw  # 未修改 → 原內容放回
            replacements.append(Replacement(track, styled))

        if not any_modified:
            report.status = "skipped"
            report.messages.append("所有勾選軌皆未修改,略過重封裝")
            return report

        if out_path is not None:
            target = Path(out_path)
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            target = Path(mkv_path).with_name(Path(mkv_path).name + ".tmp.mkv")

        if not remux_fn(mkv_path, target, replacements, tools.mkvmerge,
                        progress_cb):
            if out_path is None and target.exists():
                target.unlink()
            return MkvFileReport(
                Path(mkv_path), "error",
                report.messages + ["mkvmerge 重封裝失敗,原檔未變動"])

        if out_path is None:
            if not verify_fn(target, tools.mkvmerge):
                if target.exists():
                    target.unlink()
                return MkvFileReport(
                    Path(mkv_path), "error",
                    report.messages + ["輸出驗證失敗,保留原檔"])
            os.replace(target, mkv_path)
            report.messages.append("已驗證並取代原檔")
        return report
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_mkv_batch.py -v`
Expected: 12 passed

- [ ] **Step 5: 跑全套確認無回歸**

Run: `py -m pytest tests -v`
Expected: 203 passed(191 + 12)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/mkv_batch.py tests/test_mkv_batch.py
git commit -m "feat: add MKV batch pipeline (extract, transform, remux, verify-replace)"
```

---

### Task 2: MkvScanWorker + MkvWorker(batch_worker.py 附加)

**Files:**
- Modify: `ass_style_tool/qt/batch_worker.py`(附加兩個 worker)
- Test: `tests/test_mkv_worker.py`

**Interfaces:**
- Consumes: `mkv_batch.process_mkv/MkvTools/MkvFileReport`、`mkv_io.list_ass_tracks`
- Produces:
  - `MkvScanWorker(QObject)`:`__init__(folder: Path, mkvmerge: Path, list_fn=list_ass_tracks)`;signal `finished(object)` 攜帶 `dict[Path, list[SubtitleTrack]]`(遞迴掃 `*.mkv`,排序;無軌檔也включ入 dict 以便 UI 顯示);method `run()`
  - `MkvWorker(QObject)`:signals `progress(int, int)`(整批)、`file_progress(int)`(mkvmerge %)、`file_done(str, str)`、`message(str)`、`finished(int, int, int)`;`__init__(jobs: list[tuple[Path, list[SubtitleTrack]]], operation, tools, output_dir: Path|None, process_fn=process_mkv)`(output_dir None = 取代原檔);`run()/cancel()`;輸出資料夾模式含 basename 衝突保護(成功後才記名)

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_mkv_worker.py`:

```python
from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_batch import MkvFileReport, MkvTools
from ass_style_tool.mkv_io import SubtitleTrack
from tests.test_profile import make_profile

TOOLS = MkvTools(mkvmerge=Path("mkvmerge.exe"), mkvextract=Path("mkvextract.exe"))


def _track(tid=2):
    return SubtitleTrack(tid, "S_TEXT/ASS", "chi", "繁中", False, False)


def test_scan_worker_lists_tracks(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvScanWorker
    (tmp_path / "e1.mkv").write_bytes(b"")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "e2.mkv").write_bytes(b"")
    (tmp_path / "note.txt").write_text("x")

    def fake_list(path, mkvmerge):
        return [_track(2)] if path.name == "e1.mkv" else []

    worker = MkvScanWorker(tmp_path, Path("mkvmerge.exe"), list_fn=fake_list)
    got = {}
    worker.finished.connect(lambda d: got.update(d))
    worker.run()
    names = sorted(p.name for p in got)
    assert names == ["e1.mkv", "e2.mkv"]
    assert [t.track_id for t in got[tmp_path / "e1.mkv"]] == [2]
    assert got[tmp_path / "sub" / "e2.mkv"] == []


def test_mkv_worker_runs_and_reports(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvWorker

    def fake_process(mkv_path, tracks, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        if progress_cb:
            progress_cb(50)
            progress_cb(100)
        if out_path is not None:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(b"x")
        return MkvFileReport(Path(mkv_path), "ok", ["done"])

    jobs = [(tmp_path / "e1.mkv", [_track()]), (tmp_path / "e2.mkv", [_track()])]
    worker = MkvWorker(jobs, make_profile(), TOOLS,
                       output_dir=tmp_path / "out", process_fn=fake_process)
    done, pcts = {}, []
    worker.file_progress.connect(pcts.append)
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done == {"ok": 2, "skipped": 0, "error": 0}
    assert 100 in pcts


def test_mkv_worker_cancel_stops_between_files(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvWorker

    def fake_process(mkv_path, tracks, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        if out_path is not None:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(b"x")
        return MkvFileReport(Path(mkv_path), "ok", [])

    jobs = [(tmp_path / f"e{i}.mkv", [_track()]) for i in (1, 2, 3)]
    worker = MkvWorker(jobs, make_profile(), TOOLS,
                       output_dir=tmp_path / "out", process_fn=fake_process)
    worker.file_done.connect(lambda n, s: worker.cancel())
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done["ok"] < 3


def test_mkv_worker_output_name_collision(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvWorker

    def fake_process(mkv_path, tracks, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"x")
        return MkvFileReport(Path(mkv_path), "ok", [])

    a = tmp_path / "a" / "show.mkv"
    b = tmp_path / "b" / "show.mkv"      # 同名不同資料夾
    jobs = [(a, [_track()]), (b, [_track()])]
    worker = MkvWorker(jobs, make_profile(), TOOLS,
                       output_dir=tmp_path / "out", process_fn=fake_process)
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done == {"ok": 1, "skipped": 0, "error": 1}   # 第二個衝突報錯


def test_mkv_worker_replace_original_mode_no_collision_check(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvWorker

    def fake_process(mkv_path, tracks, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        assert out_path is None            # 取代原檔模式
        return MkvFileReport(Path(mkv_path), "ok", [])

    a = tmp_path / "a" / "show.mkv"
    b = tmp_path / "b" / "show.mkv"
    worker = MkvWorker([(a, [_track()]), (b, [_track()])], make_profile(),
                       TOOLS, output_dir=None, process_fn=fake_process)
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done == {"ok": 2, "skipped": 0, "error": 0}
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_mkv_worker.py -v`
Expected: FAIL — `ImportError: cannot import name 'MkvScanWorker'`

- [ ] **Step 3: 實作(附加到 batch_worker.py 末尾)**

import 區補(併入既有 import 行即可):

```python
from ..mkv_batch import MkvTools, process_mkv
from ..mkv_io import SubtitleTrack, list_ass_tracks
```

檔案末尾附加:

```python
class MkvScanWorker(QObject):
    """遞迴掃描資料夾內 *.mkv 並列舉各檔 ASS 字幕軌。"""

    finished = Signal(object)  # dict[Path, list[SubtitleTrack]]

    def __init__(self, folder: Path, mkvmerge: Path,
                 list_fn=list_ass_tracks) -> None:
        super().__init__()
        self._folder = Path(folder)
        self._mkvmerge = mkvmerge
        self._list_fn = list_fn

    def run(self) -> None:
        result = {}
        for path in sorted(self._folder.rglob("*.mkv")):
            if path.is_file():
                result[path] = self._list_fn(path, self._mkvmerge)
        self.finished.emit(result)


class MkvWorker(QObject):
    """MKV 批次 worker;逐檔跑 process_mkv,支援取消與檔名衝突保護。"""

    progress = Signal(int, int)        # 已完成, 總數
    file_progress = Signal(int)        # 當前檔 mkvmerge %
    file_done = Signal(str, str)       # 檔名, 狀態
    message = Signal(str)
    finished = Signal(int, int, int)   # ok, skipped, error

    def __init__(self, jobs, operation, tools: MkvTools,
                 output_dir: Optional[Path],
                 process_fn=process_mkv) -> None:
        super().__init__()
        self._jobs = list(jobs)
        self._operation = operation
        self._tools = tools
        self._output_dir = output_dir  # None = 取代原檔
        self._process_fn = process_fn
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._jobs)
        ok = skipped = error = 0
        seen_basenames: set[str] = set()
        for i, (mkv_path, tracks) in enumerate(self._jobs, start=1):
            if self._cancelled:
                self.message.emit("已取消,停止後續檔案")
                break
            if (self._output_dir is not None
                    and mkv_path.name in seen_basenames):
                error += 1
                self.file_done.emit(mkv_path.name, "error")
                self.message.emit(
                    "    輸出檔名衝突: 已有同名檔案寫入輸出資料夾,略過此檔")
                self.progress.emit(i, total)
                continue
            out = (self._output_dir / mkv_path.name
                   if self._output_dir is not None else None)
            report = self._process_fn(
                mkv_path, tracks, self._operation, self._tools,
                out_path=out, progress_cb=self.file_progress.emit)
            if report.status == "ok":
                ok += 1
                if self._output_dir is not None:
                    seen_basenames.add(mkv_path.name)
            elif report.status == "skipped":
                skipped += 1
            else:
                error += 1
            self.file_done.emit(mkv_path.name, report.status)
            for msg in report.messages:
                self.message.emit(f"    {msg}")
            self.progress.emit(i, total)
        self.finished.emit(ok, skipped, error)
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_mkv_worker.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```powershell
git add ass_style_tool/qt/batch_worker.py tests/test_mkv_worker.py
git commit -m "feat: add MKV scan and batch workers with collision guard"
```

---

### Task 3: mkv_tab.py — MKV 分頁 UI

**Files:**
- Create: `ass_style_tool/qt/mkv_tab.py`
- Test: `tests/test_mkv_tab.py`

**Interfaces:**
- Consumes: `batch_worker.MkvScanWorker/MkvWorker`、`mkv_batch.select_same_type/track_key/MkvTools`、`scale_panel.ScalePanel`、`tools.mkvmerge_path/mkvextract_path`、`mkv_io.extract_track`
- Produces:
  - `MkvTab(QWidget)`:建構子 `(get_profile: Callable[[], Profile])`;signals `log(str)`、`preview_requested(object, object)`(暫存字幕路徑, MKV 路徑)
  - 可測 API:`populate(files_tracks: dict[Path, list[SubtitleTrack]])`(建樹,ASS 軌預設全勾)、`checked_jobs() -> list[tuple[Path, list[SubtitleTrack]]]`、`apply_same_type_from_current() -> int`(以目前選取軌所屬檔案為基準,回傳被更新的檔案數)、`current_track() -> tuple[Path, SubtitleTrack] | None`、`tools_available: bool`、`shutdown()`
  - UI:資料夾列(拖放+瀏覽)、掃描按鈕、QTreeWidget(檔案→軌,勾選框)、「一鍵選整季同類型軌」、「送進預覽」、操作模式 radio(套用樣式/縮放字級)+ ScalePanel(預設隱藏)、輸出模式 radio(輸出到資料夾[預設]/取代原檔)、執行/取消、整批+單檔進度條
  - 缺工具:`tools_available` False 時顯示提示 QLabel、停用所有操作控制

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_mkv_tab.py`:

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


FILES = {
    Path("e1.mkv"): [_track(2, "chi", "繁中"), _track(3, "chi", "简中")],
    Path("e2.mkv"): [_track(5, "chi", "简中"), _track(7, "chi", "繁中")],
    Path("e3.mkv"): [],
}


def test_populate_builds_tree_all_checked(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    assert tab.tree.topLevelItemCount() == 3
    jobs = dict(tab.checked_jobs())
    assert {t.track_id for t in jobs[Path("e1.mkv")]} == {2, 3}
    assert {t.track_id for t in jobs[Path("e2.mkv")]} == {5, 7}
    assert Path("e3.mkv") not in jobs      # 無軌檔不成 job


def test_checked_jobs_respects_unchecking(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    # 取消 e1 的第二軌(简中)
    item = tab.tree.topLevelItem(0).child(1)
    item.setCheckState(0, Qt.CheckState.Unchecked)
    jobs = dict(tab.checked_jobs())
    assert {t.track_id for t in jobs[Path("e1.mkv")]} == {2}


def test_apply_same_type_from_current(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    # 基準:e1 只勾「繁中」
    tab.tree.topLevelItem(0).child(1).setCheckState(0, Qt.CheckState.Unchecked)
    tab.tree.setCurrentItem(tab.tree.topLevelItem(0).child(0))
    updated = tab.apply_same_type_from_current()
    assert updated >= 1
    jobs = dict(tab.checked_jobs())
    assert {t.track_id for t in jobs[Path("e2.mkv")]} == {7}   # e2 的繁中


def test_current_track(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab.tree.setCurrentItem(tab.tree.topLevelItem(1).child(0))
    path, track = tab.current_track()
    assert path == Path("e2.mkv")
    assert track.track_id == 5
    tab.tree.setCurrentItem(tab.tree.topLevelItem(0))   # 檔案節點
    assert tab.current_track() is None


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


def test_run_button_enabled_after_populate(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.run_button.isEnabled() is False
    tab.populate(FILES)
    assert tab.run_button.isEnabled() is True
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_mkv_tab.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.qt.mkv_tab'`

- [ ] **Step 3: 實作 mkv_tab.py**

建立 `ass_style_tool/qt/mkv_tab.py`:

```python
"""「MKV」分頁:掃描 MKV 字幕軌、勾選、一鍵選整季、批次重封裝、送進預覽。"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QRadioButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from ..mkv_batch import MkvTools, select_same_type
from ..mkv_io import SubtitleTrack, extract_track
from ..profile import Profile
from ..scale_engine import ScaleError
from ..tools import mkvextract_path, mkvmerge_path
from .batch_worker import MkvScanWorker, MkvWorker
from .scale_panel import ScalePanel

_ROLE_PATH = Qt.UserRole
_ROLE_TRACK = Qt.UserRole + 1


class MkvTab(QWidget):
    log = Signal(str)
    preview_requested = Signal(object, object)  # (暫存字幕路徑, MKV 路徑)

    def __init__(self, get_profile: Callable[[], Profile]) -> None:
        super().__init__()
        self._get_profile = get_profile
        self._files_tracks: Dict[Path, List[SubtitleTrack]] = {}
        self._thread: Optional[QThread] = None
        self._worker = None
        self._scan_thread: Optional[QThread] = None
        self._scan_worker = None
        self._preview_dir = Path(tempfile.mkdtemp(prefix="ass_mkv_preview_"))
        self.setAcceptDrops(True)

        mkvmerge = mkvmerge_path()
        mkvextract = mkvextract_path()
        self.tools_available = mkvmerge is not None and mkvextract is not None
        self._tools = (MkvTools(mkvmerge, mkvextract)
                       if self.tools_available else None)

        root = QVBoxLayout(self)

        if not self.tools_available:
            warn = QLabel("⚠ 找不到 mkvmerge/mkvextract:請安裝 MKVToolNix "
                          "後重新啟動(功能已停用,不影響其他分頁)")
            warn.setStyleSheet("color: #d08a00;")
            root.addWidget(warn)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("資料夾:"))
        self.folder_edit = QLineEdit()
        folder_row.addWidget(self.folder_edit, 1)
        browse = QPushButton("瀏覽…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(browse)
        root.addLayout(folder_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["MKV / 字幕軌", "語言", "軌名"])
        self.tree.setColumnWidth(0, 420)
        root.addWidget(self.tree, 1)

        # 操作模式
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
        self.scale_mode_radio.toggled.connect(
            lambda on: self.scale_panel.setHidden(not on))

        # 輸出模式
        out_row = QHBoxLayout()
        self.outdir_radio = QRadioButton("輸出到資料夾:")
        self.outdir_radio.setChecked(True)
        self.outdir_edit = QLineEdit()
        out_browse = QPushButton("…")
        out_browse.clicked.connect(self._browse_out)
        self.replace_radio = QRadioButton("取代原檔(驗證後覆蓋,不留備份)")
        out_row.addWidget(self.outdir_radio)
        out_row.addWidget(self.outdir_edit, 1)
        out_row.addWidget(out_browse)
        out_row.addWidget(self.replace_radio)
        root.addLayout(out_row)

        action_row = QHBoxLayout()
        self.scan_button = QPushButton("掃描字幕軌")
        self.scan_button.clicked.connect(self._on_scan)
        self.same_type_button = QPushButton("一鍵選整季同類型軌")
        self.same_type_button.clicked.connect(self._on_same_type)
        self.preview_button = QPushButton("送進預覽")
        self.preview_button.clicked.connect(self._on_send_preview)
        self.run_button = QPushButton("開始處理")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._on_run)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        for b in (self.scan_button, self.same_type_button,
                  self.preview_button, self.run_button, self.cancel_button):
            action_row.addWidget(b)
        action_row.addStretch(1)
        root.addLayout(action_row)

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
            for b in (self.scan_button, self.same_type_button,
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
                self.folder_edit.setText(path)
                break

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇含 MKV 的資料夾")
        if path:
            self.folder_edit.setText(path)

    def _browse_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇輸出資料夾")
        if path:
            self.outdir_edit.setText(path)
            self.outdir_radio.setChecked(True)

    # ---------- 掃描 ----------
    def _on_scan(self) -> None:
        folder = self.folder_edit.text().strip()
        if not folder or not Path(folder).is_dir():
            self.log.emit("請先選擇有效的資料夾")
            return
        self.scan_button.setEnabled(False)
        self._scan_thread = QThread()
        self._scan_worker = MkvScanWorker(Path(folder), self._tools.mkvmerge)
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_scan_done)
        self._scan_thread.start()

    def _on_scan_done(self, files_tracks: dict) -> None:
        if self._scan_thread is not None:
            self._scan_thread.quit()
            self._scan_thread.wait()
        self._scan_thread = None
        self._scan_worker = None
        self.scan_button.setEnabled(True)
        self.populate(files_tracks)
        total_tracks = sum(len(v) for v in files_tracks.values())
        self.log.emit(f"掃描完成:{len(files_tracks)} 個 MKV,"
                      f"共 {total_tracks} 條 ASS 字幕軌")

    def populate(self, files_tracks: Dict[Path, List[SubtitleTrack]]) -> None:
        self._files_tracks = dict(files_tracks)
        self.tree.clear()
        for path in sorted(files_tracks):
            top = QTreeWidgetItem([path.name, "", ""])
            top.setData(0, _ROLE_PATH, path)
            tracks = files_tracks[path]
            if not tracks:
                top.setText(2, "(無 ASS 字幕軌)")
            for track in tracks:
                child = QTreeWidgetItem(
                    [f"軌 {track.track_id}", track.language,
                     track.track_name or "-"])
                child.setData(0, _ROLE_PATH, path)
                child.setData(0, _ROLE_TRACK, track)
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked)
                top.addChild(child)
            self.tree.addTopLevelItem(top)
        self.tree.expandAll()
        self.run_button.setEnabled(
            any(files_tracks.values()) and self.tools_available)

    # ---------- 勾選 ----------
    def _iter_track_items(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                yield top.child(j)

    def checked_jobs(self) -> List[Tuple[Path, List[SubtitleTrack]]]:
        grouped: Dict[Path, List[SubtitleTrack]] = {}
        for item in self._iter_track_items():
            if item.checkState(0) == Qt.CheckState.Checked:
                path = item.data(0, _ROLE_PATH)
                grouped.setdefault(path, []).append(item.data(0, _ROLE_TRACK))
        return [(p, ts) for p, ts in grouped.items() if ts]

    def current_track(self) -> Optional[Tuple[Path, SubtitleTrack]]:
        item = self.tree.currentItem()
        if item is None:
            return None
        track = item.data(0, _ROLE_TRACK)
        if track is None:
            return None
        return item.data(0, _ROLE_PATH), track

    def apply_same_type_from_current(self) -> int:
        """以目前選取軌所屬檔案的勾選狀態為基準,套用到所有檔案。"""
        current = self.current_track()
        if current is None:
            self.log.emit("請先在樹狀清單選取一條字幕軌作為基準")
            return 0
        base_path = current[0]
        reference = [item.data(0, _ROLE_TRACK)
                     for item in self._iter_track_items()
                     if item.data(0, _ROLE_PATH) == base_path
                     and item.checkState(0) == Qt.CheckState.Checked]
        selected = select_same_type(reference, self._files_tracks)
        updated = 0
        for item in self._iter_track_items():
            path = item.data(0, _ROLE_PATH)
            if path == base_path:
                continue
            track = item.data(0, _ROLE_TRACK)
            want = track.track_id in selected.get(path, set())
            state = Qt.CheckState.Checked if want else Qt.CheckState.Unchecked
            if item.checkState(0) != state:
                item.setCheckState(0, state)
                updated += 1
        self.log.emit(f"已依基準檔同步 {updated} 條軌的勾選狀態")
        return updated

    def _on_same_type(self) -> None:
        self.apply_same_type_from_current()

    # ---------- 送進預覽 ----------
    def _on_send_preview(self) -> None:
        current = self.current_track()
        if current is None:
            self.log.emit("請先選取一條字幕軌")
            return
        mkv_path, track = current
        temp = self._preview_dir / f"{mkv_path.stem}_track{track.track_id}.ass"
        if not extract_track(mkv_path, track.track_id, temp,
                             self._tools.mkvextract):
            self.log.emit(f"抽取軌 {track.track_id} 失敗,無法預覽")
            return
        self.preview_requested.emit(temp, mkv_path)

    # ---------- 執行 ----------
    def _output_dir(self) -> Optional[Path]:
        if self.replace_radio.isChecked():
            return None
        text = self.outdir_edit.text().strip()
        return Path(text) if text else None

    def _on_run(self) -> None:
        jobs = self.checked_jobs()
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
        self.cancel_button.setEnabled(False)

    # ---------- 清理 ----------
    def shutdown(self) -> None:
        for thread in (self._thread, self._scan_thread):
            if thread is not None:
                thread.quit()
                thread.wait()
        import shutil
        shutil.rmtree(self._preview_dir, ignore_errors=True)
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_mkv_tab.py -v`
Expected: 7 passed

- [ ] **Step 5: 跑全套確認無回歸**

Run: `py -m pytest tests -v`
Expected: 215 passed(191 + 12 + 5 + 7)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/qt/mkv_tab.py tests/test_mkv_tab.py
git commit -m "feat: add MKV tab with track tree, season select, batch run and preview handoff"
```

---

### Task 4: 整合 — 主視窗接入 MkvTab

**Files:**
- Modify: `ass_style_tool/qt/main_window.py`
- Test: 無新自動化測試(整合以 import + 啟動冒煙 + 手動清單驗證)

**Interfaces:**
- Consumes: `mkv_tab.MkvTab`、既有 `_open_in_preview(sub_path, video_path)`
- Produces: MKV 佔位分頁替換為 MkvTab;log 與 preview_requested 接線;closeEvent 加 `mkv_tab.shutdown()`

- [ ] **Step 1: 修改 main_window.py**

(a)import 區加:

```python
from .mkv_tab import MkvTab
```

(b)把 MKV 佔位分頁那段:

```python
        mkv_page = QWidget()
        mkv_layout = QVBoxLayout(mkv_page)
        mkv_layout.addWidget(QLabel("（MKV 功能於後續計畫實作）"))
        mkv_layout.addStretch(1)
        self.tabs.addTab(mkv_page, "MKV")
```

替換為:

```python
        self.mkv_tab = MkvTab(self.style_editor.current_profile)
        self.mkv_tab.log.connect(self.append_log)
        self.mkv_tab.preview_requested.connect(self._open_in_preview)
        self.tabs.addTab(self.mkv_tab, "MKV")
```

(若替換後 `QLabel`/`QVBoxLayout`/`QWidget` 在該檔已無其他使用者,保留 import 亦可——其他區塊仍在用,勿貿然刪 import。)

(c)`closeEvent` 中 `self.preview_panel.shutdown()` 之後加:

```python
        self.mkv_tab.shutdown()
```

- [ ] **Step 2: 全套測試 + import + 啟動冒煙**

Run: `py -m pytest tests -v`
Expected: 215 passed

Run: `py -c "import ass_style_tool.qt.main_window; print('ok')"`
Expected: `ok`

```powershell
$p = Start-Process -FilePath "py" -ArgumentList "-m","ass_style_tool" -WorkingDirectory "C:\Claude_code" -PassThru
Start-Sleep -Seconds 3
if ($p.HasExited) { Write-Output "FAIL exit=$($p.ExitCode)" } else { Write-Output "OK"; Stop-Process -Id $p.Id }
```

Expected: `OK`

- [ ] **Step 3: 手動冒煙清單(由使用者以真實 MKV 執行,記於報告)**

Run: `py -m ass_style_tool`
1. 「MKV」分頁不再是佔位;工具齊全時所有按鈕可用
2. 選一個含整季 MKV 的資料夾 →「掃描字幕軌」→ 樹狀列出每檔的 ASS 軌(語言/軌名),預設全勾
3. 在某檔取消部分軌、選取一條基準軌 →「一鍵選整季同類型軌」→ 其他集數自動勾選同(語言,軌名)的軌
4. 選取一條軌 →「送進預覽」→ 自動切到預覽分頁,影片是該 MKV、字幕是該軌內容,改樣式即時反映
5. 「輸出到資料夾」+「套用樣式」跑一批 → 進度條(整批+當前檔 %)動、輸出 MKV 用播放器開啟確認:目標軌樣式已改、其他軌/音訊/章節/字型附件完好
6. 「縮放字級」模式跑一次 → 字級等比變化、樣式其他屬性不變
7. 「取代原檔」模式(拿可犧牲的測試檔!)→ 完成後原檔已是新內容且可正常播放;故意用損壞情境(如中途取消)確認原檔不會被半成品覆蓋
8. 多檔執行中按「取消」→ 當前檔完成後停止

- [ ] **Step 4: Commit**

```powershell
git add ass_style_tool/qt/main_window.py
git commit -m "feat: wire MKV tab into main window with preview handoff"
```

---

## 本計畫完成後

v2 的功能面全部到位(字幕檔批次、縮放、即時預覽、MKV 分頁)。剩 **Plan 3 — 打包**:PyInstaller onedir + Inno Setup(元件式安裝:偵測系統 ffmpeg/MKVToolNix 決定預設勾選,libmpv 固定內建)。
