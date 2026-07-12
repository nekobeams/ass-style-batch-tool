# v2 Plan 2e — 封裝字幕進 MKV(Mux 分頁)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「封裝」分頁——把外部 `.ass` 字幕檔 mux 進 MKV。選影片資料夾 + 字幕資料夾,依集數自動配對,設定軌資訊(語言/軌名/default/forced),可選封裝前先套用樣式或縮放,批次 mkvmerge 產生帶字幕的新 MKV(或驗證後取代原檔),進度/取消。

**Architecture:** `mkv_mux.py` 純邏輯(配對、mkvmerge 命令組裝、單檔 mux 管線),復用 `mkv_batch.transform_track_file`(封裝前處理)與 `mkv_batch.identify_ok`(取代驗證)、`episode_match`(配對);`MuxScanWorker`/`MuxWorker` 是薄 QThread 包裝(輸出檔名衝突保護內建);`qt/mux_tab.py` 用兩個資料夾輸入 + 配對表格。外部程序全部注入,測試不執行真實 mkvmerge。

**Tech Stack:** PySide6、MKVToolNix(mkvmerge)、pytest(offscreen Qt)。

**Spec:** `docs/superpowers/specs/2026-07-08-ass-style-tool-v2-design.md` 的「封裝字幕進 MKV」節

## Global Constraints

- 工作目錄/repo root:`C:\Claude_code`,git branch 由執行者依 subagent-driven 流程建立
- **環境重點**:`python` 是壞的 Windows Store stub,一律用 `py`:`py -m pytest tests -v`
- Python 3.9+ 相容;每個新模組頂端加 `from __future__ import annotations`
- 測試絕不執行真實 mkvmerge:`mkv_mux` 的 mux/verify 函式參數注入,worker 測試注入假 process_fn/list_fn,配對用假路徑
- mux 命令:影片所有既有軌與附件原封保留(不加任何 `--*-tracks` 排除),外部 `.ass` 以附加軌加入;軌名為空則省略 `--track-name`
- 取代原檔:寫同目錄暫存 → `identify_ok` 驗證 → `os.replace`(包 try/except OSError,失敗清暫存保留原檔,不拋出);沿用 `mkv_batch` 既有模式
- 輸出資料夾模式:內建 basename 衝突保護(成功後才記名),比照 `MkvWorker`
- 單檔失敗不中斷整批;worker 對 process_fn 包 try/except 轉 error(比照 `MkvWorker`/`ScaleWorker`);取消 = 當前檔跑完後停止
- 缺 mkvmerge → 分頁停用控制並顯示提示,不閃退
- 自動掃描:選好任一資料夾即自動觸發配對掃描(比照現有 subtitle/mkv 分頁的 `_auto_scan` 模式);保留「重新掃描」按鈕
- Qt 測試用既有 `tests/conftest.py` 的 offscreen `qapp`
- 測試指令:`py -m pytest tests -v`(從 repo root;目前基準 226 passed)
- Commit 訊息用 conventional commits

### 既有介面(本計畫會用到,已實作且測試)

- `ass_style_tool.episode_match`:`extract_episode(name) -> int|None`、`find_files(folder) -> (subs, videos)`、`SUB_EXTS`、`VIDEO_EXTS`
- `ass_style_tool.mkv_batch`:`transform_track_file(src, dst, operation) -> (bool, list[str])`(operation 為 Profile 或 ScaleOptions;Profile 無匹配回 (False, msgs) 不寫 dst)、`identify_ok(mkv_path, mkvmerge) -> bool`、`MkvTools`(mkvmerge, mkvextract)、`MkvFileReport`(mkv_path, status, messages)
- `ass_style_tool.tools`:`mkvmerge_path() -> Path|None`、`mkvextract_path() -> Path|None`
- `ass_style_tool.scale_engine.ScaleOptions/ScaleError`;`ass_style_tool.profile.Profile`
- `ass_style_tool.qt.scale_panel.ScalePanel`(`get_options()`,非法丟 ScaleError)
- `ass_style_tool.qt.main_window.MainWindow`(`append_log`;分頁在 tabs)
- 測試輔助:`tests.test_ass_style.SAMPLE_ASS`、`tests.test_profile.make_profile`、`tests.test_profile_fields.DEFAULT_VALUES/profile_from_values`

## File Structure

```
ass_style_tool/
└── mkv_mux.py          # MuxMeta, MuxPair, pair_for_mux, build_mux_command, process_mux
ass_style_tool/qt/
├── batch_worker.py     # (修改)附加 MuxScanWorker, MuxWorker
├── mux_tab.py          # (新)封裝分頁 UI
└── main_window.py      # (修改)接入 MuxTab
tests/
├── test_mkv_mux.py
├── test_mux_worker.py
└── test_mux_tab.py
```

---

### Task 1: mkv_mux.py — 配對、命令組裝、單檔 mux 管線

**Files:**
- Create: `ass_style_tool/mkv_mux.py`
- Test: `tests/test_mkv_mux.py`

