"""GUI 用的純邏輯輔助:預覽表格列建構、字型缺失判斷(不依賴 Qt)。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..ass_style import compute_applied_values
from ..profile import Profile
from ..scale_engine import ScaleOptions, fmt_num
from ..style_scan import FileStyles

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
    plan: str = ""


def preview_rows(scan,
                 plans: Optional[Dict[Path, str]] = None) -> List[PreviewRow]:
    plans = plans or {}
    rows: List[PreviewRow] = []
    for m in scan.matches:
        episode = f"{m.episode:02d}" if m.episode is not None else "?"
        video = m.video_path.name if m.video_path is not None else "-"
        rows.append(PreviewRow(
            episode=episode,
            sub_name=m.sub_path.name,
            video_name=video,
            status_label=STATUS_LABELS.get(m.status, m.status),
            plan=plans.get(m.sub_path, ""),
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


def apply_plan_text(file_styles: Optional[FileStyles], profile: Profile,
                    target_names: Sequence[str]) -> str:
    """「預計」欄文字:目標樣式在這個檔案會從幾號變成幾號。

    字級之外的欄位(外框/陰影/邊距)也會被改,但表格一欄塞不下,
    字級是最能一眼看出縮放對不對的代表值。
    """
    if file_styles is None:
        return ""
    if file_styles.error is not None:
        return "⚠ 無法讀取"
    if not target_names:
        return "⊘ 未選樣式"
    applied = compute_applied_values(profile, *file_styles.play_res)
    parts = [
        f"{name} {fmt_num(file_styles.styles[name])} "
        f"→ {fmt_num(applied.fontsize)}"
        for name in target_names if name in file_styles.styles
    ]
    if not parts:
        return f"⊘ 找不到 {'、'.join(target_names)}"
    return "、".join(parts)


def scale_plan_text(file_styles: Optional[FileStyles],
                    options: ScaleOptions) -> str:
    """縮放模式的「預計」欄文字。"""
    if file_styles is None:
        return ""
    if file_styles.error is not None:
        return "⚠ 無法讀取"
    base = file_styles.styles.get(options.base_style)
    if base is None:
        return f"⊘ 找不到基準樣式 {options.base_style}"
    if options.factor is not None:
        factor = options.factor
    elif options.target_size is not None and base:
        factor = options.target_size / base
    else:
        return ""
    return (f"{options.base_style} {fmt_num(base)} "
            f"→ {fmt_num(base * factor)}(×{fmt_num(factor)})")
