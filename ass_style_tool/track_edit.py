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
    track_type: Optional[str] = None     # 這條設定是為哪種軌道建立的;
                                         # None = 不比對(維持舊行為)


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