**Interfaces:**
- Consumes: `episode_match.extract_episode/find_files`、`mkv_batch.transform_track_file/identify_ok/MkvTools/MkvFileReport`
- Produces:
  - `MuxMeta` dataclass:`language: str = "und", track_name: str = "", default: bool = False, forced: bool = False`
  - `MuxPair` dataclass:`video_path: Path, subtitle_path: Path|None, episode: int|None, status: str`(matched|no_subtitle|ambiguous|no_episode)
  - `pair_for_mux(video_paths: list[Path], subtitle_paths: list[Path]) -> list[MuxPair]` — 依集數配對(影片為主);影片抽不到集數→no_episode;該集無字幕→no_subtitle;該集多個字幕候選或多個同集影片→ambiguous(不配對)
  - `build_mux_command(video_path, subtitle_path, out_path, meta: MuxMeta, mkvmerge: Path) -> list[str]` — 純函式
  - `process_mux(pair: MuxPair, meta: MuxMeta, operation, tools: MkvTools, out_path: Path|None=None, progress_cb=None, mux_fn=..., verify_fn=...) -> MkvFileReport` — 單檔管線;`operation` 為 None(原字幕直封)或 Profile/ScaleOptions(先轉換再封);`out_path=None` 表取代原檔

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_mkv_mux.py`:

```python
from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_batch import MkvTools
from ass_style_tool.mkv_mux import (MuxMeta, MuxPair, build_mux_command,
                                    pair_for_mux, process_mux)
from ass_style_tool.scale_engine import ScaleOptions
from tests.test_ass_style import SAMPLE_ASS
from tests.test_profile import make_profile

TOOLS = MkvTools(mkvmerge=Path("mkvmerge.exe"), mkvextract=Path("mkvextract.exe"))


# ---------- 配對 ----------

def test_pair_matches_by_episode():
    videos = [Path("[G] Show [01].mkv"), Path("[G] Show [02].mkv")]
    subs = [Path("[X] Show - 02.ass"), Path("[X] Show - 01.ass")]
    pairs = {p.video_path: p for p in pair_for_mux(videos, subs)}
    assert pairs[Path("[G] Show [01].mkv")].subtitle_path == Path("[X] Show - 01.ass")
    assert pairs[Path("[G] Show [01].mkv")].status == "matched"
    assert pairs[Path("[G] Show [02].mkv")].subtitle_path == Path("[X] Show - 02.ass")


def test_pair_no_subtitle():
    pairs = pair_for_mux([Path("a [03].mkv")], [Path("b [04].ass")])
    assert pairs[0].status == "no_subtitle"
    assert pairs[0].subtitle_path is None


def test_pair_no_episode():
    pairs = pair_for_mux([Path("movie.mkv")], [Path("x [01].ass")])
    assert pairs[0].status == "no_episode"


def test_pair_ambiguous_multiple_subs():
    pairs = pair_for_mux(
        [Path("a [01].mkv")],
        [Path("a [01].tc.ass"), Path("a [01].sc.ass")])
    assert pairs[0].status == "ambiguous"
    assert pairs[0].subtitle_path is None


# ---------- build_mux_command ----------

def _meta(**kw):
    base = dict(language="chi", track_name="繁中", default=True, forced=False)
    base.update(kw)
    return MuxMeta(**base)


def test_build_mux_command_basic():
    cmd = build_mux_command(
        Path("show.mkv"), Path("show.ass"), Path("out.mkv"),
        _meta(), Path("mkvmerge.exe"))
    assert cmd[:3] == ["mkvmerge.exe", "-o", "out.mkv"]
    # 影片在字幕之前
    assert cmd.index("show.mkv") < cmd.index("show.ass")
    joined = " ".join(cmd)
    assert "--language 0:chi" in joined
    assert "--track-name 0:繁中" in joined
    assert "--default-track 0:yes" in joined
    assert "--forced-track 0:no" in joined


def test_build_mux_command_omits_empty_track_name():
    cmd = build_mux_command(
        Path("s.mkv"), Path("s.ass"), Path("o.mkv"),
        _meta(track_name=""), Path("mkvmerge"))
    assert "--track-name" not in cmd


# ---------- process_mux ----------

def _write_ass(tmp_path, name="sub.ass"):
    p = tmp_path / name
    p.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    return p


def test_process_mux_direct_outdir(tmp_path):
    sub = _write_ass(tmp_path)
    calls = {}

    def fake_mux(video, subtitle, out, meta, mkvmerge, progress_cb=None):
        calls["subtitle"] = Path(subtitle)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"muxed")
        if progress_cb:
            progress_cb(100)
        return True

    pair = MuxPair(Path("show.mkv"), sub, 1, "matched")
    out = tmp_path / "out" / "show.mkv"
    report = process_mux(pair, _meta(), None, TOOLS, out_path=out,
                         mux_fn=fake_mux)
    assert report.status == "ok"
    assert calls["subtitle"] == sub          # 原字幕直封
    assert out.exists()


def test_process_mux_with_style_transforms_first(tmp_path):
    sub = _write_ass(tmp_path)
    seen = {}

    def fake_mux(video, subtitle, out, meta, mkvmerge, progress_cb=None):
        seen["subtitle"] = Path(subtitle)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"x")
        return True

    pair = MuxPair(Path("show.mkv"), sub, 1, "matched")
    out = tmp_path / "out" / "show.mkv"
    report = process_mux(pair, _meta(), make_profile(), TOOLS, out_path=out,
                         mux_fn=fake_mux)
    assert report.status == "ok"
    # 封進去的是轉換後的暫存檔(非原字幕)
    assert seen["subtitle"] != sub
    import pysubs2
    styled = pysubs2.SSAFile.from_string(
        seen["subtitle"].read_text(encoding="utf-8-sig"))
    assert styled.styles["Default"].fontname == "思源黑體 CN"


