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


# ---------- profiles_dir 改用 %APPDATA% ----------

def test_profiles_dir_uses_appdata(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    assert editor.profiles_dir() == tmp_path / "ass-style-tool" / "profiles"


# ---------- migrate_legacy_profiles ----------

def test_migrate_copies_when_target_empty(tmp_path):
    from ass_style_tool.qt.style_editor import migrate_legacy_profiles
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "a.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "target"
    n = migrate_legacy_profiles(legacy, target)
    assert n == 1
    assert (target / "a.json").exists()
    assert (legacy / "a.json").exists()          # 不刪原檔


def test_migrate_skips_when_target_has_json(tmp_path):
    from ass_style_tool.qt.style_editor import migrate_legacy_profiles
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "a.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    (target / "existing.json").write_text("{}", encoding="utf-8")
    assert migrate_legacy_profiles(legacy, target) == 0
    assert not (target / "a.json").exists()      # 沒覆蓋/沒搬


def test_migrate_noop_when_legacy_absent(tmp_path):
    from ass_style_tool.qt.style_editor import migrate_legacy_profiles
    assert migrate_legacy_profiles(tmp_path / "nope", tmp_path / "target") == 0


def test_migrate_noop_when_legacy_empty(tmp_path):
    from ass_style_tool.qt.style_editor import migrate_legacy_profiles
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    target = tmp_path / "target"
    assert migrate_legacy_profiles(legacy, target) == 0


def test_style_editor_wraps_content_in_scrollarea_with_readout(qapp):
    from PySide6.QtWidgets import QScrollArea
    from ass_style_tool.qt.style_editor import StyleEditor
    from ass_style_tool.qt.readout_view import ReadoutView
    editor = StyleEditor()
    assert editor.findChild(QScrollArea) is not None      # 內容包在捲動區
    assert isinstance(editor.readout_view, ReadoutView)    # 底部有讀出元件


def test_font_warning_stylesheet_uses_typed_selector(qapp):
    """未加型別選擇器的 setStyleSheet 會往下級聯,曾經把 dark 模式下拉選單
    的對比度從 13.36:1 拖垮到 1.25:1。font_warning 必須用 "QLabel { ... }"
    包住規則,而不是裸的 "color: ...;"。"""
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    assert editor.font_warning.styleSheet().strip().startswith("QLabel")


def test_style_editor_readout_view_renders(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    from ass_style_tool.preview_readout import OriginalValues, build_readout
    from tests.test_profile import make_profile
    editor = StyleEditor()
    data = build_readout(make_profile(), 640, 360,
                         OriginalValues(40.0, 2.0, 1.0, 10, 10, 10),
                         "e.ass", None, None)
    editor.readout_view.update_from(data)
    labels = [editor.readout_view.table.item(r, 0).text()
              for r in range(editor.readout_view.table.rowCount())]
    assert "字級" in labels


# ---------- 目標 Style 欄位已移出樣式編輯器 ----------

def test_editor_has_no_target_style_widget(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    assert "target_style_names" not in editor._edits


def test_get_values_still_supplies_target_style_names(qapp):
    """profile_from_values 仍要求這個鍵,移除輸入框不能連鍵一起拿掉。"""
    from ass_style_tool.profile_fields import profile_from_values
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    values = editor.get_values()
    assert values["target_style_names"]
    assert profile_from_values(values).target_style_names


def test_loading_profile_keeps_its_target_names(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    editor.set_values({**editor.get_values(),
                       "target_style_names": "CHT, CHS"})
    assert editor.get_values()["target_style_names"] == "CHT, CHS"


# ---------- I4:target_style_names 的存/讀要接得到分頁的 StylePicker ----------
#
# StyleEditor 本身不認識任何分頁——存/讀 profile 的按鈕、_target_style_names
# 隱藏值,全部封在這個檔案裡,MainWindow(main_window.py)才是唯一同時拿
# 得到 StyleEditor 與三個工作分頁的地方。這裡只測 StyleEditor 這一側的
# 契約(建構子注入的 get_target_style_names callback、profile_loaded
# 訊號);main_window.py 那一側的接線由 test_main_window.py 覆蓋。

def test_profile_to_save_uses_injected_target_style_names(qapp):
    """存檔時,注入的 get_target_style_names() 回傳非 None 就要覆蓋
    target_style_names——這模擬「使用者剛在某個分頁的側欄勾好樣式」的
    情境,原本(修這個 finding 之前)這個值完全沒有管道傳進存檔流程。"""
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor(get_target_style_names=lambda: ["CHT", "CHS"])
    editor.set_values(DEFAULT_VALUES)
    profile = editor._profile_to_save()
    assert profile.target_style_names == ["CHT", "CHS"]


def test_profile_to_save_falls_back_to_hidden_value_when_callback_returns_none(
        qapp):
    """callback 回傳 None(判斷不出是哪個分頁的勾選,例如程式剛啟動)時,
    不能用空清單覆蓋掉隱藏值——那樣存出來的檔案會比修 bug 之前更糟
    (原本至少還留著上次載入/預設的值)。"""
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor(get_target_style_names=lambda: None)
    editor.set_values(DEFAULT_VALUES)
    profile = editor._profile_to_save()
    assert profile.target_style_names == [DEFAULT_VALUES["target_style_names"]]


def test_profile_to_save_without_callback_behaves_like_before(qapp):
    """沒有注入 callback(例如直接建構 StyleEditor() 不帶參數,舊行為)
    時,存檔邏輯要跟修這個 finding 之前完全一樣。"""
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    editor.set_values(DEFAULT_VALUES)
    profile = editor._profile_to_save()
    assert profile == editor.current_profile()


def test_profile_to_save_raises_on_invalid_fields_before_consulting_callback(
        qapp):
    """欄位驗證(profile_from_values)要先跑,壞欄位不能被 override 邏輯
    蓋過去變成看起來像是存檔成功。"""
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor(get_target_style_names=lambda: ["CHT"])
    editor.set_values({**DEFAULT_VALUES, "fontsize": "big"})
    import pytest
    with pytest.raises(ValueError):
        editor._profile_to_save()


def test_load_profile_from_emits_its_target_style_names(qapp, tmp_path):
    """載入 profile 後要把它的 target_style_names 廣播出去(profile_loaded
    訊號)——原本這個值只會落進編輯器自己的隱藏欄位,對任何分頁的
    StylePicker 毫無影響。"""
    from ass_style_tool.profile import save_profile
    from ass_style_tool.profile_fields import profile_from_values
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    profile = profile_from_values(
        {**DEFAULT_VALUES, "target_style_names": "CHT, CHS"})
    path = tmp_path / "p.json"
    save_profile(profile, path)

    seen = []
    editor.profile_loaded.connect(lambda names: seen.append(names))
    editor.load_profile_from(path)

    assert seen == [["CHT", "CHS"]]
    # 編輯器自己的欄位(隱藏值)也要照舊更新,訊號是額外的,不是取代。
    assert editor.get_values()["target_style_names"] == "CHT, CHS"


def test_load_profile_from_does_not_emit_when_file_is_corrupt(qapp, tmp_path):
    """壞檔案讀取失敗時不該廣播出一個假的/空的 target_style_names——
    load_profile() 在 set_values()/emit 之前就會拋例外,呼叫端
    (_on_load_selected/restore_settings)原本就吞掉這個例外,行為不變。"""
    from ass_style_tool.qt.style_editor import StyleEditor
    bad = tmp_path / "corrupt.json"
    bad.write_text("not valid json", encoding="utf-8")
    editor = StyleEditor()
    seen = []
    editor.profile_loaded.connect(lambda names: seen.append(names))
    import pytest
    with pytest.raises(Exception):
        editor.load_profile_from(bad)
    assert seen == []
