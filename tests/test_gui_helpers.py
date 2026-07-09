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
