from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_io import MediaTrack
from ass_style_tool.track_edit import TrackEdit


def _tracks():
    return [
        MediaTrack(0, "video", "V_HEVC", "und", "", True, False),
        MediaTrack(1, "audio", "A_FLAC", "jpn", "", True, False),
        MediaTrack(2, "subtitles", "S_TEXT/ASS", "chi", "繁中", False, False),
    ]


def _files():
    """單一檔案的 map——既有測試沿用這個,行為與原本傳 list 相同。"""
    return {Path("a.mkv"): _tracks()}


def test_get_edits_defaults_keep_all(qapp):
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_files())
    edits = d.get_edits()
    assert set(edits) == {0, 1, 2}
    assert all(e.keep for e in edits.values())
    assert edits[2].set_default is None
    assert edits[2].language is None and edits[2].track_name is None


def test_get_edits_reads_widgets(qapp):
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_files())
    d._keep_checks[1].setChecked(False)          # 丟音訊
    d._default_combos[2].setCurrentIndex(1)      # 字幕預設=是
    idx = d._lang_combos[2].findData("chi")
    assert idx >= 0
    d._lang_combos[2].setCurrentIndex(idx)
    d._name_edits[2].setText("繁體")
    edits = d.get_edits()
    assert edits[1].keep is False
    assert edits[2].set_default is True
    assert edits[2].language == "chi"
    assert edits[2].track_name == "繁體"


def test_existing_prefill(qapp):
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(
        _files(), existing={2: TrackEdit(keep=False, set_forced=True,
                                         language="eng")})
    assert d._keep_checks[2].isChecked() is False
    assert d._forced_combos[2].currentData() is True
    assert d._lang_combos[2].currentData() == "eng"


def test_existing_prefill_with_mismatched_type_is_discarded(qapp):
    """既有設定是為別種軌道存的(例如上一批次 id 2 是字幕),這批範本裡
    id 2 卻是別的類型——prefill 不能沿用,否則 get_edits() 會把「為字幕
    做的丟棄設定」重新蓋上目前的類型,讓 build_source_track_flags 的
    type guard 誤判為安全,正是 Fix 1 要防的情境。"""
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    # _tracks() 的 id 2 是 subtitles;existing 卻記錄它曾是 audio 的設定
    d = ModifyTracksDialog(
        _files(), existing={2: TrackEdit(keep=False, track_type="audio")})
    assert d._keep_checks[2].isChecked() is True   # 不合的 prefill 被丟棄,回到預設
    edits = d.get_edits()
    assert edits[2].track_type == "subtitles"
    assert edits[2].keep is True


# ---------- Fix 4b:語言欄改成精選 combo,不能再自由輸入 ----------

def test_language_column_is_combo_not_lineedit(qapp):
    from PySide6.QtWidgets import QComboBox
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_files())
    for combo in d._lang_combos:
        assert isinstance(combo, QComboBox)
        assert combo.isEditable() is False   # 不可自由輸入,只能從清單挑


def test_language_combo_options_match_shared_languages_list(qapp):
    from ass_style_tool.languages import LANGUAGES
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_files())
    combo = d._lang_combos[0]
    codes = {combo.itemData(i) for i in range(combo.count())}
    assert codes == {""} | {code for _label, code in LANGUAGES}


def test_language_combo_default_means_unchanged(qapp):
    """沒有既有設定時,預設選中的項目要讓 get_edits() 回傳 language=None
    (=不變),延續原本 QLineEdit 留空的語意。"""
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_files())
    assert d._lang_combos[2].currentData() == ""
    edits = d.get_edits()
    assert edits[2].language is None


def test_language_combo_cannot_hold_arbitrary_typo_text(qapp):
    """Fix 4b 的核心:選項僅限清單裡的碼,沒有辦法讓 get_edits() 產生
    像 "zh"/"中文" 這種會讓整批 mkvmerge 失敗的自由文字。"""
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_files())
    combo = d._lang_combos[2]
    assert combo.findData("zh") == -1
    assert combo.findText("中文") == -1


def test_table_has_alternating_rows(qapp):
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_files())
    assert d.table.alternatingRowColors() is True


def test_table_selects_full_rows(qapp):
    from PySide6.QtWidgets import QAbstractItemView
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_files())
    assert d.table.selectionBehavior() == QAbstractItemView.SelectRows


def test_cell_widget_stylesheets_are_scoped(qapp):
    """背景透明樣式表必須限定 widget 自身型別,不可用裸字串,
    否則會向下 cascade 到 QComboBox 彈出視窗、QLineEdit 右鍵選單等
    子元件,導致它們也變透明。"""
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_files())
    for name in d._name_edits:
        assert name.styleSheet().strip().startswith("QLineEdit {")
    for combo in d._default_combos + d._forced_combos + d._lang_combos:
        assert combo.styleSheet().strip().startswith("QComboBox {")
    # 保留欄的置中 wrapper 也應限定型別,即使 QCheckBox 本身沒有彈出子元件
    wrap = d.table.cellWidget(0, 0)
    assert wrap.styleSheet().strip().startswith("QWidget {")


def test_get_edits_records_track_type(qapp):
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_files())
    edits = d.get_edits()
    # _tracks() 是 video(0) / audio(1) / subtitles(2)
    assert edits[0].track_type == "video"
    assert edits[1].track_type == "audio"
    assert edits[2].track_type == "subtitles"


def test_info_table_shows_one_row_per_file(qapp):
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog

    files = {
        Path("a.mkv"): _tracks(),
        Path("b.mkv"): [MediaTrack(0, "video", "V", "und", "", True, False)],
    }
    d = ModifyTracksDialog(files)
    assert d.info_table.rowCount() == 2
    assert d.info_table.item(0, 0).text() == "a.mkv"
    assert d.info_table.item(1, 0).text() == "b.mkv"


def test_info_table_follows_selected_track_row(qapp):
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog

    files = {
        Path("a.mkv"): _tracks(),                                  # 軌2=字幕
        Path("b.mkv"): [MediaTrack(2, "audio", "A", "jpn", "", True, False)],
    }
    d = ModifyTracksDialog(files)
    d.table.selectRow(2)                       # 選字幕軌(ID 2)
    b_row = 1 if d.info_table.item(1, 0).text() == "b.mkv" else 0
    assert "類型不符" in d.info_table.item(b_row, 1).text()

    d.table.selectRow(0)                       # 改選視訊軌(ID 0)
    b_row = 1 if d.info_table.item(1, 0).text() == "b.mkv" else 0
    assert "✗" in d.info_table.item(b_row, 1).text()   # b.mkv 沒有軌 0


def test_template_skips_unreadable_first_file(qapp):
    """list_all_tracks 讀失敗回傳 []。若排序後第一個檔案剛好是那個壞檔,
    範本不該跟著空白——否則整張編輯表零列,get_edits() 回傳 {},OK
    後會把使用者原本的設定整批清空(Fix 2)。"""
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog

    files = {
        Path("a_broken.mkv"): [],            # 字母序最前,但讀不到軌道
        Path("b_ok.mkv"): _tracks(),
    }
    d = ModifyTracksDialog(files)
    assert len(d._tracks) == 3
    edits = d.get_edits()
    assert set(edits) == {0, 1, 2}
    assert edits[2].track_type == "subtitles"
