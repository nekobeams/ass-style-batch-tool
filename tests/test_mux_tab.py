from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_mux import MuxPair
from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values


def _tab(monkeypatch, available=True):
    fake = (lambda: Path("x.exe")) if available else (lambda: None)
    monkeypatch.setattr("ass_style_tool.qt.mux_tab.mkvmerge_path", fake)
    monkeypatch.setattr("ass_style_tool.qt.mux_tab.mkvextract_path", fake)
    from ass_style_tool.qt.mux_tab import MuxTab
    return MuxTab(lambda: profile_from_values(DEFAULT_VALUES))


PAIRS = [
    MuxPair(Path("a [01].mkv"), Path("a [01].ass"), 1, "matched"),
    MuxPair(Path("b [02].mkv"), None, 2, "no_subtitle"),
    MuxPair(Path("c [03].mkv"), Path("c [03].ass"), 3, "matched"),
]


def test_populate_checks_matched_only(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    assert tab.table.rowCount() == 3
    checked = tab.checked_pairs()
    assert {p.video_path for p in checked} == {Path("a [01].mkv"), Path("c [03].mkv")}


def test_checked_pairs_respects_unchecking(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    tab.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    checked = tab.checked_pairs()
    assert {p.video_path for p in checked} == {Path("c [03].mkv")}


def test_current_meta(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.trackname_edit.setText("繁中")
    tab.default_check.setChecked(True)
    tab.forced_check.setChecked(False)
    meta = tab.current_meta()
    assert meta.track_name == "繁中"
    assert meta.default is True
    assert meta.forced is False
    assert meta.language                      # 有語言值(下拉預設)


def test_mode_switch_shows_scale_panel(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.scale_panel.isHidden() is True
    tab.scale_mode_radio.setChecked(True)
    assert tab.scale_panel.isHidden() is False


def test_run_button_enabled_after_populate(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.run_button.isEnabled() is False
    tab.populate(PAIRS)
    assert tab.run_button.isEnabled() is True


def test_tools_missing_disables(qapp, monkeypatch):
    tab = _tab(monkeypatch, available=False)
    assert tab.tools_available is False
    assert tab.run_button.isEnabled() is False
    assert tab.scan_button.isEnabled() is False


def test_operation_none_when_direct(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.direct_mode_radio.setChecked(True)
    assert tab.current_operation() is None


def test_operation_profile_when_apply(qapp, monkeypatch):
    from ass_style_tool.profile import Profile
    tab = _tab(monkeypatch)
    tab.apply_mode_radio.setChecked(True)
    assert isinstance(tab.current_operation(), Profile)


# ---------- 各群組 RadioButton 互不干擾 ----------

def test_radio_groups_do_not_interfere(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.scale_mode_radio.setChecked(True)
    tab.replace_radio.setChecked(True)      # 點輸出模式(取代原影片)
    assert tab.scale_mode_radio.isChecked() is True   # 封裝前處理不得被取消
    tab.outdir_radio.setChecked(True)
    assert tab.scale_mode_radio.isChecked() is True
    # 封裝前處理的三個 radio 仍應在同一群組內互斥
    tab.apply_mode_radio.setChecked(True)
    assert tab.direct_mode_radio.isChecked() is False
    assert tab.scale_mode_radio.isChecked() is False


# ---------- 手動配對:set_row_subtitle 模型變更 ----------

def test_set_row_subtitle_assigns_and_checks(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    # 第 1 列原本 no_subtitle → 手動指定字幕
    tab.set_row_subtitle(1, Path("manual [02].ass"))
    assert tab.table.item(1, 0).checkState() == Qt.CheckState.Checked
    checked = {p.video_path: p for p in tab.checked_pairs()}
    assert Path("b [02].mkv") in checked
    assert checked[Path("b [02].mkv")].subtitle_path == Path("manual [02].ass")


def test_set_row_subtitle_clear_unchecks(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    # 第 0 列原本 matched → 清除指定
    tab.set_row_subtitle(0, None)
    assert tab.table.item(0, 0).checkState() == Qt.CheckState.Unchecked
    assert Path("a [01].mkv") not in {p.video_path for p in tab.checked_pairs()}


def test_set_row_subtitle_reassign_matched(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    # 第 0 列原本 matched(a [01].ass)→ 改指定別的字幕
    tab.set_row_subtitle(0, Path("other [01].ass"))
    checked = {p.video_path: p for p in tab.checked_pairs()}
    assert checked[Path("a [01].mkv")].subtitle_path == Path("other [01].ass")


def test_set_row_subtitle_recovers_ambiguous_row(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    pairs = [MuxPair(Path("d [04].mkv"), None, 4, "ambiguous")]
    tab.populate(pairs)
    tab.set_row_subtitle(0, Path("chosen [04].ass"))
    checked = {p.video_path: p for p in tab.checked_pairs()}
    assert Path("d [04].mkv") in checked
    assert checked[Path("d [04].mkv")].subtitle_path == Path("chosen [04].ass")


def test_set_row_subtitle_recovers_no_episode_row(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    pairs = [MuxPair(Path("movie.mkv"), None, None, "no_episode")]
    tab.populate(pairs)
    tab.set_row_subtitle(0, Path("movie.ass"))
    checked = {p.video_path: p for p in tab.checked_pairs()}
    assert Path("movie.mkv") in checked
    assert checked[Path("movie.mkv")].subtitle_path == Path("movie.ass")


# ---------- 手動配對:字幕欄下拉選單 ----------

def test_populate_builds_subtitle_combos(qapp, monkeypatch):
    from PySide6.QtWidgets import QComboBox
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    combo0 = tab.table.cellWidget(0, 2)
    assert isinstance(combo0, QComboBox)
    # matched 列:初始選取為其字幕
    assert combo0.currentData() == Path("a [01].ass")
    # no_subtitle 列:初始選取「(無)」→ None
    combo1 = tab.table.cellWidget(1, 2)
    assert combo1.currentData() is None


def test_subtitle_combo_stylesheet_is_scoped(qapp, monkeypatch):
    """背景透明樣式表必須限定 QComboBox 型別,不可用裸字串,
    否則會 cascade 到彈出視窗導致其背景消失。"""
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    for row in range(tab.table.rowCount()):
        combo = tab.table.cellWidget(row, 2)
        assert combo.styleSheet().strip().startswith("QComboBox {")


def test_combo_options_include_available_and_current(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab._available_subtitles = [Path("x [01].ass"), Path("y [02].ass")]
    tab.populate(PAIRS)
    combo0 = tab.table.cellWidget(0, 2)
    datas = [combo0.itemData(i) for i in range(combo0.count())]
    assert None in datas                       # 「(無)」選項
    assert Path("x [01].ass") in datas          # 掃描到的可用字幕
    assert Path("y [02].ass") in datas
    assert Path("a [01].ass") in datas          # 該列現有字幕(即使不在掃描清單也保留)
    assert combo0.currentData() == Path("a [01].ass")


# ---------- 設定持久化 ----------

def test_save_and_restore_settings_roundtrip(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab_a = _tab(monkeypatch)
    tab_a.video_edit.setText(r"C:\mux\video")
    tab_a.subtitle_edit.setText(r"C:\mux\sub")
    tab_a.replace_radio.setChecked(True)
    tab_a.outdir_edit.setText(r"C:\mux\out")
    tab_a.save_settings(settings)

    tab_b = _tab(monkeypatch)
    tab_b.restore_settings(settings)
    assert tab_b.video_edit.text() == r"C:\mux\video"
    assert tab_b.subtitle_edit.text() == r"C:\mux\sub"
    assert tab_b.replace_radio.isChecked() is True
    assert tab_b.outdir_edit.text() == r"C:\mux\out"


def test_restore_settings_does_not_trigger_scan(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    settings.setValue("mux/video_folder", str(tmp_path))
    settings.setValue("mux/subtitle_folder", str(tmp_path))
    settings.setValue("mux/output_mode", "outdir")
    settings.setValue("mux/outdir", "")

    tab = _tab(monkeypatch)
    tab.restore_settings(settings)
    assert tab._scanned_key is None
    assert tab.table.rowCount() == 0


def test_restore_settings_defaults_outdir_when_unset(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab = _tab(monkeypatch)
    tab.restore_settings(settings)
    assert tab.video_edit.text() == ""
    assert tab.subtitle_edit.text() == ""
    assert tab.outdir_radio.isChecked() is True


def test_modify_tracks_stores_edits(qapp, monkeypatch):
    import ass_style_tool.qt.mux_tab as mux_tab_mod
    from ass_style_tool.qt.mux_tab import MuxTab
    from ass_style_tool.mkv_io import MediaTrack
    from ass_style_tool.mkv_mux import MuxPair
    from ass_style_tool.track_edit import TrackEdit

    # 讓 tools 視為可用
    monkeypatch.setattr(mux_tab_mod, "mkvmerge_path", lambda: __import__("pathlib").Path("mkvmerge"))
    monkeypatch.setattr(mux_tab_mod, "mkvextract_path", lambda: __import__("pathlib").Path("mkvextract"))
    tab = MuxTab(lambda: None)

    # 有一部 matched 影片
    tab._pairs = [MuxPair(__import__("pathlib").Path("v.mkv"), None, 1, "matched")]

    monkeypatch.setattr(
        mux_tab_mod, "list_all_tracks",
        lambda video, mkvmerge: [MediaTrack(1, "audio", "A", "jpn", "", True, False)])

    class FakeDialog:
        def __init__(self, tracks, existing, parent):
            pass
        def exec(self):
            return 1
        def get_edits(self):
            return {1: TrackEdit(keep=False)}

    monkeypatch.setattr(mux_tab_mod, "ModifyTracksDialog", FakeDialog)
    tab._on_modify_tracks()
    assert tab._track_edits == {1: TrackEdit(keep=False)}


def test_table_has_alternating_rows(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.table.alternatingRowColors() is True


def test_table_selects_full_rows(qapp, monkeypatch):
    from PySide6.QtWidgets import QAbstractItemView
    tab = _tab(monkeypatch)
    assert tab.table.selectionBehavior() == QAbstractItemView.SelectRows


def test_run_button_tagged_accent(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.run_button.property("accent") is True
