from __future__ import annotations

from ass_style_tool.profile import Profile
from ass_style_tool.profile_fields import DEFAULT_VALUES, values_from_profile


def test_get_values_roundtrip(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    editor.set_values(DEFAULT_VALUES)
    values = editor.get_values()
    # 關鍵欄位讀回一致
    assert values["fontname"] == DEFAULT_VALUES["fontname"]
    assert values["target_style_names"] == DEFAULT_VALUES["target_style_names"]
    assert str(values["fontsize"]) == str(DEFAULT_VALUES["fontsize"])
    assert bool(values["bold"]) == bool(DEFAULT_VALUES["bold"])
    assert values["alignment"] == DEFAULT_VALUES["alignment"]


def test_current_profile_from_defaults(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    editor.set_values(DEFAULT_VALUES)
    profile = editor.current_profile()
    assert isinstance(profile, Profile)
    assert profile.style.fontname == DEFAULT_VALUES["fontname"]
    assert profile.base_width == 1920


def test_set_values_from_profile_roundtrip(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    from ass_style_tool.profile_fields import profile_from_values
    editor = StyleEditor()
    p0 = profile_from_values(DEFAULT_VALUES)
    editor.set_values(values_from_profile(p0))
    assert editor.current_profile() == p0


def test_invalid_fontsize_raises(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    editor.set_values(DEFAULT_VALUES)
    editor.set_values({**DEFAULT_VALUES, "fontsize": "big"})
    import pytest
    with pytest.raises(ValueError):
        editor.current_profile()


def test_font_warning_toggles(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    # 一個幾乎不可能安裝的字型名 → 應標記未安裝
    editor.set_values({**DEFAULT_VALUES, "fontname": "NoSuchFont ZZZ 12345"})
    editor.refresh_font_warning()
    assert editor.font_warning_visible() is True


def test_values_changed_signal_fires(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    fired = []
    editor.values_changed.connect(lambda: fired.append(1))
    editor._edits["fontsize"].setText("88")
    assert len(fired) >= 1
    before = len(fired)
    editor._checks["bold"].setChecked(True)
    assert len(fired) > before


# ---------- 設定持久化 ----------

def test_save_and_restore_profile_setting(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from ass_style_tool.profile import save_profile
    from ass_style_tool.qt.style_editor import StyleEditor

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    editor_a = StyleEditor()
    monkeypatch.setattr(editor_a, "profiles_dir", lambda: profiles_dir)
    editor_a.set_values(DEFAULT_VALUES)
    profile = editor_a.current_profile()
    save_profile(profile, profiles_dir / "mine.json")
    editor_a._refresh_profile_list()
    idx = editor_a.profile_combo.findData(str(profiles_dir / "mine.json"))
    editor_a.profile_combo.setCurrentIndex(idx)

    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    editor_a.save_settings(settings)

    editor_b = StyleEditor()
    monkeypatch.setattr(editor_b, "profiles_dir", lambda: profiles_dir)
    editor_b._refresh_profile_list()
    editor_b.restore_settings(settings)
    assert editor_b.profile_combo.currentData() == str(profiles_dir / "mine.json")


def test_restore_profile_setting_missing_file_is_silent(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from ass_style_tool.qt.style_editor import StyleEditor

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    settings.setValue("style/profile", str(profiles_dir / "gone.json"))

    editor = StyleEditor()
    monkeypatch.setattr(editor, "profiles_dir", lambda: profiles_dir)
    editor._refresh_profile_list()
    editor.restore_settings(settings)  # 不應拋例外
    assert editor.profile_combo.currentData() is None


def test_restore_profile_setting_corrupt_file_is_silent(qapp, monkeypatch, tmp_path):
    """style/profile 指向的檔案存在(會被 findData 找到)但內容損毀時,
    restore_settings 不應拋出例外(對照手動載入按鈕會彈出 QMessageBox,
    啟動流程不可有互動對話框擋住)。"""
    from PySide6.QtCore import QSettings
    from ass_style_tool.qt.style_editor import StyleEditor

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    bad_path = profiles_dir / "corrupt.json"
    bad_path.write_text("not valid json", encoding="utf-8")

    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    settings.setValue("style/profile", str(bad_path))

    editor = StyleEditor()
    monkeypatch.setattr(editor, "profiles_dir", lambda: profiles_dir)
    editor._refresh_profile_list()  # corrupt.json 存在於目錄中,會出現在下拉選單
    editor.restore_settings(settings)  # 不應拋例外

    # findData 找到了該路徑,combo 會選到它,但 load_profile_from 失敗被吞掉,
    # 欄位維持先前狀態(建構時的 DEFAULT_VALUES),不會是損毀資料。
    assert editor.profile_combo.currentData() == str(bad_path)
    assert editor._edits["fontname"].text() == DEFAULT_VALUES["fontname"]