def test_process_mux_scale_operation(tmp_path):
    sub = _write_ass(tmp_path)
    seen = {}

    def fake_mux(video, subtitle, out, meta, mkvmerge, progress_cb=None):
        seen["text"] = Path(subtitle).read_text(encoding="utf-8-sig")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"x")
        return True

    pair = MuxPair(Path("show.mkv"), sub, 1, "matched")
    process_mux(pair, _meta(), ScaleOptions(factor=2), TOOLS,
                out_path=tmp_path / "o" / "show.mkv", mux_fn=fake_mux)
    assert "Style: Default,Arial,80," in seen["text"]


def test_process_mux_no_subtitle_is_skipped(tmp_path):
    pair = MuxPair(Path("show.mkv"), None, 1, "no_subtitle")
    report = process_mux(pair, _meta(), None, TOOLS,
                         out_path=tmp_path / "o.mkv",
                         mux_fn=lambda *a, **k: True)
    assert report.status == "skipped"


def test_process_mux_mux_fail_is_error(tmp_path):
    sub = _write_ass(tmp_path)
    pair = MuxPair(Path("show.mkv"), sub, 1, "matched")
    report = process_mux(pair, _meta(), None, TOOLS,
                         out_path=tmp_path / "o" / "show.mkv",
                         mux_fn=lambda *a, **k: False)
    assert report.status == "error"


def test_process_mux_replace_verify_and_swap(tmp_path):
    video = tmp_path / "show.mkv"
    video.write_bytes(b"ORIGINAL")
    sub = _write_ass(tmp_path)

    def fake_mux(v, s, out, meta, mkvmerge, progress_cb=None):
        Path(out).write_bytes(b"MUXED")
        return True

    pair = MuxPair(video, sub, 1, "matched")
    report = process_mux(pair, _meta(), None, TOOLS, out_path=None,
                         mux_fn=fake_mux, verify_fn=lambda p, m: True)
    assert report.status == "ok"
    assert video.read_bytes() == b"MUXED"
    assert not video.with_name(video.name + ".tmp.mkv").exists()


def test_process_mux_replace_verify_fail_keeps_original(tmp_path):
    video = tmp_path / "show.mkv"
    video.write_bytes(b"ORIGINAL")
    sub = _write_ass(tmp_path)

    def fake_mux(v, s, out, meta, mkvmerge, progress_cb=None):
        Path(out).write_bytes(b"BROKEN")
        return True

    pair = MuxPair(video, sub, 1, "matched")
    report = process_mux(pair, _meta(), None, TOOLS, out_path=None,
                         mux_fn=fake_mux, verify_fn=lambda p, m: False)
    assert report.status == "error"
    assert video.read_bytes() == b"ORIGINAL"
    assert not video.with_name(video.name + ".tmp.mkv").exists()
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_mkv_mux.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.mkv_mux'`

- [ ] **Step 3: 實作 mkv_mux.py**

建立 `ass_style_tool/mkv_mux.py`:

```python
"""把外部 .ass 字幕封裝(mux)進 MKV 的純邏輯:配對、命令組裝、單檔管線。

外部程序(mux/驗證)以函式參數注入,預設綁定實作;測試注入假函式。
復用 mkv_batch 的封裝前處理(transform_track_file)與取代驗證(identify_ok)。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .episode_match import extract_episode
from .mkv_batch import (MkvFileReport, MkvTools, identify_ok,
                        transform_track_file)


@dataclass
class MuxMeta:
    language: str = "und"
    track_name: str = ""
    default: bool = False
    forced: bool = False


@dataclass
class MuxPair:
    video_path: Path
    subtitle_path: Optional[Path]
    episode: Optional[int]
    status: str  # matched | no_subtitle | ambiguous | no_episode


def pair_for_mux(
    video_paths: List[Path], subtitle_paths: List[Path]
) -> List[MuxPair]:
    """依集數編號把影片與字幕配對(以影片為主)。"""
    subs_by_ep: Dict[int, List[Path]] = {}
    for sub in subtitle_paths:
        ep = extract_episode(sub.name)
        if ep is not None:
            subs_by_ep.setdefault(ep, []).append(sub)

    video_eps = [extract_episode(v.name) for v in video_paths]
    video_ep_counts: Dict[int, int] = {}
    for ep in video_eps:
        if ep is not None:
            video_ep_counts[ep] = video_ep_counts.get(ep, 0) + 1

    result: List[MuxPair] = []
    for video, ep in zip(video_paths, video_eps):
        if ep is None:
            result.append(MuxPair(video, None, None, "no_episode"))
            continue
        candidates = subs_by_ep.get(ep, [])
        if video_ep_counts[ep] > 1 or len(candidates) > 1:
            result.append(MuxPair(video, None, ep, "ambiguous"))
        elif len(candidates) == 1:
            result.append(MuxPair(video, candidates[0], ep, "matched"))
        else:
            result.append(MuxPair(video, None, ep, "no_subtitle"))
    return result


def build_mux_command(
    video_path: Path, subtitle_path: Path, out_path: Path,
    meta: MuxMeta, mkvmerge: Path,
) -> List[str]:
    """影片所有軌保留,外部字幕以附加軌加入(檔內為 track 0)。"""
    cmd: List[str] = [str(mkvmerge), "-o", str(out_path), str(video_path)]
    cmd += ["--language", f"0:{meta.language}"]
    if meta.track_name:
        cmd += ["--track-name", f"0:{meta.track_name}"]
    cmd += ["--default-track", f"0:{'yes' if meta.default else 'no'}"]
    cmd += ["--forced-track", f"0:{'yes' if meta.forced else 'no'}"]
    cmd.append(str(subtitle_path))
    return cmd


def _default_mux(video_path, subtitle_path, out_path, meta, mkvmerge,
                 progress_cb=None) -> bool:
    from .mkv_io import parse_progress
    cmd = build_mux_command(video_path, subtitle_path, out_path, meta, mkvmerge)
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace")
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


def process_mux(
    pair: MuxPair,
    meta: MuxMeta,
    operation,
    tools: MkvTools,
    out_path: Optional[Path] = None,
    progress_cb: Optional[Callable[[int], None]] = None,
    mux_fn: Callable = _default_mux,
    verify_fn: Callable = identify_ok,
) -> MkvFileReport:
    """單一影片的 mux 管線。operation=None 原字幕直封,否則先轉換再封。
    out_path=None 表取代原檔。"""
    video = pair.video_path
    if pair.subtitle_path is None:
        return MkvFileReport(video, "skipped", ["無配對字幕,略過"])

    report = MkvFileReport(video, "ok")
    workdir = Path(tempfile.mkdtemp(prefix="ass_mux_"))
    try:
        subtitle = pair.subtitle_path
        if operation is not None:
            styled = workdir / "styled.ass"
            try:
                changed, msgs = transform_track_file(subtitle, styled, operation)
            except Exception as exc:  # 轉換失敗視為整檔錯誤
                return MkvFileReport(video, "error", [f"字幕處理失敗: {exc}"])
            report.messages += msgs
            if changed:
                subtitle = styled
            # 未修改(如找不到目標 Style)→ 仍封原字幕

        if out_path is not None:
            target = Path(out_path)
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            target = video.with_name(video.name + ".tmp.mkv")

        if not mux_fn(video, subtitle, target, meta, tools.mkvmerge,
                      progress_cb):
            if out_path is None and target.exists():
                target.unlink()
            return MkvFileReport(
                video, "error", report.messages + ["mkvmerge 封裝失敗,原檔未變動"])

        if out_path is None:
            if not verify_fn(target, tools.mkvmerge):
                if target.exists():
                    target.unlink()
                return MkvFileReport(
                    video, "error", report.messages + ["輸出驗證失敗,保留原檔"])
            try:
                os.replace(target, video)
            except OSError as exc:
                if target.exists():
                    target.unlink()
                return MkvFileReport(
                    video, "error", report.messages + [f"取代原檔失敗: {exc}"])
            report.messages.append("已驗證並取代原檔")
        return report
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_mkv_mux.py -v`
Expected: 13 passed

