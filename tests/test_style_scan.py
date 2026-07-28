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


def test_summarize_empty_list_returns_empty_summary():
    # 沒有任何檔案時,summarize([]) 不該因 signatures.most_common(1)[0]
    # 這個索引動作而丟出 IndexError——這是 `if not readable: return summary`
    # 這道防線在保護的情境。
    summary = summarize([])
    assert summary.names == []
    assert summary.inconsistent == []
    assert summary.unreadable == []


def test_summarize_all_unreadable_returns_empty_names_and_inconsistent(tmp_path):
    # 整批都讀取失敗時,readable 會是空 list,同樣要靠
    # `if not readable: return summary` 防線擋掉 most_common(1)[0] 的 IndexError。
    bad1 = FileStyles(tmp_path / "bad1.ass", error="讀取失敗")
    bad2 = FileStyles(tmp_path / "bad2.ass", error="讀取失敗")
    summary = summarize([bad1, bad2])
    assert summary.names == []
    assert summary.inconsistent == []
    assert summary.unreadable == [tmp_path / "bad1.ass", tmp_path / "bad2.ass"]


def test_summarize_tie_break_is_deterministic_and_order_independent(tmp_path):
    # 打平情境:兩檔 {Default}、兩檔 {CHS},沒有任何一組是嚴格多數。
    # 基準規則是「打平時取排序後字典序最小的樣式名組合」,
    # sorted(["CHS"]) < sorted(["Default"]),所以 CHS 那組當基準,
    # Default 那組兩檔都要被列進 inconsistent——即使是真正對半分,
    # 使用者仍然要收到「這批不一致」的警訊。
    d1 = FileStyles(tmp_path / "d1.ass", {"Default": 48.0})
    d2 = FileStyles(tmp_path / "d2.ass", {"Default": 48.0})
    c1 = FileStyles(tmp_path / "c1.ass", {"CHS": 48.0})
    c2 = FileStyles(tmp_path / "c2.ass", {"CHS": 48.0})

    expected = [tmp_path / "d1.ass", tmp_path / "d2.ass"]

    summary = summarize([d1, d2, c1, c2])
    assert summary.inconsistent == expected

    # 打亂輸入順序(尤其讓 CHS 先出現)不該改變挑出的基準組合——
    # 若 tie-break 被移除或反過來,這裡會因為 Counter 先出現順序
    # 改變而挑到不同的基準,導致 inconsistent 的「集合」跟著變。
    shuffled_summary = summarize([c2, d1, c1, d2])
    assert set(shuffled_summary.inconsistent) == set(expected)

    reversed_summary = summarize([c2, c1, d2, d1])
    assert set(reversed_summary.inconsistent) == set(expected)
