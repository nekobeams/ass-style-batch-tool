"""MKV 字幕軌的列舉、抽取與重封裝(呼叫 mkvmerge/mkvextract)。"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .subprocess_utils import no_window_kwargs

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
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, encoding="utf-8",
            **no_window_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        return []
    return parse_ass_tracks(data)


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
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300, encoding="utf-8",
            **no_window_kwargs(),
        )
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
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **no_window_kwargs(),
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            if progress_cb is not None:
                pct = parse_progress(line)
                if pct is not None:
                    progress_cb(pct)
        proc.wait()
        return proc.returncode in (0, 1)
    except OSError:
        return False
