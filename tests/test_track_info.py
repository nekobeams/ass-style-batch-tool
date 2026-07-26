from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_io import MediaTrack
from ass_style_tool.track_info import build_track_info_rows


def _sub(tid, lang="chi", name="繁中", default=False, forced=False):
    return MediaTrack(tid, "subtitles", "S_TEXT/ASS", lang, name,
                      default, forced)


def _audio(tid):
    return MediaTrack(tid, "audio", "A_FLAC", "jpn", "", True, False)


def _files():
    return {
        Path("b.mkv"): [_audio(1), _sub(2, name="B繁中", default=True)],
        Path("a.mkv"): [_audio(1), _sub(2, name="A繁中")],
        Path("c.mkv"): [_audio(1)],              # 沒有軌 2
        Path("d.mkv"): [_audio(1), _audio(2)],   # 軌 2 是音訊,類型不符
    }


def test_rows_sorted_by_file_name():
    rows = build_track_info_rows(2, "subtitles", _files())
    assert [r.video_name for r in rows] == ["a.mkv", "b.mkv", "c.mkv", "d.mkv"]


def test_row_for_matching_track_carries_that_files_values():
    rows = {r.video_name: r for r in build_track_info_rows(2, "subtitles",
                                                           _files())}
    b = rows["b.mkv"]
    assert b.found is True and b.type_matches is True
    assert b.track_name == "B繁中"
    assert b.language == "chi"
    assert b.default is True          # 取的是該檔自己的值
    assert b.forced is False
    assert rows["a.mkv"].track_name == "A繁中"
    assert rows["a.mkv"].default is False


def test_row_for_missing_track():
    rows = {r.video_name: r for r in build_track_info_rows(2, "subtitles",
                                                           _files())}
    c = rows["c.mkv"]
    assert c.found is False
    assert c.type_matches is False
    assert c.default is None and c.forced is None
    assert c.track_name == "" and c.language == ""


def test_row_for_type_mismatch_reports_actual_type():
    rows = {r.video_name: r for r in build_track_info_rows(2, "subtitles",
                                                           _files())}
    d = rows["d.mkv"]
    assert d.found is True            # ID 存在
    assert d.type_matches is False    # 但不是字幕
    assert d.track_type == "audio"    # 告訴使用者它實際是什麼
    assert d.default is None and d.forced is None


def test_empty_map_gives_no_rows():
    assert build_track_info_rows(2, "subtitles", {}) == []
