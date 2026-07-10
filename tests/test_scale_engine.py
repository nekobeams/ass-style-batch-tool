from __future__ import annotations

import pytest

from ass_style_tool.scale_engine import (ScaleError, ScaleOptions,
                                         fmt_num, parse_format_indices,
                                         scale_text)

V4PLUS_SAMPLE = (
    "[Script Info]\r\n"
    "; 這是註解,不可被更動\r\n"
    "PlayResX: 1280\r\n"
    "PlayResY: 720\r\n"
    "\r\n"
    "[V4+ Styles]\r\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
    "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
    "Alignment, MarginL, MarginR, MarginV, Encoding\r\n"
    "Style: Default,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
    "0,0,0,0,100,100,0,0,1,2,1,2,10,10,10,1\r\n"
    "Style: OP,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
    "0,0,0,0,100,100,0,0,1,2,1,8,10,10,10,1\r\n"
    "\r\n"
    "[Events]\r\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\r\n"
    "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,測試字幕\r\n"
)

# v4(SSA)欄位順序不同:Fontsize 在第 3 欄之外的位置、無 Outline 欄名(TertiaryColour 等)
V4_SAMPLE = (
    "[V4 Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "TertiaryColour, BackColour, Bold, Italic, BorderStyle, Outline, "
    "Shadow, Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding\n"
    "Style: Default,Arial,20,16777215,255,0,0,0,0,1,2,1,2,10,10,10,0,1\n"
)


# ---------- fmt_num ----------

def test_fmt_num_integer():
    assert fmt_num(40.0) == "40"


def test_fmt_num_rounds_to_one_decimal():
    assert fmt_num(40.55) in ("40.5", "40.6")  # 浮點表示法邊界,兩者皆可接受
    assert fmt_num(40.44) == "40.4"


def test_fmt_num_no_trailing_zero():
    assert fmt_num(50.0000001) == "50"


def test_fmt_num_keeps_half():
    assert fmt_num(40.5) == "40.5"


# ---------- parse_format_indices ----------

def test_parse_format_indices_v4plus():
    line = ("Format: Name, Fontname, Fontsize, PrimaryColour, Outline, "
            "Shadow, Alignment")
    idx = parse_format_indices(line)
    assert idx["name"] == 0
    assert idx["fontsize"] == 2
    assert idx["outline"] == 4
    assert idx["shadow"] == 5


def test_parse_format_indices_tolerates_spacing():
    idx = parse_format_indices("Format:Name,Fontsize , Outline")
    assert idx == {"name": 0, "fontsize": 1, "outline": 2}


# ---------- ScaleOptions.validate ----------

def test_options_requires_exactly_one_mode():
    with pytest.raises(ScaleError):
        ScaleOptions().validate()
    with pytest.raises(ScaleError):
        ScaleOptions(factor=1.5, target_size=60).validate()


def test_options_rejects_nonpositive():
    with pytest.raises(ScaleError):
        ScaleOptions(factor=0).validate()
    with pytest.raises(ScaleError):
        ScaleOptions(target_size=-5).validate()


# ---------- scale_text:倍率模式 ----------

def test_scale_factor_mode():
    out, report = scale_text(V4PLUS_SAMPLE, ScaleOptions(factor=1.5))
    assert "Style: Default,Arial,60," in out
    assert "Style: OP,Arial,90," in out
    assert report.factor_used == 1.5
    assert [(c.name, c.old_size, c.new_size) for c in report.style_changes] == [
        ("Default", "40", "60"), ("OP", "60", "90")]


def test_scale_factor_scales_outline_shadow():
    out, _ = scale_text(V4PLUS_SAMPLE, ScaleOptions(factor=2))
    # Default: Outline 2->4, Shadow 1->2(欄位位置依 Format 動態解析)
    assert ",1,4,2,2,10,10,10,1" in out


def test_scale_no_decorations():
    out, _ = scale_text(
        V4PLUS_SAMPLE, ScaleOptions(factor=2, scale_decorations=False))
    assert ",1,2,1,2,10,10,10,1" in out  # Outline/Shadow 不變


def test_scale_v4_ssa_format():
    out, report = scale_text(V4_SAMPLE, ScaleOptions(factor=2))
    assert "Style: Default,Arial,40," in out
    assert report.style_changes[0].new_size == "40"


# ---------- scale_text:目標模式 ----------

def test_target_mode_scales_proportionally():
    out, report = scale_text(
        V4PLUS_SAMPLE, ScaleOptions(target_size=50, base_style="Default"))
    assert "Style: Default,Arial,50," in out
    assert "Style: OP,Arial,75," in out  # 60 * (50/40)
    assert report.factor_used == pytest.approx(1.25)


def test_target_mode_falls_back_to_first_style():
    out, _ = scale_text(
        V4PLUS_SAMPLE, ScaleOptions(target_size=80, base_style="不存在"))
    # 用第一個 style(Default, 40)當基準:factor=2
    assert "Style: Default,Arial,80," in out
    assert "Style: OP,Arial,120," in out


# ---------- 完整性 ----------

def test_comments_and_playres_untouched():
    out, _ = scale_text(V4PLUS_SAMPLE, ScaleOptions(factor=3))
    assert "; 這是註解,不可被更動" in out
    assert "PlayResX: 1280" in out
    assert "PlayResY: 720" in out


def test_factor_one_is_identity():
    out, _ = scale_text(V4PLUS_SAMPLE, ScaleOptions(factor=1.0))
    assert out == V4PLUS_SAMPLE  # 逐字元一致(含 CRLF)


def test_not_ass_raises():
    with pytest.raises(ScaleError):
        scale_text("hello\nworld\n", ScaleOptions(factor=2))
