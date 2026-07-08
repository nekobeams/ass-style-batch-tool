"""目標樣式設定檔(Profile)的資料結構、ASS 色碼轉換與 JSON 讀寫。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pysubs2


@dataclass
class TargetStyle:
    fontname: str
    fontsize: float
    bold: bool
    italic: bool
    primary_colour: str
    outline_colour: str
    back_colour: str
    outline: float
    shadow: float
    alignment: int
    margin_l: int
    margin_r: int
    margin_v: int


@dataclass
class Profile:
    profile_name: str
    target_style_names: list[str]
    base_width: int
    base_height: int
    style: TargetStyle


def parse_ass_color(text: str) -> pysubs2.Color:
    """解析 '&HAABBGGRR' 格式色碼;非法字串丟 ValueError。"""
    cleaned = text.strip().upper()
    if cleaned.startswith("&H"):
        cleaned = cleaned[2:]
    cleaned = cleaned.rstrip("&")
    if not cleaned:
        raise ValueError(f"空白色碼: {text!r}")
    value = int(cleaned, 16)  # 非十六進位字元會丟 ValueError
    return pysubs2.Color(
        r=value & 0xFF,
        g=(value >> 8) & 0xFF,
        b=(value >> 16) & 0xFF,
        a=(value >> 24) & 0xFF,
    )


def color_to_ass(color: pysubs2.Color) -> str:
    return f"&H{color.a:02X}{color.b:02X}{color.g:02X}{color.r:02X}"


def _validate_style(style: TargetStyle) -> None:
    parse_ass_color(style.primary_colour)
    parse_ass_color(style.outline_colour)
    parse_ass_color(style.back_colour)
    if not 1 <= style.alignment <= 9:
        raise ValueError(f"alignment 必須是 1-9,收到 {style.alignment}")


def load_profile(path: Path) -> Profile:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    style = TargetStyle(**data["style"])
    _validate_style(style)
    return Profile(
        profile_name=data["profile_name"],
        target_style_names=list(data["target_style_names"]),
        base_width=int(data["base_resolution"]["width"]),
        base_height=int(data["base_resolution"]["height"]),
        style=style,
    )


def save_profile(profile: Profile, path: Path) -> None:
    data = {
        "profile_name": profile.profile_name,
        "target_style_names": profile.target_style_names,
        "base_resolution": {
            "width": profile.base_width,
            "height": profile.base_height,
        },
        "style": asdict(profile.style),
    }
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
