from __future__ import annotations

from ass_style_tool.mkv_io import MediaTrack
from ass_style_tool.track_edit import TrackEdit, build_source_track_flags


def _tracks():
    return [
        MediaTrack(0, "video", "V_HEVC", "und", "", True, False),
        MediaTrack(1, "audio", "A_FLAC", "jpn", "", True, False),
        MediaTrack(2, "subtitles", "S_TEXT/ASS", "chi", "繁A", False, False),
        MediaTrack(3, "subtitles", "S_TEXT/ASS", "chi", "繁B", False, False),
    ]


def test_empty_edits_no_flags():
    assert build_source_track_flags({}, _tracks()) == []


def test_all_keep_no_attrs_no_flags():
    edits = {i: TrackEdit() for i in range(4)}
    assert build_source_track_flags(edits, _tracks()) == []


def test_drop_one_subtitle_lists_kept_ids():
    flags = build_source_track_flags({3: TrackEdit(keep=False)}, _tracks())
    assert "--subtitle-tracks" in flags
    assert flags[flags.index("--subtitle-tracks") + 1] == "2"
    assert "--no-video" not in flags and "--no-audio" not in flags


def test_drop_all_audio_uses_no_audio():
    flags = build_source_track_flags({1: TrackEdit(keep=False)}, _tracks())
    assert "--no-audio" in flags


def test_default_forced_language_name_on_kept_track():
    flags = build_source_track_flags(
        {2: TrackEdit(set_default=True, set_forced=False,
                      language="chi", track_name="繁體")}, _tracks())
    assert flags[flags.index("--default-track") + 1] == "2:yes"
    assert flags[flags.index("--forced-track") + 1] == "2:no"
    assert flags[flags.index("--language") + 1] == "2:chi"
    assert flags[flags.index("--track-name") + 1] == "2:繁體"


def test_attrs_not_emitted_for_dropped_track():
    flags = build_source_track_flags(
        {2: TrackEdit(keep=False, set_default=True)}, _tracks())
    assert "--default-track" not in flags        # 丟棄軌不設屬性
    assert flags[flags.index("--subtitle-tracks") + 1] == "3"


def test_none_and_blank_attrs_not_emitted():
    flags = build_source_track_flags(
        {2: TrackEdit(set_default=None, language="", track_name="")}, _tracks())
    assert flags == []


def test_only_ids_present_in_tracks_produce_flags():
    # id 9 不在 tracks 內 → 忽略(per-video 過濾)
    flags = build_source_track_flags(
        {9: TrackEdit(keep=False, set_default=True)}, _tracks())
    assert flags == []


def _audio_at_2():
    """軌 2 是音訊的檔案——與範本(字幕)不同類型。"""
    return [
        MediaTrack(0, "video", "V_HEVC", "und", "", True, False),
        MediaTrack(1, "audio", "A_FLAC", "jpn", "", True, False),
        MediaTrack(2, "audio", "A_AC3", "eng", "", False, False),
    ]


def test_type_mismatch_does_not_drop_the_wrong_track():
    # 使用者把「字幕軌 2」設為丟棄;這個檔案的軌 2 卻是音訊 → 不可丟音訊
    edits = {2: TrackEdit(keep=False, track_type="subtitles")}
    flags = build_source_track_flags(edits, _audio_at_2())
    assert "--no-audio" not in flags
    assert "--audio-tracks" not in flags
    assert flags == []          # 這個檔案完全不受影響


def test_type_mismatch_does_not_emit_attributes():
    edits = {2: TrackEdit(set_default=True, language="chi",
                          track_name="繁中", track_type="subtitles")}
    flags = build_source_track_flags(edits, _audio_at_2())
    assert flags == []


def test_type_match_still_applies():
    edits = {2: TrackEdit(set_default=True, track_type="subtitles")}
    flags = build_source_track_flags(edits, _tracks())   # 軌 2 是字幕
    assert flags[flags.index("--default-track") + 1] == "2:yes"


def test_track_type_none_keeps_old_behaviour():
    # 沒記錄類型 → 不比對,維持既有行為(回歸保護)
    edits = {2: TrackEdit(keep=False)}
    flags = build_source_track_flags(edits, _audio_at_2())
    assert "--no-audio" in flags or "--audio-tracks" in flags
