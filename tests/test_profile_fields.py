from __future__ import annotations

import pytest

from ass_style_tool.profile import Profile
from ass_style_tool.profile_fields import (DEFAULT_VALUES, FIELD_KEYS,
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
