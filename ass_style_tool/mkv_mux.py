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
from .subprocess_utils import no_window_kwargs


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