- [ ] **Step 5: 跑全套確認無回歸**

Run: `py -m pytest tests -v`
Expected: 239 passed(226 + 13)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/mkv_mux.py tests/test_mkv_mux.py
git commit -m "feat: add mux pipeline (pair by episode, build mux command, process_mux)"
```

---

### Task 2: MuxScanWorker + MuxWorker(batch_worker.py 附加)

**Files:**
- Modify: `ass_style_tool/qt/batch_worker.py`(附加兩個 worker)
- Test: `tests/test_mux_worker.py`

**Interfaces:**
- Consumes: `mkv_mux.pair_for_mux/process_mux/MuxMeta/MuxPair`、`episode_match.find_files`
- Produces:
  - `MuxScanWorker(QObject)`:`__init__(video_folder: Path, subtitle_folder: Path, pair_fn=pair_for_mux)`;signal `finished(object)` 攜帶 `list[MuxPair]`;`run()`(用 `find_files` 取兩資料夾的影片/字幕清單再配對)
  - `MuxWorker(QObject)`:signals `progress(int,int)`、`file_progress(int)`、`file_done(str,str)`、`message(str)`、`finished(int,int,int)`;`__init__(pairs, meta, operation, tools, output_dir, process_fn=process_mux)`;`run()/cancel()`;輸出資料夾模式含 basename 衝突保護(成功後才記名);對 process_fn 包 try/except 轉 error

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_mux_worker.py`:

