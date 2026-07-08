"""Profile 與 GUI 欄位字典之間的轉換與驗證(純邏輯,不依賴 Qt)。"""
from __future__ import annotations

from typing import Dict, Tuple

from .profile import Profile, TargetStyle, parse_ass_color

FIELD_KEYS: Tuple[str, ...] = (
    "profile_name", "target_style_names",
    "fontname", "fontsize", "bold", "italic",
    "primary_colour", "outline_colour", "back_colour",
    "outline", "shadow", "alignment",
    "margin_l", "margin_r", "margin_v",
    "base_width", "base_height",
)

DEFAULT_VALUES: Dict[str, object] = {
    "profile_name": "我的字幕標準",
    "target_style_names": "Default",
    "fontname": "思源黑體 CN",
    "fontsize": "72",
    "bold": False,
    "italic": False,
    "primary_colour": "&H00FFFFFF",
    "outline_colour": "&H00000000",
    "back_colour": "&H00000000",
    "outline": "3.6",
    "shadow": "1.0",
    "alignment": "2",
    "margin_l": "20",
    "margin_r": "20",
    "margin_v": "24",
    "base_width": "1920",
    "base_height": "1080",
}


def _num(values: dict, key: str, cast):
    try:
        return cast(values[key])
    except (TypeError, ValueError):
        raise ValueError(f"欄位 {key} 必須是數字,收到 {values.get(key)!r}")


def profile_from_values(values: dict) -> Profile:
    fontname = str(values["fontname"]).strip()
    if not fontname:
        raise ValueError("字型名稱不可為空")
    names = [n.strip() for n in str(values["target_style_names"]).split(",")
             if n.strip()]
    if not names:
        raise ValueError("目標 Style 名稱不可為空")
    alignment = _num(values, "alignment", int)
    if not 1 <= alignment <= 9:
        raise ValueError(f"alignment 必須是 1-9,收到 {alignment}")
    base_width = _num(values, "base_width", int)
    base_height = _num(values, "base_height", int)
    if base_width <= 0 or base_height <= 0:
        raise ValueError("基準解析度必須大於 0")
    for key in ("primary_colour", "outline_colour", "back_colour"):
        parse_ass_color(str(values[key]))  # 非法丟 ValueError
    style = TargetStyle(
        fontname=fontname,
        fontsize=_num(values, "fontsize", float),
        bold=bool(values["bold"]),
        italic=bool(values["italic"]),
        primary_colour=str(values["primary_colour"]).strip(),
        outline_colour=str(values["outline_colour"]).strip(),
        back_colour=str(values["back_colour"]).strip(),
        outline=_num(values, "outline", float),
        shadow=_num(values, "shadow", float),
        alignment=alignment,
        margin_l=_num(values, "margin_l", int),
        margin_r=_num(values, "margin_r", int),
        margin_v=_num(values, "margin_v", int),
    )
    return Profile(
        profile_name=str(values["profile_name"]).strip() or "未命名",
        target_style_names=names,
        base_width=base_width,
        base_height=base_height,
        style=style,
    )


def values_from_profile(profile: Profile) -> Dict[str, object]:
    s = profile.style
    return {
        "profile_name": profile.profile_name,
        "target_style_names": ", ".join(profile.target_style_names),
        "fontname": s.fontname,
        "fontsize": str(s.fontsize),
        "bold": s.bold,
        "italic": s.italic,
        "primary_colour": s.primary_colour,
        "outline_colour": s.outline_colour,
        "back_colour": s.back_colour,
        "outline": str(s.outline),
        "shadow": str(s.shadow),
        "alignment": str(s.alignment),
        "margin_l": str(s.margin_l),
        "margin_r": str(s.margin_r),
        "margin_v": str(s.margin_v),
        "base_width": str(profile.base_width),
        "base_height": str(profile.base_height),
    }
