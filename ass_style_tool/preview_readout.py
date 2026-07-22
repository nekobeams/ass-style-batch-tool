"""套用樣式「換算對照」讀出的純資料組裝(無 Qt、無檔案 I/O、易測)。

把 profile + 檔案 PlayRes + 原字幕值 + 影片解析度,組成一份可直接呈現的
ReadoutData。實際數字換算一律委派給 ass_style.compute_applied_values,
確保與批次寫檔完全一致。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .ass_style import compute_applied_values
from .profile import Profile
from .resolution import aspect_mismatch


@dataclass
class OriginalValues:
    """來源字幕檔中,將被修改的目標樣式的現有數值。"""
    fontsize: float
    outline: float
    shadow: float
    margin_l: int
    margin_r: int
    margin_v: int


@dataclass
class ReadoutRow:
    label: str
    original: str
    applied: str


@dataclass
class ReadoutData:
    mechanism: str
    context_subtitle: str
    context_video: str
    aspect_warning: bool
    rows: List[ReadoutRow]
    missing_message: str
    note: str


def _fmt(value) -> str:
    """數字顯示:整數不帶小數點;小數去掉多餘尾零(1.20 → 1.2)。"""
    number = float(value)
    if number == int(number):
        return str(int(number))
    return f"{round(number, 2):g}"


def build_readout(
    profile: Profile,
    play_res_x: int,
    play_res_y: int,
    original: Optional[OriginalValues],
    subtitle_name: str,
    video_name: Optional[str],
    video_res: Optional[Tuple[int, int]],
) -> ReadoutData:
    av = compute_applied_values(profile, play_res_x, play_res_y)
    canvas_w, canvas_h = av.ref_w, av.ref_h

    mechanism = (
        f"工具把 profile(基準 {profile.base_width}×{profile.base_height})"
        f"依這個檔案的畫布 {canvas_w}×{canvas_h} "
        f"等比縮放 {av.scale_y:.3f}× 後套用"
    )
    context_subtitle = (
        f"此檔案:{subtitle_name} · 字幕畫布 {canvas_w}×{canvas_h}"
    )

    aspect_warning = False
    if video_res is not None:
        vw, vh = video_res
        aspect_warning = aspect_mismatch((canvas_w, canvas_h), (vw, vh))
        status = ("⚠ 比例不符,字幕可能被拉伸變形" if aspect_warning
                  else "比例相符 ✓")
        context_video = f"影片:{video_name} · {vw}×{vh} · {status}"
    else:
        context_video = "影片:載入影片可看到實際疊在畫面上的效果"

    note = "字型、顏色、對齊 直接採用 profile 設定(不縮放)"

    if original is None:
        names = "、".join(profile.target_style_names)
        missing_message = (
            f"此檔案沒有目標樣式「{names}」→ 套用時將略過,不會改到這個檔案"
        )
        return ReadoutData(
            mechanism=mechanism,
            context_subtitle=context_subtitle,
            context_video=context_video,
            aspect_warning=aspect_warning,
            rows=[],
            missing_message=missing_message,
            note=note,
        )

    rows = [
        ReadoutRow("字級", _fmt(original.fontsize), _fmt(av.fontsize)),
        ReadoutRow("外框", _fmt(original.outline), _fmt(av.outline)),
        ReadoutRow("陰影", _fmt(original.shadow), _fmt(av.shadow)),
        ReadoutRow("邊界 L", _fmt(original.margin_l), _fmt(av.margin_l)),
        ReadoutRow("邊界 R", _fmt(original.margin_r), _fmt(av.margin_r)),
        ReadoutRow("邊界 V", _fmt(original.margin_v), _fmt(av.margin_v)),
    ]
    return ReadoutData(
        mechanism=mechanism,
        context_subtitle=context_subtitle,
        context_video=context_video,
        aspect_warning=aspect_warning,
        rows=rows,
        missing_message="",
        note=note,
    )
