"""資訊面板的資料組裝:某個軌道 ID 在各檔案的實際狀況(純邏輯,無 Qt)。

規則是依軌道 ID 套用的,但同一個 ID 在不同檔案未必是同一種軌道——
type_matches 就是用來讓使用者看出這件事。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .mkv_io import MediaTrack


@dataclass
class TrackInfoRow:
    video_name: str
    found: bool             # 該檔有沒有這個軌道 ID
    type_matches: bool      # 有,且類型與範本相同(found 為 False 時一律 False)
    track_type: str         # 該檔這個 ID 實際的類型(找不到時為 "")
    default: Optional[bool] # 類型不符或找不到時為 None
    forced: Optional[bool]
    track_name: str
    language: str


def build_track_info_rows(
    track_id: int,
    template_type: str,
    tracks_by_file: Dict[Path, List[MediaTrack]],
) -> List[TrackInfoRow]:
    """依檔名排序,回傳每部影片對這個軌道 ID 的狀況。"""
    rows: List[TrackInfoRow] = []
    for path in sorted(tracks_by_file, key=lambda p: p.name):
        track = next(
            (t for t in tracks_by_file[path] if t.track_id == track_id), None)
        if track is None:
            rows.append(TrackInfoRow(
                video_name=path.name, found=False, type_matches=False,
                track_type="", default=None, forced=None,
                track_name="", language=""))
            continue
        if track.track_type != template_type:
            # ID 在,但不是同一種軌道:該檔不會套用這條設定
            rows.append(TrackInfoRow(
                video_name=path.name, found=True, type_matches=False,
                track_type=track.track_type, default=None, forced=None,
                track_name="", language=""))
            continue
        rows.append(TrackInfoRow(
            video_name=path.name, found=True, type_matches=True,
            track_type=track.track_type, default=track.default,
            forced=track.forced, track_name=track.track_name,
            language=track.language))
    return rows
