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
from .scale_engine import ScaleOptions, scale_file
from .subprocess_utils import no_window_kwargs


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
                                encoding="utf-8", timeout=120,
                                **no_window_kwargs())
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
            try:
                os.replace(target, mkv_path)
            except OSError as exc:
                if target.exists():
                    target.unlink()
                return MkvFileReport(
                    Path(mkv_path), "error",
                    report.messages + [f"取代原檔失敗: {exc}"])
            report.messages.append("已驗證並取代原檔")
        return report
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
