"""依「語言 + 軌名」把範本檔上選定的字幕軌解析到整批影片(純邏輯,無 Qt)。

MKV 分頁的字幕軌選擇改成「在範本檔上定規則、整批套用」之後,需要一組不
依賴 Qt 的函式:把規則解析成逐檔的軌清單、產生逐檔驗證面板的內容、以及
算出有多少軌沒被任何規則涵蓋(範本檔只代表一個檔案,其他檔案可能有它
沒有的軌;這些軌會被靜默略過,呼叫端要能把數字講出來)。

刻意不用軌 ID 當鍵:同一季裡某集多一條音訊軌就會把字幕軌的 ID 推掉,
依 ID 會套到另一種語言的字幕上。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple

from .mkv_batch import track_key
from .mkv_io import SubtitleTrack

#: (語言, 軌名)
TrackKey = Tuple[str, str]


def all_keys(files_tracks: Dict[Path, List[SubtitleTrack]]) -> Set[TrackKey]:
    """整批影片出現過的所有鍵。"""
    return {track_key(t) for tracks in files_tracks.values() for t in tracks}


def resolve_tracks(
    keys: Set[TrackKey],
    files_tracks: Dict[Path, List[SubtitleTrack]],
) -> Dict[Path, List[SubtitleTrack]]:
    """把鍵集合解析成逐檔要套用的軌清單。

    一個檔案有多條軌符合同一個鍵時全部納入(呼叫端的資訊面板會標 ⚠)。
    沒有任何軌符合的檔案不會出現在結果中——批次執行時等於跳過。
    """
    result: Dict[Path, List[SubtitleTrack]] = {}
    for path, tracks in files_tracks.items():
        picked = [t for t in tracks if track_key(t) in keys]
        if picked:
            result[path] = picked
    return result


@dataclass
class SelectInfoRow:
    video_name: str
    track_ids: List[int]   # 空 = 找不到;長度 > 1 = 多條符合


def build_select_info_rows(
    key: TrackKey,
    files_tracks: Dict[Path, List[SubtitleTrack]],
) -> List[SelectInfoRow]:
    """逐檔資訊面板的內容:一個鍵在每部影片解析到哪幾條軌。依檔名排序。"""
    rows: List[SelectInfoRow] = []
    for path in sorted(files_tracks, key=lambda p: p.name):
        ids = [t.track_id for t in files_tracks[path] if track_key(t) == key]
        rows.append(SelectInfoRow(video_name=path.name, track_ids=ids))
    return rows


def uncovered_track_count(
    keys: Set[TrackKey],
    files_tracks: Dict[Path, List[SubtitleTrack]],
) -> Tuple[int, int]:
    """回傳 (含未涵蓋軌的影片數, 未涵蓋軌總數)。

    「未涵蓋」= 該檔有 ASS 字幕軌,但它的鍵不在 keys 裡。
    """
    videos = 0
    tracks = 0
    for file_tracks in files_tracks.values():
        count = sum(1 for t in file_tracks if track_key(t) not in keys)
        if count:
            videos += 1
            tracks += count
    return videos, tracks