```python
from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_batch import MkvFileReport, MkvTools
from ass_style_tool.mkv_mux import MuxMeta, MuxPair

TOOLS = MkvTools(mkvmerge=Path("mkvmerge.exe"), mkvextract=Path("mkvextract.exe"))
META = MuxMeta(language="chi", track_name="繁中", default=True, forced=False)


def test_scan_worker_pairs_two_folders(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MuxScanWorker
    vdir = tmp_path / "video"
    sdir = tmp_path / "sub"
    vdir.mkdir()
    sdir.mkdir()
    (vdir / "Show [01].mkv").write_bytes(b"")
    (vdir / "Show [02].mkv").write_bytes(b"")
    (sdir / "Show - 01.ass").write_bytes(b"")
    worker = MuxScanWorker(vdir, sdir)
    got = {}
    worker.finished.connect(lambda pairs: got.update(pairs=pairs))
    worker.run()
    by_ep = {p.episode: p.status for p in got["pairs"]}
    assert by_ep[1] == "matched"
    assert by_ep[2] == "no_subtitle"


def test_mux_worker_runs_and_reports(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MuxWorker

    def fake_process(pair, meta, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        if progress_cb:
            progress_cb(100)
        if out_path is not None:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(b"x")
        return MkvFileReport(pair.video_path, "ok", ["done"])

    pairs = [
        MuxPair(tmp_path / "a [01].mkv", tmp_path / "a.ass", 1, "matched"),
        MuxPair(tmp_path / "b [02].mkv", tmp_path / "b.ass", 2, "matched"),
    ]
    worker = MuxWorker(pairs, META, None, TOOLS,
                       output_dir=tmp_path / "out", process_fn=fake_process)
    done, pcts = {}, []
    worker.file_progress.connect(pcts.append)
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done == {"ok": 2, "skipped": 0, "error": 0}
    assert 100 in pcts


def test_mux_worker_exception_isolated(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MuxWorker

    def fake_process(pair, meta, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        if pair.episode == 2:
            raise RuntimeError("boom")
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"x")
        return MkvFileReport(pair.video_path, "ok", [])

    pairs = [
        MuxPair(tmp_path / f"e{i} [{i:02d}].mkv", tmp_path / f"s{i}.ass", i,
                "matched") for i in (1, 2, 3)]
    worker = MuxWorker(pairs, META, None, TOOLS,
                       output_dir=tmp_path / "out", process_fn=fake_process)
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done == {"ok": 2, "skipped": 0, "error": 1}   # 不崩、續跑


def test_mux_worker_cancel(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MuxWorker

    def fake_process(pair, meta, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"x")
        return MkvFileReport(pair.video_path, "ok", [])

    pairs = [MuxPair(tmp_path / f"e{i} [{i:02d}].mkv", tmp_path / f"s{i}.ass",
                     i, "matched") for i in (1, 2, 3)]
    worker = MuxWorker(pairs, META, None, TOOLS,
                       output_dir=tmp_path / "out", process_fn=fake_process)
    worker.file_done.connect(lambda n, s: worker.cancel())
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done["ok"] < 3


def test_mux_worker_output_name_collision(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MuxWorker

    def fake_process(pair, meta, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"x")
        return MkvFileReport(pair.video_path, "ok", [])

    pairs = [
        MuxPair(tmp_path / "a" / "show.mkv", tmp_path / "a.ass", 1, "matched"),
        MuxPair(tmp_path / "b" / "show.mkv", tmp_path / "b.ass", 1, "matched"),
    ]
    worker = MuxWorker(pairs, META, None, TOOLS,
                       output_dir=tmp_path / "out", process_fn=fake_process)
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done == {"ok": 1, "skipped": 0, "error": 1}
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_mux_worker.py -v`
Expected: FAIL — `ImportError: cannot import name 'MuxScanWorker'`

- [ ] **Step 3: 實作(附加到 batch_worker.py 末尾)**

import 區補(併入既有 import 行):

```python
from ..mkv_mux import MuxMeta, MuxPair, pair_for_mux, process_mux
from ..episode_match import find_files
```

檔案末尾附加:

```python
class MuxScanWorker(QObject):
    """掃描影片資料夾與字幕資料夾,依集數配對。"""

    finished = Signal(object)  # list[MuxPair]

    def __init__(self, video_folder: Path, subtitle_folder: Path,
                 pair_fn=pair_for_mux) -> None:
        super().__init__()
        self._video_folder = Path(video_folder)
        self._subtitle_folder = Path(subtitle_folder)
        self._pair_fn = pair_fn

    def run(self) -> None:
        _subs_in_v, videos = find_files(self._video_folder)
        subs, _videos_in_s = find_files(self._subtitle_folder)
        self.finished.emit(self._pair_fn(videos, subs))


class MuxWorker(QObject):
    """封裝批次 worker;逐檔跑 process_mux,支援取消與檔名衝突保護。"""

    progress = Signal(int, int)
    file_progress = Signal(int)
    file_done = Signal(str, str)
    message = Signal(str)
    finished = Signal(int, int, int)

    def __init__(self, pairs, meta: MuxMeta, operation, tools,
                 output_dir: Optional[Path], process_fn=process_mux) -> None:
        super().__init__()
        self._pairs = list(pairs)
        self._meta = meta
        self._operation = operation
        self._tools = tools
        self._output_dir = output_dir
        self._process_fn = process_fn
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._pairs)
        ok = skipped = error = 0
        seen_basenames: set[str] = set()
        for i, pair in enumerate(self._pairs, start=1):
            if self._cancelled:
                self.message.emit("已取消,停止後續檔案")
                break
            name = pair.video_path.name
            if self._output_dir is not None and name in seen_basenames:
                error += 1
                self.file_done.emit(name, "error")
                self.message.emit(
                    "    輸出檔名衝突: 已有同名檔案寫入輸出資料夾,略過此檔")
                self.progress.emit(i, total)
                continue
            out = (self._output_dir / name
                   if self._output_dir is not None else None)
            try:
                report = self._process_fn(
                    pair, self._meta, self._operation, self._tools,
                    out_path=out, progress_cb=self.file_progress.emit)
            except Exception as exc:  # 單檔失敗不中斷整批
                error += 1
                self.file_done.emit(name, "error")
                self.message.emit(f"    處理失敗: {exc}")
                self.progress.emit(i, total)
                continue
            if report.status == "ok":
                ok += 1
                if self._output_dir is not None:
                    seen_basenames.add(name)
            elif report.status == "skipped":
                skipped += 1
            else:
                error += 1
            self.file_done.emit(name, report.status)
            for msg in report.messages:
                self.message.emit(f"    {msg}")
            self.progress.emit(i, total)
        self.finished.emit(ok, skipped, error)
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_mux_worker.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```powershell
git add ass_style_tool/qt/batch_worker.py tests/test_mux_worker.py
git commit -m "feat: add mux scan and batch workers with collision guard"
```

---

### Task 3: mux_tab.py — 封裝分頁 UI

**Files:**
- Create: `ass_style_tool/qt/mux_tab.py`
- Test: `tests/test_mux_tab.py`

**Interfaces:**
- Consumes: `batch_worker.MuxScanWorker/MuxWorker`、`mkv_mux.MuxMeta/MuxPair`、`mkv_batch.MkvTools`、`scale_panel.ScalePanel`、`scale_engine.ScaleError`、`tools.mkvmerge_path/mkvextract_path`
- Produces:
  - `MuxTab(QWidget)`:建構子 `(get_profile: Callable[[], Profile])`;signal `log(str)`
  - 可測 API:`populate(pairs: list[MuxPair])`(建表格,matched 列預設勾選、其他不勾)、`checked_pairs() -> list[MuxPair]`(只回勾選且 matched)、`current_meta() -> MuxMeta`(從語言/軌名/default/forced 控件讀)、`tools_available: bool`、`_auto_scan()`、`shutdown()`
  - UI:影片資料夾列(拖放+瀏覽)、字幕資料夾列(瀏覽)、配對表格(勾選/影片/字幕/集數/狀態)、軌資訊列(語言下拉、軌名、default 勾選、forced 勾選)、封裝前處理(不處理/套用樣式/縮放 三選;縮放時顯示 ScalePanel)、輸出模式(資料夾[預設]/取代原檔)、重新掃描/開始封裝/取消、整批+單檔進度
  - 自動掃描:兩個資料夾都有效時,任一資料夾選好即自動配對掃描(`_auto_scan`)
  - 缺工具:`tools_available` False → 停用控制 + 提示

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_mux_tab.py`:

