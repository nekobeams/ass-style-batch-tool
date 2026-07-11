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


@dataclass
class DialogueLine:
    start_ms: int
    end_ms: int
    text: str


def format_timestamp(ms: int) -> str:
    """毫秒 → 'H:MM:SS.cc'(ASS 慣用時間格式)。"""
    total_cs = int(round(ms / 10))
    hours, rem = divmod(total_cs, 360000)
    minutes, rem = divmod(rem, 6000)
    seconds, centis = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centis:02d}"


def dialogue_lines(subs) -> List[DialogueLine]:
    """取出非 Comment 的事件行;文字去 override 標籤、\\N 摺成空格。"""
    lines: List[DialogueLine] = []
    for event in subs.events:
        if event.is_comment:
            continue
        text = " ".join(event.plaintext.split())
        lines.append(DialogueLine(start_ms=event.start, end_ms=event.end,
                                  text=text))
    return lines
