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
