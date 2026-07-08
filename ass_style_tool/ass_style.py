"""ASS 檔案讀寫(含編碼偵測)與目標樣式套用。"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import pysubs2
from charset_normalizer import from_bytes

from .profile import Profile, parse_ass_color
from .resolution import compute_scale, reference_resolution


def detect_and_decode(path: Path) -> str:
    """讀檔並解碼:先試 utf-8-sig(涵蓋含/不含 BOM 的 UTF-8),
    失敗再用 charset-normalizer 統計偵測(涵蓋 Big5/GBK 等)。"""
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    best = from_bytes(raw).best()
    if best is None:
        raise ValueError(f"無法判斷檔案編碼: {path}")
    return str(best)


def load_subs(path: Path) -> pysubs2.SSAFile:
    return pysubs2.SSAFile.from_string(detect_and_decode(path))


def save_subs(subs: pysubs2.SSAFile, path: Path) -> None:
    """一律輸出 UTF-8 with BOM(Aegisub 預設)。"""
    Path(path).write_text(subs.to_string("ass"), encoding="utf-8-sig")


def get_play_res(subs: pysubs2.SSAFile) -> Tuple[int, int]:
    def _read(key: str) -> int:
        try:
            return int(float(subs.info.get(key, 0)))
        except (TypeError, ValueError):
            return 0

    return _read("PlayResX"), _read("PlayResY")


def get_scaled_border_shadow(subs: pysubs2.SSAFile) -> str:
    return str(subs.info.get("ScaledBorderAndShadow", "unset"))


def apply_profile(subs: pysubs2.SSAFile, profile: Profile) -> List[str]:
    """把 profile 的目標樣式套用到指定名稱的 Style(依 PlayRes 規則縮放)。

    只修改 [V4+ Styles] 中對應的行;絕不改寫 Script Info 標頭、
    不新增 Style。回傳實際修改到的 Style 名稱。
    """
    ref_w, ref_h = reference_resolution(*get_play_res(subs))
    scale_x, scale_y = compute_scale(
        ref_w, ref_h, profile.base_width, profile.base_height
    )
    target = profile.style
    modified: List[str] = []
    for name in profile.target_style_names:
        style = subs.styles.get(name)
        if style is None:
            continue
        style.fontname = target.fontname
        style.fontsize = round(target.fontsize * scale_y)
        style.bold = target.bold
        style.italic = target.italic
        style.primarycolor = parse_ass_color(target.primary_colour)
        style.outlinecolor = parse_ass_color(target.outline_colour)
        style.backcolor = parse_ass_color(target.back_colour)
        style.outline = round(target.outline * scale_y, 2)
        style.shadow = round(target.shadow * scale_y, 2)
        style.alignment = pysubs2.Alignment(target.alignment)
        style.marginl = round(target.margin_l * scale_x)
        style.marginr = round(target.margin_r * scale_x)
        style.marginv = round(target.margin_v * scale_y)
        modified.append(name)
    return modified