```python
from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_mux import MuxPair
from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values


def _tab(monkeypatch, available=True):
    fake = (lambda: Path("x.exe")) if available else (lambda: None)
    monkeypatch.setattr("ass_style_tool.qt.mux_tab.mkvmerge_path", fake)
    monkeypatch.setattr("ass_style_tool.qt.mux_tab.mkvextract_path", fake)
    from ass_style_tool.qt.mux_tab import MuxTab
    return MuxTab(lambda: profile_from_values(DEFAULT_VALUES))


PAIRS = [
    MuxPair(Path("a [01].mkv"), Path("a [01].ass"), 1, "matched"),
    MuxPair(Path("b [02].mkv"), None, 2, "no_subtitle"),
    MuxPair(Path("c [03].mkv"), Path("c [03].ass"), 3, "matched"),
]


def test_populate_checks_matched_only(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    assert tab.table.rowCount() == 3
    checked = tab.checked_pairs()
    assert {p.video_path for p in checked} == {Path("a [01].mkv"), Path("c [03].mkv")}


def test_checked_pairs_respects_unchecking(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    tab.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    checked = tab.checked_pairs()
    assert {p.video_path for p in checked} == {Path("c [03].mkv")}


def test_current_meta(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.trackname_edit.setText("繁中")
    tab.default_check.setChecked(True)
    tab.forced_check.setChecked(False)
    meta = tab.current_meta()
    assert meta.track_name == "繁中"
    assert meta.default is True
    assert meta.forced is False
    assert meta.language                      # 有語言值(下拉預設)


def test_mode_switch_shows_scale_panel(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.scale_panel.isHidden() is True
    tab.scale_mode_radio.setChecked(True)
    assert tab.scale_panel.isHidden() is False


def test_run_button_enabled_after_populate(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.run_button.isEnabled() is False
    tab.populate(PAIRS)
    assert tab.run_button.isEnabled() is True


def test_tools_missing_disables(qapp, monkeypatch):
    tab = _tab(monkeypatch, available=False)
    assert tab.tools_available is False
    assert tab.run_button.isEnabled() is False
    assert tab.scan_button.isEnabled() is False


def test_operation_none_when_direct(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.direct_mode_radio.setChecked(True)
    assert tab.current_operation() is None


def test_operation_profile_when_apply(qapp, monkeypatch):
    from ass_style_tool.profile import Profile
    tab = _tab(monkeypatch)
    tab.apply_mode_radio.setChecked(True)
    assert isinstance(tab.current_operation(), Profile)
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_mux_tab.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.qt.mux_tab'`

- [ ] **Step 3: 實作 mux_tab.py**

建立 `ass_style_tool/qt/mux_tab.py`:

