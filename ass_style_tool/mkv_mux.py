"""把外部 .ass 字幕封裝(mux)進 MKV 的純邏輯:配對、命令組裝、單檔管線。

外部程序(mux/驗證)以函式參數注入,預設綁定實作;測試注入假函式。
復用 mkv_batch 的封裝前處理(transform_track_file)與取代驗證(identify_ok)。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .episode_match import extract_episode
from .mkv_batch import (MkvFileReport, MkvTools, identify_ok,
                        transform_track_file)
from .mkv_io import list_all_tracks

_logger = logging.getLogger(__name__)
from .subprocess_utils import no_window_kwargs
from .track_edit import build_source_track_flags


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


def _default_mux(video_path, subtitle_path, out_path, meta, mkvmerge,
                 progress_cb=None, source_flags=None):
    """回傳 (成功?, 最後幾行輸出)。

    最後這幾行只在失敗時派上用場(process_mux 會附進錯誤訊息),讓使用者
    知道 mkvmerge 到底在抱怨什麼,而不是只看到「封裝失敗」四個字。
    """
    from .mkv_io import parse_progress
    cmd = build_mux_command(video_path, subtitle_path, out_path, meta, mkvmerge,
                            source_flags)
    tail: "deque[str]" = deque(maxlen=10)
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            **no_window_kwargs())
    except OSError:
        return False, []
    assert proc.stdout is not None
    for line in proc.stdout:
        tail.append(line.rstrip("\n"))
        if progress_cb is not None:
            pct = parse_progress(line)
            if pct is not None:
                progress_cb(pct)
    proc.wait()
    return proc.returncode in (0, 1), list(tail)


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

        # 來源軌道清單:edits 要靠它組旗標,取代原檔模式還要靠它確認來源
        # 是否本來就有視訊軌(見下方 out_path is None 分支的安全檢查)。
        source_tracks: List = []
        if edits or out_path is None:
            try:
                source_tracks = track_list_fn(video, tools.mkvmerge)
            except Exception:
                # 這裡不是「選配功能缺失」——mkvmerge 這個時間點已經確定
                # 存在(tools.mkvmerge 是呼叫端算好傳進來的),掃軌失敗代表
                # mkvmerge 本身出錯或這個檔案有問題,不是日常會發生的事。
                # 不改變原本的容錯行為(source_tracks 退回空清單,照常往下
                # 走,下面的分支會告訴使用者「本檔未套用軌道修改」),只是
                # 把完整 traceback 記下來,不然使用者回報「這個檔案的軌道
                # 修改怎麼都套用不到」時完全無從查起。
                _logger.exception(
                    "掃描來源軌道失敗:%s", video.name)
                source_tracks = []

        source_flags: List[str] = []
        if edits:
            if source_tracks:
                source_flags = build_source_track_flags(edits, source_tracks)
            else:
                # 掃軌失敗 → 不做軌道修改,照常封裝,但要讓使用者知道
                # 設定的軌道修改這一檔其實沒套用,而不是靜默跳過。
                report.messages.append("讀不到軌道資訊,本檔未套用軌道修改")

        mux_result = mux_fn(video, subtitle, target, meta, tools.mkvmerge,
                            progress_cb, source_flags)
        # _default_mux 回傳 (成功?, 最後幾行輸出);測試注入的假 mux_fn
        # 大多仍是舊介面(只回傳 bool)——兩種都接受,不強迫全部改寫。
        if isinstance(mux_result, tuple):
            mux_ok, mux_tail = mux_result
        else:
            mux_ok, mux_tail = mux_result, []
        if not mux_ok:
            if out_path is None and target.exists():
                target.unlink()
            messages = report.messages + ["mkvmerge 封裝失敗,原檔未變動"]
            if mux_tail:
                messages.append("mkvmerge 輸出: " + " | ".join(mux_tail))
            return MkvFileReport(video, "error", messages)

        if out_path is None:
            if not verify_fn(target, tools.mkvmerge):
                if target.exists():
                    target.unlink()
                return MkvFileReport(
                    video, "error", report.messages + ["輸出驗證失敗,保留原檔"])
            if any(t.track_type == "video" for t in source_tracks):
                # 來源本來有視訊軌;丟軌設定(如取消勾選視訊的「保留」)可能讓
                # 輸出變成只剩音訊/字幕。這種輸出拿去覆蓋原檔是不可逆的資料
                # 遺失,必須擋下——與丟音軌/字幕軌不同,那多半是有意的。
                output_tracks = track_list_fn(target, tools.mkvmerge)
                if not any(t.track_type == "video" for t in output_tracks):
                    if target.exists():
                        target.unlink()
                    return MkvFileReport(
                        video, "error",
                        report.messages + ["輸出缺少視訊軌,已保留原檔"])
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
