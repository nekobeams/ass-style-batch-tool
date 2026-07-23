from __future__ import annotations

from ass_style_tool.mkv_io import MediaTrack
from ass_style_tool.track_edit import TrackEdit


def _tracks():
    return [
        MediaTrack(0, "video", "V_HEVC", "und", "", True, False),
        MediaTrack(1, "audio", "A_FLAC", "jpn", "", True, False),
        MediaTrack(2, "subtitles", "S_TEXT/ASS", "chi", "繁中", False, False),
    ]


def test_get_edits_defaults_keep_all(qapp):
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_tracks())
    edits = d.get_edits()
    assert set(edits) == {0, 1, 2}
    assert all(e.keep for e in edits.values())
    assert edits[2].set_default is None
    assert edits[2].language is None and edits[2].track_name is None


def test_get_edits_reads_widgets(qapp):
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_tracks())
    d._keep_checks[1].setChecked(False)          # 丟音訊
    d._default_combos[2].setCurrentIndex(1)      # 字幕預設=是
    d._lang_edits[2].setText("chi")
    d._name_edits[2].setText("繁體")
    edits = d.get_edits()
    assert edits[1].keep is False
    assert edits[2].set_default is True
    assert edits[2].language == "chi"
    assert edits[2].track_name == "繁體"


def test_existing_prefill(qapp):
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(
        _tracks(), existing={2: TrackEdit(keep=False, set_forced=True,
                                          language="eng")})
    assert d._keep_checks[2].isChecked() is False
    assert d._forced_combos[2].currentData() is True
    assert d._lang_edits[2].text() == "eng"


def test_table_has_alternating_rows(qapp):
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_tracks())
    assert d.table.alternatingRowColors() is True


def test_table_selects_full_rows(qapp):
    from PySide6.QtWidgets import QAbstractItemView
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_tracks())
    assert d.table.selectionBehavior() == QAbstractItemView.SelectRows


def test_cell_widget_stylesheets_are_scoped(qapp):
    """背景透明樣式表必須限定 widget 自身型別,不可用裸字串,
    否則會向下 cascade 到 QComboBox 彈出視窗、QLineEdit 右鍵選單等
    子元件,導致它們也變透明。"""
    from ass_style_tool.qt.modify_tracks_dialog import ModifyTracksDialog
    d = ModifyTracksDialog(_tracks())
    for lang in d._lang_edits:
        assert lang.styleSheet().strip().startswith("QLineEdit {")
    for name in d._name_edits:
        assert name.styleSheet().strip().startswith("QLineEdit {")
    for combo in d._default_combos + d._forced_combos:
        assert combo.styleSheet().strip().startswith("QComboBox {")
    # 保留欄的置中 wrapper 也應限定型別,即使 QCheckBox 本身沒有彈出子元件
    wrap = d.table.cellWidget(0, 0)
    assert wrap.styleSheet().strip().startswith("QWidget {")
