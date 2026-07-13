from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_io import SubtitleTrack
from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values


def _track(tid, lang="chi", name="繁中"):
    return SubtitleTrack(tid, "S_TEXT/ASS", lang, name, False, False)


def _tab(monkeypatch, available=True):
    fake = (lambda: Path("x.exe")) if available else (lambda: None)
    monkeypatch.setattr("ass_style_tool.qt.mkv_tab.mkvmerge_path", fake)
    monkeypatch.setattr("ass_style_tool.qt.mkv_tab.mkvextract_path", fake)
    from ass_style_tool.qt.mkv_tab import MkvTab
    return MkvTab(lambda: profile_from_values(DEFAULT_VALUES))


FILES = {
    Path("e1.mkv"): [_track(2, "chi", "繁中"), _track(3, "chi", "简中")],
    Path("e2.mkv"): [_track(5, "chi", "简中"), _track(7, "chi", "繁中")],
    Path("e3.mkv"): [],
}


def test_populate_builds_tree_all_checked(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    assert tab.tree.topLevelItemCount() == 3
    jobs = dict(tab.checked_jobs())
    assert {t.track_id for t in jobs[Path("e1.mkv")]} == {2, 3}
    assert {t.track_id for t in jobs[Path("e2.mkv")]} == {5, 7}
    assert Path("e3.mkv") not in jobs      # 無軌檔不成 job


def test_checked_jobs_respects_unchecking(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    # 取消 e1 的第二軌(简中)
    item = tab.tree.topLevelItem(0).child(1)
    item.setCheckState(0, Qt.CheckState.Unchecked)
    jobs = dict(tab.checked_jobs())
    assert {t.track_id for t in jobs[Path("e1.mkv")]} == {2}


def test_apply_same_type_from_current(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    # 基準:e1 只勾「繁中」
    tab.tree.topLevelItem(0).child(1).setCheckState(0, Qt.CheckState.Unchecked)
    tab.tree.setCurrentItem(tab.tree.topLevelItem(0).child(0))
    updated = tab.apply_same_type_from_current()
    assert updated >= 1
    jobs = dict(tab.checked_jobs())
    assert {t.track_id for t in jobs[Path("e2.mkv")]} == {7}   # e2 的繁中


def test_current_track(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab.tree.setCurrentItem(tab.tree.topLevelItem(1).child(0))
    path, track = tab.current_track()
    assert path == Path("e2.mkv")
    assert track.track_id == 5
    tab.tree.setCurrentItem(tab.tree.topLevelItem(0))   # 檔案節點
    assert tab.current_track() is None


def test_mode_switch_toggles_scale_panel(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.scale_panel.isHidden() is True
    tab.scale_mode_radio.setChecked(True)
    assert tab.scale_panel.isHidden() is False


def test_tools_missing_disables_controls(qapp, monkeypatch):
    tab = _tab(monkeypatch, available=False)
    assert tab.tools_available is False
    assert tab.scan_button.isEnabled() is False
    assert tab.run_button.isEnabled() is False


def test_run_button_enabled_after_populate(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.run_button.isEnabled() is False
    tab.populate(FILES)
    assert tab.run_button.isEnabled() is True


# ---------- 自動掃描(選資料夾即載入) ----------

def test_auto_scan_triggers_on_folder_chosen(qapp, monkeypatch, tmp_path):
    tab = _tab(monkeypatch)
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab._folder_chosen(str(tmp_path))
    assert calls == [1]
    assert tab.folder_edit.text() == str(tmp_path)


def test_auto_scan_skips_same_folder(qapp, monkeypatch, tmp_path):
    tab = _tab(monkeypatch)
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab._scanned_folder = str(tmp_path)
    tab.folder_edit.setText(str(tmp_path))
    tab._auto_scan()
    assert calls == []


def test_auto_scan_skips_when_tools_missing(qapp, monkeypatch, tmp_path):
    tab = _tab(monkeypatch, available=False)
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab._folder_chosen(str(tmp_path))
    assert calls == []


def test_auto_scan_skips_during_run(qapp, monkeypatch, tmp_path):
    tab = _tab(monkeypatch)
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab._thread = object()
    tab._folder_chosen(str(tmp_path))
    assert calls == []


# ---------- 各群組 RadioButton 互不干擾 ----------

def test_radio_groups_do_not_interfere(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.scale_mode_radio.setChecked(True)
    tab.replace_radio.setChecked(True)      # 點輸出模式(取代原檔)
    assert tab.scale_mode_radio.isChecked() is True   # 操作模式不得被取消
    tab.outdir_radio.setChecked(True)
    assert tab.scale_mode_radio.isChecked() is True


# ---------- 設定持久化 ----------

def test_save_and_restore_settings_roundtrip(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab_a = _tab(monkeypatch)
    tab_a.folder_edit.setText(r"C:\mkv\show")
    tab_a.replace_radio.setChecked(True)
    tab_a.outdir_edit.setText(r"C:\mkv\out")
    tab_a.save_settings(settings)

    tab_b = _tab(monkeypatch)
    tab_b.restore_settings(settings)
    assert tab_b.folder_edit.text() == r"C:\mkv\show"
    assert tab_b.replace_radio.isChecked() is True
    assert tab_b.outdir_edit.text() == r"C:\mkv\out"


def test_restore_settings_does_not_trigger_scan(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    settings.setValue("mkv/folder", str(tmp_path))
    settings.setValue("mkv/output_mode", "outdir")
    settings.setValue("mkv/outdir", "")

    tab = _tab(monkeypatch)
    tab.restore_settings(settings)
    assert tab._scanned_folder is None


def test_restore_settings_defaults_outdir_when_unset(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab = _tab(monkeypatch)
    tab.restore_settings(settings)
    assert tab.folder_edit.text() == ""
    assert tab.outdir_radio.isChecked() is True
