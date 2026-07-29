from __future__ import annotations

import pytest

from ass_style_tool.profile import Profile
from ass_style_tool.profile_fields import (DEFAULT_VALUES, FIELD_KEYS,
                                           parse_target_style_names,
                                           profile_from_values,
                                           values_from_profile)


def test_default_values_have_all_keys():
    assert set(DEFAULT_VALUES) == set(FIELD_KEYS)


def test_defaults_build_valid_profile():
    p = profile_from_values(DEFAULT_VALUES)
    assert isinstance(p, Profile)
    assert p.base_width == 1920
    assert p.base_height == 1080


def test_profile_from_values_parses_types():
    values = dict(DEFAULT_VALUES)
    values.update({
        "profile_name": "我的",
        "target_style_names": "Default, OP",
        "fontname": "思源黑體 CN",
        "fontsize": "72",
        "bold": True,
        "italic": False,
        "outline": "3.6",
        "shadow": "1.0",
        "alignment": "2",
        "margin_l": "20", "margin_r": "20", "margin_v": "24",
        "base_width": "1920", "base_height": "1080",
        "primary_colour": "&H00FFFFFF",
        "outline_colour": "&H00000000",
        "back_colour": "&H00000000",
    })
    p = profile_from_values(values)
    assert p.target_style_names == ["Default", "OP"]   # 逗號分隔、去空白
    assert p.style.fontsize == 72.0
    assert p.style.bold is True
    assert p.style.alignment == 2
    assert p.style.margin_v == 24


def test_empty_fontname_raises():
    values = dict(DEFAULT_VALUES)
    values["fontname"] = "  "
    with pytest.raises(ValueError):
        profile_from_values(values)


def test_empty_target_styles_raises():
    values = dict(DEFAULT_VALUES)
    values["target_style_names"] = " , "
    with pytest.raises(ValueError):
        profile_from_values(values)


def test_bad_number_raises():
    values = dict(DEFAULT_VALUES)
    values["fontsize"] = "big"
    with pytest.raises(ValueError):
        profile_from_values(values)


def test_bad_color_raises():
    values = dict(DEFAULT_VALUES)
    values["primary_colour"] = "nope"
    with pytest.raises(ValueError):
        profile_from_values(values)


def test_nonpositive_base_resolution_raises():
    values = dict(DEFAULT_VALUES)
    values["base_width"] = "0"
    with pytest.raises(ValueError):
        profile_from_values(values)


def test_bad_alignment_raises():
    values = dict(DEFAULT_VALUES)
    values["alignment"] = "10"
    with pytest.raises(ValueError):
        profile_from_values(values)


def test_roundtrip_values_profile_values():
    p = profile_from_values(DEFAULT_VALUES)
    back = values_from_profile(p)
    p2 = profile_from_values(back)
    assert p == p2


# ---------- parse_target_style_names(最終審查 Batch A3 Finding 1) ----------
# profile_from_values() 與 style_editor.py 的載入防呆共用同一個判斷式,
# 不能各自維護一份看起來像、實際上不同的真值檢查。這裡直接測這個共用
# helper 本身的行為。

def test_parse_target_style_names_splits_strips_and_filters_empty():
    assert parse_target_style_names("CHT, CHS") == ["CHT", "CHS"]
    assert parse_target_style_names("  Sign  ,, OP ") == ["Sign", "OP"]


def test_parse_target_style_names_all_blank_is_empty():
    """`","`、`" "`、空字串這幾種在裸的 falsy-list 檢查底下可能仍是
    「非空」的原始值,但切開、去空白、過濾之後應該一律得到空清單。"""
    assert parse_target_style_names(",") == []
    assert parse_target_style_names(" ") == []
    assert parse_target_style_names("") == []


def test_profile_from_values_uses_parse_target_style_names():
    """profile_from_values() 對 target_style_names 的驗證要跟
    parse_target_style_names() 是同一個判斷來源,不是另外維護一份。"""
    values = dict(DEFAULT_VALUES)
    values["target_style_names"] = ",,   ,"
    with pytest.raises(ValueError, match="目標 Style 名稱不可為空"):
        profile_from_values(values)
