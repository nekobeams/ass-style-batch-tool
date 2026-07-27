"""從檔名抽取集數編號,並把字幕檔與影片檔配對。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SUB_EXTS = {".ass", ".ssa", ".srt"}
VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".webm", ".mov", ".flv", ".wmv"}


def ass_output_name(src: Path) -> Path:
    """輸出檔名決策:.ass/.ssa 保留原副檔名(維持既有行為);其他(如 .srt)
    正規化成 .ass(輸出一律為 ASS 內容)。回傳含原目錄的完整路徑。"""
    if src.suffix.lower() in {".ass", ".ssa"}:
        return src
    return src.with_suffix(".ass")


#: 幾乎可以肯定是解析度而非集數的 1-3 位數字
_NON_EPISODE_NUMBERS = {480, 540, 576, 720, 960}

#: 依優先序嘗試的集數樣式
_PATTERNS = [
    re.compile(r"S\d{1,2}E(\d{1,3})", re.IGNORECASE),          # S01E05
    re.compile(r"\bEP?(\d{1,3})\b", re.IGNORECASE),             # E05 / EP05
    re.compile(r"\[(\d{1,3})(?:v\d)?\]"),                       # [05] / [05v2]
    re.compile(r"[ _]-[ _](\d{1,3})(?=[ _\[\(.]|$)"),           # " - 05 "
]


def extract_episode(filename: str) -> Optional[int]:
    name = Path(filename).name
    for pattern in _PATTERNS:
        for match in pattern.finditer(name):
            value = int(match.group(1))
            if value in _NON_EPISODE_NUMBERS:
                continue
            return value
    return None


@dataclass
class MatchResult:
    sub_path: Path
    episode: Optional[int]
    video_path: Optional[Path] = None
    video_resolution: Optional[Tuple[int, int]] = None
    status: str = "no_video"  # matched | no_video | ambiguous | no_episode


def find_files(folder: Path) -> Tuple[List[Path], List[Path]]:
    """列出資料夾**當層**的字幕檔與影片檔(不進子資料夾)。

    刻意不遞迴:整季素材放同一層是常態,而遞迴會把不相干的子資料夾一起
    掃進來,還讓「不同子資料夾同名影片」在以檔名當 key 的面板裡撞在一起。
    """
    subs: List[Path] = []
    videos: List[Path] = []
    for path in sorted(Path(folder).glob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext in SUB_EXTS:
            subs.append(path)
        elif ext in VIDEO_EXTS:
            videos.append(path)
    return subs, videos


def match_pairs(
    sub_paths: List[Path], video_paths: List[Path]
) -> List[MatchResult]:
    videos_by_ep: Dict[int, List[Path]] = {}
    for video in video_paths:
        ep = extract_episode(video.name)
        if ep is not None:
            videos_by_ep.setdefault(ep, []).append(video)

    sub_eps = [extract_episode(sub.name) for sub in sub_paths]
    sub_ep_counts: Dict[int, int] = {}
    for ep in sub_eps:
        if ep is not None:
            sub_ep_counts[ep] = sub_ep_counts.get(ep, 0) + 1

    results: List[MatchResult] = []
    for sub, ep in zip(sub_paths, sub_eps):
        if ep is None:
            results.append(MatchResult(sub_path=sub, episode=None, status="no_episode"))
            continue
        candidates = videos_by_ep.get(ep, [])
        if sub_ep_counts[ep] > 1 or len(candidates) > 1:
            results.append(MatchResult(sub_path=sub, episode=ep, status="ambiguous"))
        elif len(candidates) == 1:
            results.append(
                MatchResult(sub_path=sub, episode=ep,
                            video_path=candidates[0], status="matched")
            )
        else:
            results.append(MatchResult(sub_path=sub, episode=ep, status="no_video"))
    return results
