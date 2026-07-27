from __future__ import annotations

from pathlib import Path

from ass_style_tool.episode_match import (MatchResult, extract_episode,
                                          find_files, match_pairs)


def test_extract_bracketed_episode_dbd():
    name = "[DBD-Raws][High School DxD Born][01][1080P][BDRip][HEVC-10bit][FLAC].tc.ass"
    assert extract_episode(name) == 1


def test_extract_bracketed_episode_vcb():
    name = "[VCB-Studio] Blend S [12][Ma10p_1080p][x265_flac_aac].mkv"
    assert extract_episode(name) == 12


def test_extract_dash_episode_lolihouse():
    name = "[LoliHouse] Blend S - 12 [WebRip 1920x1080 HEVC-yuv420p10 AAC].LKSub-sc_繁_台.ass"
    assert extract_episode(name) == 12


def test_extract_sxxexx():
    assert extract_episode("Show.S01E05.1080p.mkv") == 5


def test_extract_ep_prefix():
    assert extract_episode("Anime EP07 BDRip.ass") == 7


def test_bracketed_720_excluded_finds_real_episode():
    assert extract_episode("[Group] Show [720][04].mkv") == 4


def test_resolution_in_brackets_not_episode():
    # [1080P] 非純數字、720p 也非純數字,唯一集數是 [03]
    assert extract_episode("[Group] Anime [1080P][03].ass") == 3


def test_no_episode_returns_none():
    assert extract_episode("movie.ass") is None


def test_find_files(tmp_path):
    (tmp_path / "a [01].ass").write_text("x", encoding="utf-8")
    (tmp_path / "b [02].ssa").write_text("x", encoding="utf-8")
    (tmp_path / "v [01].mkv").write_bytes(b"")
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    subs, videos = find_files(tmp_path)
    assert [p.name for p in subs] == ["a [01].ass", "b [02].ssa"]
    assert [p.name for p in videos] == ["v [01].mkv"]


def test_find_files_ignores_subfolders(tmp_path):
    """選資料夾固定只掃當層:子資料夾的字幕與影片一律不納入。

    使用者明確決定不加「包含子資料夾」勾選框(畫面已經太擠)。
    """
    (tmp_path / "a [01].ass").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b [02].ssa").write_text("x", encoding="utf-8")
    (tmp_path / "sub" / "v [02].mkv").write_bytes(b"")
    subs, videos = find_files(tmp_path)
    assert [p.name for p in subs] == ["a [01].ass"]
    assert videos == []


def _paths(*names: str) -> list[Path]:
    return [Path(n) for n in names]


def test_match_one_to_one():
    results = match_pairs(
        _paths("[A] Show [01].ass", "[A] Show [02].ass"),
        _paths("[B] Show - 01 [x].mkv", "[B] Show - 02 [x].mkv"),
    )
    assert [r.status for r in results] == ["matched", "matched"]
    assert results[0].video_path == Path("[B] Show - 01 [x].mkv")
    assert results[0].episode == 1


def test_match_no_video():
    results = match_pairs(_paths("[A] Show [03].ass"), [])
    assert results[0].status == "no_video"
    assert results[0].video_path is None


def test_match_no_episode():
    results = match_pairs(_paths("opening.ass"), _paths("[B] Show - 01.mkv"))
    assert results[0].status == "no_episode"


def test_match_ambiguous_two_videos():
    results = match_pairs(
        _paths("[A] Show [01].ass"),
        _paths("[B] Show - 01 [720p].mkv", "[C] Show - 01 [1080p].mkv"),
    )
    assert results[0].status == "ambiguous"
    assert results[0].video_path is None


def test_match_ambiguous_two_subs_same_episode():
    results = match_pairs(
        _paths("[A] Show [01].tc.ass", "[A] Show [01].sc.ass"),
        _paths("[B] Show - 01.mkv"),
    )
    assert [r.status for r in results] == ["ambiguous", "ambiguous"]


# ---------- SRT 支援 ----------

def test_sub_exts_includes_srt():
    from ass_style_tool.episode_match import SUB_EXTS
    assert ".srt" in SUB_EXTS
    assert ".ass" in SUB_EXTS
    assert ".ssa" in SUB_EXTS


def test_ass_output_name_keeps_ass_family():
    from pathlib import Path
    from ass_style_tool.episode_match import ass_output_name
    assert ass_output_name(Path("a/b.ass")) == Path("a/b.ass")
    assert ass_output_name(Path("a/b.ssa")) == Path("a/b.ssa")


def test_ass_output_name_normalizes_srt():
    from pathlib import Path
    from ass_style_tool.episode_match import ass_output_name
    assert ass_output_name(Path("a/movie.srt")) == Path("a/movie.ass")
    # 大小寫不敏感
    assert ass_output_name(Path("a/movie.SRT")) == Path("a/movie.ass")
