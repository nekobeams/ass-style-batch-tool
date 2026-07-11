from __future__ import annotations

from pathlib import Path

from ass_style_tool.batch_runner import ScanResult
from ass_style_tool.episode_match import MatchResult
from ass_style_tool.qt.gui_helpers import (PreviewRow, font_is_missing,
                                           preview_rows)


def test_preview_rows_matched():
    scan = ScanResult(matches=[
        MatchResult(sub_path=Path("a [01].ass"), episode=1,
                    video_path=Path("v01.mkv"),
                    video_resolution=(1920, 1080), status="matched"),
    ], warnings=[])
    rows = preview_rows(scan)
    assert len(rows) == 1
    r = rows[0]
    assert r.episode == "01"
    assert r.sub_name == "a [01].ass"
    assert r.video_name == "v01.mkv"
    assert r.status_label == "已配對"


def test_preview_rows_no_video_and_no_episode():
    scan = ScanResult(matches=[
        MatchResult(sub_path=Path("x [03].ass"), episode=3,
                    video_path=None, status="no_video"),
        MatchResult(sub_path=Path("opening.ass"), episode=None,
                    status="no_episode"),
    ], warnings=[])
    rows = preview_rows(scan)
    assert rows[0].video_name == "-"
    assert rows[0].episode == "03"
    assert rows[0].status_label == "無對應影片"
    assert rows[1].episode == "?"
    assert rows[1].status_label == "無法判斷集數"


def test_preview_rows_ambiguous():
    scan = ScanResult(matches=[
        MatchResult(sub_path=Path("a [01].ass"), episode=1, status="ambiguous"),
    ], warnings=[])
    assert preview_rows(scan)[0].status_label == "配對模糊"


def test_font_missing_true():
    assert font_is_missing("思源黑體 CN", ["Arial", "Microsoft JhengHei"]) is True


def test_font_missing_false_case_insensitive():
    assert font_is_missing("arial", ["Arial", "MS Gothic"]) is False


def test_font_missing_empty_name_is_not_missing():
    assert font_is_missing("  ", ["Arial"]) is False


# ---------- 字幕行清單 ----------
import pysubs2

from ass_style_tool.qt.gui_helpers import (DialogueLine, dialogue_lines,
                                           format_timestamp)


def test_format_timestamp():
    assert format_timestamp(0) == "0:00:00.00"
    assert format_timestamp(1000) == "0:00:01.00"
    assert format_timestamp(61230) == "0:01:01.23"
    assert format_timestamp(3600000 + 125450) == "1:02:05.45"


def _subs_from(text: str) -> pysubs2.SSAFile:
    return pysubs2.SSAFile.from_string(text)


LINES_SAMPLE = (
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, Outline, Shadow\n"
    "Style: Default,Arial,40,2,1\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\fs40}大字\\N第二行\n"
    "Comment: 0,0:00:02.00,0:00:04.00,Default,,0,0,0,,這是註解事件\n"
    "Dialogue: 0,0:00:05.50,0:00:07.00,Default,,0,0,0,,一般對白\n"
)


def test_dialogue_lines_skips_comments_and_strips_tags():
    lines = dialogue_lines(_subs_from(LINES_SAMPLE))
    assert len(lines) == 2
    assert lines[0].start_ms == 1000
    assert lines[0].text == "大字 第二行"   # 標籤去除、\N 摺成空格
    assert lines[1].start_ms == 5500


def test_dialogue_lines_empty():
    empty = LINES_SAMPLE.split("[Events]")[0] + "[Events]\n" \
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    assert dialogue_lines(_subs_from(empty)) == []
