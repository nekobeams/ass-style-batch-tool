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