```python
"""「封裝」分頁:把外部 .ass 字幕依集數配對後 mux 進 MKV。"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QProgressBar, QPushButton,
                               QRadioButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..mkv_batch import MkvTools
from ..mkv_mux import MuxMeta, MuxPair
from ..profile import Profile
from ..scale_engine import ScaleError
from ..tools import mkvextract_path, mkvmerge_path
from .batch_worker import MuxScanWorker, MuxWorker
from .scale_panel import ScalePanel

_HEADERS = ["封裝", "影片", "字幕", "集數", "狀態"]
_STATUS_LABELS = {"matched": "已配對", "no_subtitle": "無對應字幕",
                  "ambiguous": "配對模糊", "no_episode": "無法判斷集數"}
# 常見字幕語言(mkvmerge 用 ISO 639-2)
_LANGUAGES = [("中文", "chi"), ("日文", "jpn"), ("英文", "eng"),
              ("未定", "und")]


class MuxTab(QWidget):
    log = Signal(str)

    def __init__(self, get_profile: Callable[[], Profile]) -> None:
        super().__init__()
        self._get_profile = get_profile
        self._pairs: List[MuxPair] = []
        self._thread: Optional[QThread] = None
        self._worker = None
        self._scan_thread: Optional[QThread] = None
        self._scan_worker = None
        self._scanned_key: Optional[tuple] = None
        self.setAcceptDrops(True)

        mkvmerge = mkvmerge_path()
        mkvextract = mkvextract_path()
        self.tools_available = mkvmerge is not None and mkvextract is not None
        self._tools = (MkvTools(mkvmerge, mkvextract)
                       if self.tools_available else None)

        root = QVBoxLayout(self)
        if not self.tools_available:
            warn = QLabel("⚠ 找不到 mkvmerge:請安裝 MKVToolNix 後重新啟動"
                          "(封裝功能已停用)")
            warn.setStyleSheet("color: #d08a00;")
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
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        # 軌資訊
        meta_row = QHBoxLayout()
        meta_row.addWidget(QLabel("語言:"))
        self.language_combo = QComboBox()
        for label, code in _LANGUAGES:
            self.language_combo.addItem(f"{label} ({code})", code)
        meta_row.addWidget(self.language_combo)
        meta_row.addWidget(QLabel("軌名:"))
        self.trackname_edit = QLineEdit()
        meta_row.addWidget(self.trackname_edit, 1)
        self.default_check = QCheckBox("預設軌")
        self.forced_check = QCheckBox("強制軌")
        meta_row.addWidget(self.default_check)
        meta_row.addWidget(self.forced_check)
        root.addLayout(meta_row)

        # 封裝前處理
        op_row = QHBoxLayout()
        op_row.addWidget(QLabel("封裝前:"))
        self.direct_mode_radio = QRadioButton("原字幕直接封")
        self.direct_mode_radio.setChecked(True)
        self.apply_mode_radio = QRadioButton("先套用目前樣式")
        self.scale_mode_radio = QRadioButton("先縮放字級")
        op_row.addWidget(self.direct_mode_radio)
        op_row.addWidget(self.apply_mode_radio)
        op_row.addWidget(self.scale_mode_radio)
        op_row.addStretch(1)
        root.addLayout(op_row)

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
        self.replace_radio = QRadioButton("取代原影片(驗證後覆蓋)")
        out_row.addWidget(self.outdir_radio)
        out_row.addWidget(self.outdir_edit, 1)
        out_row.addWidget(out_browse)
        out_row.addWidget(self.replace_radio)
        root.addLayout(out_row)

        action_row = QHBoxLayout()
        self.scan_button = QPushButton("重新掃描")
        self.scan_button.clicked.connect(self._on_scan)
        self.run_button = QPushButton("開始封裝")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._on_run)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._on_cancel)
        for b in (self.scan_button, self.run_button, self.cancel_button):
            action_row.addWidget(b)
        action_row.addStretch(1)
        root.addLayout(action_row)

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
            for b in (self.scan_button, self.run_button):
                b.setEnabled(False)

    # ---------- 拖放 / 檔案選擇 ----------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and Path(path).is_dir():
                self.video_edit.setText(path)
                self._auto_scan()
                break

    def _browse_video(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇影片資料夾")
        if path:
            self.video_edit.setText(path)
            self._auto_scan()

    def _browse_subtitle(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇字幕資料夾")
        if path:
            self.subtitle_edit.setText(path)
            self._auto_scan()

    def _browse_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "選擇輸出資料夾")
        if path:
            self.outdir_edit.setText(path)
            self.outdir_radio.setChecked(True)

    # ---------- 掃描 ----------
    def _auto_scan(self) -> None:
        if not self.tools_available:
            return
        v = self.video_edit.text().strip()
        s = self.subtitle_edit.text().strip()
        if not (v and s and Path(v).is_dir() and Path(s).is_dir()):
            return
        if (v, s) == self._scanned_key:
            return
        if self._scan_thread is not None or self._thread is not None:
            return
        self._on_scan()

    def _on_scan(self) -> None:
        if self._thread is not None:
            self.log.emit("封裝進行中,請稍後再掃描")
            return
        v = self.video_edit.text().strip()
        s = self.subtitle_edit.text().strip()
        if not (v and s and Path(v).is_dir() and Path(s).is_dir()):
            self.log.emit("請先選擇有效的影片與字幕資料夾")
            return
        self._scanned_key = (v, s)
        self.scan_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self._scan_thread = QThread()
        self._scan_worker = MuxScanWorker(Path(v), Path(s))
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_scan_done)
        self._scan_thread.start()

    def _on_scan_done(self, pairs: list) -> None:
        if self._scan_thread is not None:
            self._scan_thread.quit()
            self._scan_thread.wait()
        self._scan_thread = None
        self._scan_worker = None
        self.scan_button.setEnabled(True)
        self.populate(pairs)
        matched = sum(1 for p in pairs if p.status == "matched")
        self.log.emit(f"配對完成:{len(pairs)} 部影片,{matched} 部有對應字幕")

    def populate(self, pairs: List[MuxPair]) -> None:
        self._pairs = list(pairs)
        self.table.setRowCount(len(pairs))
        for r, pair in enumerate(pairs):
            check = QTableWidgetItem()
            check.setFlags(check.flags() | Qt.ItemIsUserCheckable)
            check.setCheckState(
                Qt.CheckState.Checked if pair.status == "matched"
                else Qt.CheckState.Unchecked)
            self.table.setItem(r, 0, check)
            self.table.setItem(r, 1, QTableWidgetItem(pair.video_path.name))
            self.table.setItem(
                r, 2, QTableWidgetItem(
                    pair.subtitle_path.name if pair.subtitle_path else "-"))
            self.table.setItem(
                r, 3, QTableWidgetItem(
                    f"{pair.episode:02d}" if pair.episode is not None else "?"))
            self.table.setItem(
                r, 4, QTableWidgetItem(
                    _STATUS_LABELS.get(pair.status, pair.status)))
        self.run_button.setEnabled(
            self.tools_available and any(p.status == "matched" for p in pairs)
            and self._thread is None)

    def checked_pairs(self) -> List[MuxPair]:
        result = []
        for r, pair in enumerate(self._pairs):
            item = self.table.item(r, 0)
            if (item is not None and item.checkState() == Qt.CheckState.Checked
                    and pair.status == "matched"):
                result.append(pair)
        return result

    # ---------- 軌資訊 / 操作 ----------
    def current_meta(self) -> MuxMeta:
        return MuxMeta(
            language=self.language_combo.currentData(),
            track_name=self.trackname_edit.text().strip(),
            default=self.default_check.isChecked(),
            forced=self.forced_check.isChecked())

    def current_operation(self):
        if self.scale_mode_radio.isChecked():
            return self.scale_panel.get_options()
        if self.apply_mode_radio.isChecked():
            return self._get_profile()
        return None

    def _output_dir(self) -> Optional[Path]:
        if self.replace_radio.isChecked():
            return None
        text = self.outdir_edit.text().strip()
        return Path(text) if text else None

    # ---------- 執行 ----------
    def _on_run(self) -> None:
        if self._scan_thread is not None or self._thread is not None:
            self.log.emit("已有掃描或封裝進行中")
            return
        pairs = self.checked_pairs()
        if not pairs:
            self.log.emit("沒有勾選任何可封裝的影片")
            return
        try:
            operation = self.current_operation()
        except (ScaleError, ValueError) as exc:
            self.log.emit(f"參數錯誤: {exc}")
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
        self._worker = MuxWorker(pairs, self.current_meta(), operation,
                                 self._tools, output_dir)
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
        self.log.emit(f"封裝完成:成功 {ok},跳過 {skipped},錯誤 {error}")
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self.scan_button.setEnabled(True)
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def shutdown(self) -> None:
        for thread in (self._thread, self._scan_thread):
            if thread is not None:
                thread.quit()
                thread.wait()
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_mux_tab.py -v`
Expected: 8 passed

