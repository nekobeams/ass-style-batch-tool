from __future__ import annotations

import json
from pathlib import Path

import pysubs2
import pytest

from ass_style_tool.profile import (Profile, TargetStyle, ass_color_to_rgb,
                                    color_to_ass, load_profile,
                                    parse_ass_color, rgb_to_ass_color,
                                    save_profile)


def make_style(**overrides) -> TargetStyle:
    kwargs = dict(
        fontname="思源黑體 CN", fontsize=72.0, bold=False, italic=False,
        primary_colour="&H00FFFFFF", outline_colour="&H00000000",
        back_colour="&H00000000", outline=3.6, shadow=1.0, alignment=2,
        margin_l=20, margin_r=20, margin_v=24,
    )
    kwargs.update(overrides)
    return TargetStyle(**kwargs)


def make_profile(**overrides) -> Profile:
    kwargs = dict(
        profile_name="測試設定", target_style_names=["Default"],
        base_width=1920, base_height=1080, style=make_style(),
    )
    kwargs.update(overrides)
    return Profile(**kwargs)


def test_parse_ass_color_white():
    c = parse_ass_color("&H00FFFFFF")
    assert (c.r, c.g, c.b, c.a) == (255, 255, 255, 0)


def test_parse_ass_color_component_order():
    # &HAABBGGRR: AA=12, BB=34, GG=56, RR=78
    c = parse_ass_color("&H12345678")
    assert (c.a, c.b, c.g, c.r) == (0x12, 0x34, 0x56, 0x78)


def test_parse_ass_color_trailing_ampersand():
    c = parse_ass_color("&HFFFFFF&")  # SSA v4 寫法
    assert (c.r, c.g, c.b) == (255, 255, 255)


def test_parse_ass_color_invalid_raises():
    with pytest.raises(ValueError):
        parse_ass_color("not a color")


def test_color_roundtrip():
    original = "&H12345678"
    assert color_to_ass(parse_ass_color(original)) == original


# ---------- ass_color_to_rgb / rgb_to_ass_color(從 style_editor.py 的
# _ass_to_qcolor/_qcolor_to_ass 抽出的演算法本體,不依賴 Qt) ----------

def test_ass_color_to_rgb_drops_alpha_and_keeps_channel_order():
    """三個色版故意用不同數值,避免通道順序寫反(例如 R/B 對調)時測試
    還碰巧通過。"""
    assert ass_color_to_rgb("&H80FF8040") == (0x40, 0x80, 0xFF)


def test_rgb_to_ass_color_roundtrips_color_and_alpha():
    original = "&H80FF8040"
    rgb = ass_color_to_rgb(original)
    # ass_color_to_rgb 刻意丟棄 alpha,所以要餵回原始字串取回 alpha——
    # 這正是 rgb_to_ass_color 第二個參數存在的理由。
    assert rgb_to_ass_color(rgb, original) == original


def test_rgb_to_ass_color_falls_back_to_zero_alpha_on_invalid_source():
    """換色時如果欄位裡原本的文字打到一半是無效色碼,parse_ass_color
    會丟 ValueError——不該讓整個換色動作跟著失敗,只是 alpha 退回 0。"""
    assert rgb_to_ass_color((0x40, 0x80, 0xFF), "not-a-color") == "&H00FF8040"


def test_profile_save_load_roundtrip(tmp_path):
    profile = make_profile()
    path = tmp_path / "p.json"
    save_profile(profile, path)
    assert load_profile(path) == profile


def test_saved_json_matches_spec_shape(tmp_path):
    path = tmp_path / "p.json"
    save_profile(make_profile(), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["base_resolution"] == {"width": 1920, "height": 1080}
    assert data["target_style_names"] == ["Default"]
    assert data["style"]["fontname"] == "思源黑體 CN"


def test_load_profile_rejects_bad_alignment(tmp_path):
    path = tmp_path / "p.json"
    save_profile(make_profile(style=make_style(alignment=10)), path)
    with pytest.raises(ValueError):
        load_profile(path)


def test_load_profile_rejects_bad_color(tmp_path):
    path = tmp_path / "p.json"
    save_profile(make_profile(style=make_style(primary_colour="oops")), path)
    with pytest.raises(ValueError):
        load_profile(path)
