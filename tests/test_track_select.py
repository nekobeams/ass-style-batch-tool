from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_io import SubtitleTrack
from ass_style_tool.track_select import (all_keys, build_select_info_rows,
                                         resolve_tracks,
                                         uncovered_track_count)


def _track(tid, lang="chi", name="繁中"):
    return SubtitleTrack(tid, "S_TEXT/ASS", lang, name, False, False)


FILES = {
    Path("e1.mkv"): [_track(2, "chi", "繁中"), _track(3, "chi", "简中")],
    Path("e2.mkv"): [_track(5, "chi", "简中"), _track(7, "chi", "繁中")],
    Path("e3.mkv"): [_track(1, "jpn", "")],
    Path("e4.mkv"): [],
}


def test_resolve_tracks_matches_by_key_not_by_track_id():
    """整季裡某集多一條音訊軌會把字幕軌 ID 推掉——規則必須依語言+軌名。"""
    got = resolve_tracks({("chi", "繁中")}, FILES)
    assert {p.name: [t.track_id for t in ts] for p, ts in got.items()} == {
        "e1.mkv": [2], "e2.mkv": [7]}


def test_resolve_tracks_omits_files_without_a_match():
    got = resolve_tracks({("chi", "繁中")}, FILES)
    assert Path("e3.mkv") not in got     # 只有日文軌
    assert Path("e4.mkv") not in got     # 完全沒有 ASS 軌


def test_resolve_tracks_keeps_every_track_sharing_one_key():
    """兩條軌都是 und 且無軌名時同一個鍵會命中兩條,兩條都要納入。"""
    files = {Path("e1.mkv"): [_track(2, "und", ""), _track(3, "und", "")]}
    got = resolve_tracks({("und", "")}, files)
    assert [t.track_id for t in got[Path("e1.mkv")]] == [2, 3]


def test_resolve_tracks_empty_keys_selects_nothing():
    assert resolve_tracks(set(), FILES) == {}


def test_all_keys_collects_every_key_in_the_batch():
    assert all_keys(FILES) == {("chi", "繁中"), ("chi", "简中"), ("jpn", "")}


def test_build_select_info_rows_reports_found_missing_and_multiple():
    files = {
        Path("b.mkv"): [_track(4, "chi", "繁中")],
        Path("a.mkv"): [_track(2, "chi", "繁中"), _track(3, "chi", "繁中")],
        Path("c.mkv"): [_track(9, "jpn", "")],
    }
    rows = build_select_info_rows(("chi", "繁中"), files)
    assert [r.video_name for r in rows] == ["a.mkv", "b.mkv", "c.mkv"]
    assert rows[0].track_ids == [2, 3]   # 多條符合
    assert rows[1].track_ids == [4]      # 剛好一條
    assert rows[2].track_ids == []       # 找不到


def test_uncovered_track_count_counts_videos_and_tracks():
    """範本檔沒有的軌會被靜默略過——對話框要能把數字講出來。"""
    videos, tracks = uncovered_track_count({("chi", "繁中")}, FILES)
    assert (videos, tracks) == (3, 3)    # e1 简中 / e2 简中 / e3 jpn


def test_uncovered_track_count_zero_when_every_key_selected():
    assert uncovered_track_count(all_keys(FILES), FILES) == (0, 0)
