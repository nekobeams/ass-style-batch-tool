"""ASS 檔案讀寫(含編碼偵測)與目標樣式套用。"""
from __future__ import annotations

from dataclasses import dataclass
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


@dataclass
class AppliedValues:
    """profile 套用到某 PlayRes 後,各數值欄位的換算結果。"""
    scale_x: float
    scale_y: float
    ref_w: int
    ref_h: int
    fontsize: int
    outline: float
    shadow: float
    margin_l: int
    margin_r: int
    margin_v: int


def compute_applied_values(
    profile: Profile, play_res_x: int, play_res_y: int
) -> AppliedValues:
    """依 PlayRes 規則換算 profile 目標樣式的各數值欄位。

    縮放與四捨五入規則必須與 apply_profile 寫檔時逐欄位一致,兩者共用本函式。
    """
    ref_w, ref_h = reference_resolution(play_res_x, play_res_y)
    scale_x, scale_y = compute_scale(
        ref_w, ref_h, profile.base_width, profile.base_height
    )
    t = profile.style
    return AppliedValues(
        scale_x=scale_x,
        scale_y=scale_y,
        ref_w=ref_w,
        ref_h=ref_h,
        fontsize=round(t.fontsize * scale_y),
        outline=round(t.outline * scale_y, 2),
        shadow=round(t.shadow * scale_y, 2),
        margin_l=round(t.margin_l * scale_x),
        margin_r=round(t.margin_r * scale_x),
        margin_v=round(t.margin_v * scale_y),
    )


def apply_profile(
    subs: pysubs2.SSAFile,
    profile: Profile,
    *,
    apply_to_all_styles: bool = False,
) -> List[str]:
    """把 profile 的目標樣式套用到指定名稱的 Style(依 PlayRes 規則縮放)。

    只修改 [V4+ Styles] 中對應的行;絕不改寫 Script Info 標頭、
    不新增 Style。回傳實際修改到的 Style 名稱。

    apply_to_all_styles=True 時,忽略 profile.target_style_names,改為套用到
    subs 目前實際擁有的所有 Style(供轉檔而來、無原生樣式名稱可比對的來源,
    例如 SRT 轉換後只會有單一 "Default" 樣式)。預設 False 維持既有
    依名稱精確比對的行為。
    """
    av = compute_applied_values(profile, *get_play_res(subs))
    target = profile.style
    modified: List[str] = []
    names = (
        list(subs.styles.keys()) if apply_to_all_styles
        else profile.target_style_names
    )
    for name in names:
        style = subs.styles.get(name)
        if style is None:
            continue
        style.fontname = target.fontname
        style.fontsize = av.fontsize
        style.bold = target.bold
        style.italic = target.italic
        style.primarycolor = parse_ass_color(target.primary_colour)
        style.outlinecolor = parse_ass_color(target.outline_colour)
        style.backcolor = parse_ass_color(target.back_colour)
        style.outline = av.outline
        style.shadow = av.shadow
        style.alignment = pysubs2.Alignment(target.alignment)
        style.marginl = av.margin_l
        style.marginr = av.margin_r
        style.marginv = av.margin_v
        modified.append(name)
    return modified
