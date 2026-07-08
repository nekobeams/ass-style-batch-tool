"""預覽用暫存字幕產生:套用目前樣式到來源字幕的複本,供 mpv 重載。"""
from __future__ import annotations

from pathlib import Path
from typing import List

from .ass_style import apply_profile, load_subs, save_subs
from .profile import Profile


def render_preview_ass(
    source_ass_path: Path, profile: Profile, out_path: Path
) -> List[str]:
    """讀來源 .ass、套用 profile(縮放規則與批次一致)、寫到 out_path。

    來源檔不被修改(load_subs 每次從磁碟讀新的物件)。回傳實際改到的 Style 名稱。
    """
    subs = load_subs(source_ass_path)
    modified = apply_profile(subs, profile)
    save_subs(subs, out_path)
    return modified
