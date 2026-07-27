from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_io import SubtitleTrack
from ass_style_tool.qt.select_tracks_dialog import SelectTracksDialog


def _track(tid, lang="chi", name="繁中"):
    return SubtitleTrack(tid, "S_TEXT/ASS", lang, name, False, False)


FILES = {
    Path("e1.mkv"): [_track(2, "chi", "繁中"), _track(3, "chi", "简中")],
    Path("e2.mkv"): [_track(5, "chi", "简中"), _track(7, "chi", "繁中")],
    Path("e3.mkv"): [_track(1, "jpn", "")],
}


def test_defaults_to_every_track_checked(qapp):
    """existing=None 代表從未設定過:維持舊行為(掃完全部勾起來)。"""
    dialog = SelectTracksDialog(FILES)
    assert dialog.get_keys() == {("chi", "繁中"), ("chi", "简中")}


def test_prefills_from_existing_selection(qapp):
    dialog = SelectTracksDialog(FILES, existing={("chi", "繁中")})
    assert dialog.get_keys() == {("chi", "繁中")}


def test_unchecking_removes_the_key(qapp):
    dialog = SelectTracksDialog(FILES)
    dialog._checks[1].setChecked(False)      # 範本檔的第二列(简中)
    assert dialog.get_keys() == {("chi", "繁中")}


def test_template_skips_files_with_no_ass_tracks(qapp):
    """排最前面的檔案讀不到軌時不能讓整個對話框空白(否則按確定後清光設定)。"""
    files = {
        Path("a_broken.mkv"): [],
        Path("b_good.mkv"): [_track(4, "chi", "繁中")],
    }
    dialog = SelectTracksDialog(files)
    assert [t.track_id for t in dialog._tracks] == [4]
    assert dialog.get_keys() == {("chi", "繁中")}


def test_no_tracks_at_all_yields_empty_selection(qapp):
    dialog = SelectTracksDialog({Path("a.mkv"): []})
    assert dialog._tracks == []
    assert dialog.get_keys() == set()


def test_info_table_marks_found_missing_and_multiple(qapp):
    files = {
        Path("a.mkv"): [_track(2, "chi", "繁中"), _track(3, "chi", "繁中")],
        Path("b.mkv"): [_track(4, "chi", "繁中")],
        Path("c.mkv"): [_track(9, "jpn", "")],
    }
    dialog = SelectTracksDialog(files)
    dialog.table.selectRow(0)                # 範本 a.mkv 的第一列(繁中)
    texts = [dialog.info_table.item(r, 1).text()
             for r in range(dialog.info_table.rowCount())]
    assert texts[0].startswith("⚠")          # a.mkv 有兩條符合
    assert "軌 2" in texts[0] and "軌 3" in texts[0]
    assert texts[1] == "✓ 軌 4"
    assert texts[2] == "✗ 沒有符合的軌"


def test_summary_warns_about_tracks_no_rule_covers(qapp):
    """範本檔沒有的軌會被靜默略過——數字必須講出來。"""
    dialog = SelectTracksDialog(FILES)        # 範本 e1 沒有 jpn 軌
    assert "1 部影片" in dialog.summary.text()
    assert "1 條" in dialog.summary.text()


def test_summary_is_empty_when_everything_is_covered(qapp):
    files = {Path("a.mkv"): [_track(2, "chi", "繁中")],
             Path("b.mkv"): [_track(5, "chi", "繁中")]}
    assert SelectTracksDialog(files).summary.text() == ""


def test_summary_updates_when_a_track_is_unchecked(qapp):
    files = {Path("a.mkv"): [_track(2, "chi", "繁中"), _track(3, "chi", "简中")]}
    dialog = SelectTracksDialog(files)
    assert dialog.summary.text() == ""
    dialog._checks[1].setChecked(False)
    assert "1 條" in dialog.summary.text()
