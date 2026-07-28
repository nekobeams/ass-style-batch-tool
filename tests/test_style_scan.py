from __future__ import annotations

from pathlib import Path

from ass_style_tool.style_scan import FileStyles, scan_styles, summarize

_HEADER = """[Script Info]
PlayResX: {w}
PlayResY: {h}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
"""

_STYLE = ("Style: {name},Arial,{size},&H00FFFFFF,&H000000FF,&H00000000,"
          "&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n")

_EVENTS = """
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,{style},,0,0,0,,測試字幕
"""


def write_ass(path: Path, styles, w=1920, h=1080, encoding="utf-8-sig") -> Path:
    """寫出一個真的能被 pysubs2 解析的 ASS 檔。styles 是 [(名稱, 字級)]。"""
    text = _HEADER.format(w=w, h=h)
    for name, size in styles:
        text += _STYLE.format(name=name, size=size)
    text += _EVENTS.format(style=styles[0][0])
    path.write_text(text, encoding=encoding)
    return path


def test_scan_styles_reads_names_and_sizes(tmp_path):
    p = write_ass(tmp_path / "a.ass", [("Default", 48), ("CHT", 52)])
    result = scan_styles(p)
    assert result.error is None
    assert result.styles == {"Default": 48.0, "CHT": 52.0}


def test_scan_styles_reads_play_res(tmp_path):
    p = write_ass(tmp_path / "a.ass", [("Default", 48)], w=1280, h=720)
    assert scan_styles(p).play_res == (1280, 720)


def test_scan_styles_handles_big5(tmp_path):
    p = write_ass(tmp_path / "big5.ass", [("Default", 40)], encoding="big5")
    result = scan_styles(p)
    assert result.error is None
    assert result.styles == {"Default": 40.0}


def test_scan_styles_reports_broken_file_without_raising(tmp_path):
    p = tmp_path / "broken.ass"
    p.write_bytes(b"\xff\xfe\x00\x00 not a subtitle at all \xff")
    result = scan_styles(p)
    assert result.error is not None
    assert result.styles == {}


def test_summarize_dedupes_and_sorts(tmp_path):
    a = FileStyles(tmp_path / "a.ass", {"Default": 48.0, "CHT": 52.0})
    b = FileStyles(tmp_path / "b.ass", {"Default": 48.0})
    summary = summarize([a, b])
    assert summary.names == ["CHT", "Default"]


def test_summarize_flags_the_odd_file_out(tmp_path):
    same1 = FileStyles(tmp_path / "1.ass", {"Default": 48.0})
    same2 = FileStyles(tmp_path / "2.ass", {"Default": 48.0})
    odd = FileStyles(tmp_path / "3.ass", {"CHS": 48.0})
    summary = summarize([same1, same2, odd])
    assert summary.inconsistent == [tmp_path / "3.ass"]


def test_summarize_collects_unreadable_separately(tmp_path):
    ok = FileStyles(tmp_path / "ok.ass", {"Default": 48.0})
    bad = FileStyles(tmp_path / "bad.ass", error="讀取失敗")
    summary = summarize([ok, bad])
    assert summary.unreadable == [tmp_path / "bad.ass"]
    assert summary.names == ["Default"]
