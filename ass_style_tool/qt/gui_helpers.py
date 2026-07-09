"""GUI 用的純邏輯輔助:預覽表格列建構、字型缺失判斷(不依賴 Qt)。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

STATUS_LABELS = {
    "matched": "已配對",
    "no_video": "無對應影片",
    "ambiguous": "配對模糊",
    "no_episode": "無法判斷集數",
}


@dataclass
class PreviewRow:
    episode: str
    sub_name: str
    video_name: str
    status_label: str


def preview_rows(scan) -> List[PreviewRow]:
    rows: List[PreviewRow] = []
    for m in scan.matches:
        episode = f"{m.episode:02d}" if m.episode is not None else "?"
        video = m.video_path.name if m.video_path is not None else "-"
        rows.append(PreviewRow(
            episode=episode,
            sub_name=m.sub_path.name,
            video_name=video,
            status_label=STATUS_LABELS.get(m.status, m.status),
        ))
    return rows


def font_is_missing(fontname: str, available_families: List[str]) -> bool:
    name = fontname.strip().lower()
    if not name:
        return False
    return name not in {fam.lower() for fam in available_families}