- [ ] **Step 5: 跑全套確認無回歸**

Run: `py -m pytest tests -v`
Expected: 252 passed(239 + 5 + 8)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/qt/mux_tab.py tests/test_mux_tab.py
git commit -m "feat: add mux tab (pair videos+subtitles, track meta, batch mux)"
```

---

### Task 4: 整合 — 主視窗接入 MuxTab

**Files:**
- Modify: `ass_style_tool/qt/main_window.py`

**Interfaces:**
- Consumes: `mux_tab.MuxTab`
- Produces: 在「MKV」分頁之後新增「封裝」分頁;log 接線;closeEvent 加 `mux_tab.shutdown()`

- [ ] **Step 1: 修改 main_window.py**

(a)import 區加(併入既有 `.mkv_tab` import 附近):

```python
from .mux_tab import MuxTab
```

(b)在 `self.tabs.addTab(self.mkv_tab, "MKV")` 那行之後、預覽分頁之前加:

```python
        self.mux_tab = MuxTab(self.style_editor.current_profile)
        self.mux_tab.log.connect(self.append_log)
        self.tabs.addTab(self.mux_tab, "封裝")
```

(c)`closeEvent` 中 `self.mkv_tab.shutdown()` 之後加:

```python
        self.mux_tab.shutdown()
```

- [ ] **Step 2: 全套測試 + import + 啟動冒煙**

Run: `py -m pytest tests -v`
Expected: 252 passed

Run: `py -c "import ass_style_tool.qt.main_window; print('ok')"`
Expected: `ok`

```powershell
$p = Start-Process -FilePath "py" -ArgumentList "-m","ass_style_tool" -WorkingDirectory "C:\Claude_code" -PassThru
Start-Sleep -Seconds 3
if ($p.HasExited) { Write-Output "FAIL exit=$($p.ExitCode)" } else { Write-Output "OK"; Stop-Process -Id $p.Id }
```

Expected: `OK`

- [ ] **Step 3: 手動冒煙清單(由使用者以真實檔案執行,記於報告)**

Run: `py -m ass_style_tool`
1. 出現「封裝」分頁,工具齊全時控制可用
2. 選影片資料夾 + 字幕資料夾 → 自動配對,表格列出影片↔字幕↔集數↔狀態,matched 列預設勾選
3. 設語言/軌名/預設/強制;「原字幕直接封」+「輸出到資料夾」跑一批 → 輸出 MKV 用播放器開啟:新字幕軌在、語言/軌名正確、原有音視訊/章節完好
4. 改「先套用目前樣式」再跑 → 封進去的字幕已套用樣式面板的設定
5. 「先縮放字級」+ 縮放面板設倍率 → 封進去的字幕字級已縮放
6. 「取代原影片」模式(拿可犧牲的測試檔)→ 完成後原影片已含新字幕且可播放
7. 多檔執行中「取消」→ 當前檔完成後停止

- [ ] **Step 4: Commit**

```powershell
git add ass_style_tool/qt/main_window.py
git commit -m "feat: wire mux tab into main window"
```

---

## 本計畫完成後

v2 功能面再擴一塊:除了改樣式/縮放/預覽/處理 MKV 內字幕,現在也能把外部字幕封裝進 MKV。剩 **Plan 3 — 打包**(PyInstaller + Inno Setup)。
