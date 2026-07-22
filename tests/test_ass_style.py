from __future__ import annotations

from pathlib import Path

import pysubs2
import pytest

from ass_style_tool.ass_style import (apply_profile, compute_applied_values,
                                      AppliedValues, detect_and_decode,
                                      get_play_res, get_scaled_border_shadow,
                                      load_subs, save_subs)
from tests.test_profile import make_profile, make_style

SAMPLE_ASS = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,10,1
Style: OP,Comic Sans MS,60,&H0000FFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,8,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,測試字幕一
Dialogue: 0,0:00:04.00,0:00:06.00,OP,,0,0,0,,片頭曲
"""


def test_load_utf8_bom(tmp_path):
    path = tmp_path / "a.ass"
    path.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    subs = load_subs(path)
    assert "測試字幕一" in subs.events[0].text


def test_load_utf8_no_bom(tmp_path):
    path = tmp_path / "a.ass"
    path.write_bytes(SAMPLE_ASS.encode("utf-8"))
    subs = load_subs(path)
    assert subs.styles["Default"].fontname == "Arial"


def test_load_big5(tmp_path):
    long_line = (
        "這是一段比較長的繁體中文字幕內容,用來讓編碼偵測擁有足夠的樣本資料,"
        "裡面包含常見的標點符號、以及像動畫、字幕、樣式這些常用詞彙。"
    )
    text = SAMPLE_ASS.replace("測試字幕一", long_line)
    path = tmp_path / "big5.ass"
    path.write_bytes(text.encode("big5"))
    subs = load_subs(path)
    assert "繁體中文字幕內容" in subs.events[0].text


def test_undecodable_raises(tmp_path):
    path = tmp_path / "bad.ass"
    path.write_bytes(bytes(range(256)) * 4)
    with pytest.raises(ValueError):
        detect_and_decode(path)


def test_save_writes_utf8_bom(tmp_path):
    subs = pysubs2.SSAFile.from_string(SAMPLE_ASS)
    out = tmp_path / "out.ass"
    save_subs(subs, out)
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")
    # 能重新讀回
    assert "Default" in load_subs(out).styles


def test_get_play_res():
    subs = pysubs2.SSAFile.from_string(SAMPLE_ASS)
    assert get_play_res(subs) == (1280, 720)


def test_get_play_res_missing():
    stripped = SAMPLE_ASS.replace("PlayResX: 1280\nPlayResY: 720\n", "")
    subs = pysubs2.SSAFile.from_string(stripped)
    assert get_play_res(subs) == (0, 0)


def test_get_scaled_border_shadow_unset():
    subs = pysubs2.SSAFile.from_string(SAMPLE_ASS)
    assert get_scaled_border_shadow(subs) == "unset"


def test_get_scaled_border_shadow_present():
    text = SAMPLE_ASS.replace(
        "ScriptType: v4.00+", "ScriptType: v4.00+\nScaledBorderAndShadow: yes"
    )
    subs = pysubs2.SSAFile.from_string(text)
    assert get_scaled_border_shadow(subs) == "yes"


def test_apply_profile_scales_to_720p():
    subs = pysubs2.SSAFile.from_string(SAMPLE_ASS)
    modified = apply_profile(subs, make_profile())
    assert modified == ["Default"]
    st = subs.styles["Default"]
    # scale_y = 720/1080, scale_x = 1280/1920
    assert st.fontname == "思源黑體 CN"
    assert st.fontsize == 48          # round(72 * 720/1080)
    assert st.outline == 2.4          # round(3.6 * 720/1080, 2)
    assert st.shadow == 0.67          # round(1.0 * 720/1080, 2)
    assert st.marginv == 16           # round(24 * 720/1080)
    assert st.marginl == 13           # round(20 * 1280/1920)
    assert st.marginr == 13
    assert int(st.alignment) == 2
    assert (st.primarycolor.r, st.primarycolor.g, st.primarycolor.b) == (255, 255, 255)


def test_apply_profile_leaves_other_styles_untouched():
    subs = pysubs2.SSAFile.from_string(SAMPLE_ASS)
    apply_profile(subs, make_profile())
    op = subs.styles["OP"]
    assert op.fontname == "Comic Sans MS"
    assert op.fontsize == 60


def test_apply_profile_missing_style_returns_empty():
    subs = pysubs2.SSAFile.from_string(SAMPLE_ASS)
    profile = make_profile(target_style_names=["不存在的樣式"])
    assert apply_profile(subs, profile) == []
    assert "不存在的樣式" not in subs.styles  # 不自動新增


def test_apply_profile_no_playres_uses_spec_default():
    stripped = SAMPLE_ASS.replace("PlayResX: 1280\nPlayResY: 720\n", "")
    subs = pysubs2.SSAFile.from_string(stripped)
    apply_profile(subs, make_profile())
    # scale_y = 288/1080
    assert subs.styles["Default"].fontsize == 19  # round(72 * 288/1080) = round(19.2)


def test_apply_profile_does_not_touch_headers():
    subs = pysubs2.SSAFile.from_string(SAMPLE_ASS)
    apply_profile(subs, make_profile())
    assert subs.info["PlayResX"] == "1280"
    assert subs.info["PlayResY"] == "720"


def load_subs_from_sample():
    return pysubs2.SSAFile.from_string(SAMPLE_ASS)


def test_compute_applied_values_half_scale():
    # 基準 1920x1080,畫布 640x360 → scale 0.3333
    profile = make_profile()  # fontsize 72, outline 3.6, shadow 1.0, margin 20/20/24
    av = compute_applied_values(profile, 640, 360)
    assert av.ref_w == 640 and av.ref_h == 360
    assert round(av.scale_y, 3) == 0.333
    assert av.fontsize == 24          # round(72 * 1/3)
    assert av.outline == 1.2          # round(3.6 * 1/3, 2)
    assert av.shadow == 0.33          # round(1.0 * 1/3, 2)
    assert av.margin_l == 7           # round(20 * 1/3)
    assert av.margin_r == 7
    assert av.margin_v == 8           # round(24 * 1/3)


def test_compute_applied_values_identity_when_same_res():
    profile = make_profile()
    av = compute_applied_values(profile, 1920, 1080)
    assert av.scale_x == 1.0 and av.scale_y == 1.0
    assert av.fontsize == 72
    assert av.outline == 3.6
    assert av.margin_v == 24


def test_compute_applied_values_missing_playres_uses_reference():
    # 兩者皆 0 → reference_resolution 回 384x288(規範預設)
    profile = make_profile()
    av = compute_applied_values(profile, 0, 0)
    assert (av.ref_w, av.ref_h) == (384, 288)


def test_apply_profile_matches_compute_applied_values():
    # 寫檔結果必須與 compute_applied_values 完全一致
    path_subs = load_subs_from_sample()
    profile = make_profile()
    av = compute_applied_values(profile, *get_play_res(path_subs))
    apply_profile(path_subs, profile)
    style = path_subs.styles["Default"]
    assert style.fontsize == av.fontsize
    assert style.outline == av.outline
    assert style.shadow == av.shadow
    assert style.marginl == av.margin_l
    assert style.marginr == av.margin_r
    assert style.marginv == av.margin_v
