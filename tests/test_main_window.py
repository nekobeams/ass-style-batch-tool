"""MainWindow 建構期的設定還原不應因損毀的 profile 檔而崩潰。"""
from __future__ import annotations


def test_main_window_survives_corrupt_profile_setting(qapp, monkeypatch, tmp_path):
    """在 MainWindow.__init__ 呼叫的 _restore_settings() 內,
    style_editor.restore_settings() 若遇到損毀的 profile 檔案,
    不應讓整個建構子拋出例外(否則每次啟動都會崩潰,且壞路徑
    會持續留在 QSettings 造成無法復原的磚化)。

    這裡把 main_window 模組內的 QSettings 建構子替換成一個以
    tmp_path 下 ini 檔為後盾的版本,避免測試寫到使用者真正的
    QSettings(登錄檔 / 系統設定檔)。
    """
    from PySide6.QtCore import QSettings
    import ass_style_tool.qt.main_window as main_window_module

    ini_path = tmp_path / "settings.ini"

    # 先用同一份 ini 檔寫入一個指向損毀 profile 檔的 style/profile 設定,
    # 並讓該檔案出現在 StyleEditor 預設的 profiles_dir() (Path.cwd()/"profiles")
    # 掃描範圍內,才會被 profile_combo 的 findData 找到而觸發載入。
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    bad_profile = profiles_dir / "corrupt.json"
    bad_profile.write_text("not valid json", encoding="utf-8")

    seed_settings = QSettings(str(ini_path), QSettings.Format.IniFormat)
    seed_settings.setValue("style/profile", str(bad_profile))
    seed_settings.sync()

    def _fake_qsettings(*_args, **_kwargs):
        return QSettings(str(ini_path), QSettings.Format.IniFormat)

    monkeypatch.setattr(main_window_module, "QSettings", _fake_qsettings)
    monkeypatch.setattr(
        main_window_module.StyleEditor, "profiles_dir", lambda self: profiles_dir)

    window = main_window_module.MainWindow()
    try:
        # 建構子沒有拋出例外就達成本測試目的;順便確認 profile 欄位
        # 沒有被損毀資料污染(load 失敗應被靜默吞掉)。
        assert window.style_editor.profile_combo.currentData() == str(bad_profile)
    finally:
        window.deleteLater()
        qapp.processEvents()
        qapp.processEvents()


def test_preview_readout_wired_to_style_editor(qapp, monkeypatch, tmp_path):
    """在 preview_panel 觸發一次讀出更新,左欄 style_editor.readout_view
    表格應被填(驗證 main_window 的訊號接線)。用空的暫存 QSettings 避免
    載入使用者真實設定或 profile。"""
    from PySide6.QtCore import QSettings
    import ass_style_tool.qt.main_window as mw
    from tests.test_ass_style import SAMPLE_ASS

    ini = tmp_path / "s.ini"
    monkeypatch.setattr(
        mw, "QSettings",
        lambda *a, **k: QSettings(str(ini), QSettings.Format.IniFormat))

    window = mw.MainWindow()
    try:
        sub = tmp_path / "e.ass"
        sub.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
        window.preview_panel.set_media(sub)       # 無影片,offscreen 安全
        table = window.style_editor.readout_view.table
        labels = [table.item(r, 0).text() for r in range(table.rowCount())]
        assert "字級" in labels
    finally:
        window.deleteLater()


def _window(monkeypatch, tmp_path):
    """用暫存 ini 建 MainWindow,避免動到使用者真正的 QSettings。"""
    from PySide6.QtCore import QSettings
    import ass_style_tool.qt.main_window as mw
    ini = tmp_path / "theme.ini"
    monkeypatch.setattr(
        mw, "QSettings",
        lambda *a, **k: QSettings(str(ini), QSettings.Format.IniFormat))
    return mw.MainWindow()


def test_left_click_toggles_between_dark_and_light(qapp, monkeypatch, tmp_path):
    """左鍵必定翻面:不論起點是跟隨系統還是手動,按下去顏色一定改變。"""
    window = _window(monkeypatch, tmp_path)
    try:
        import ass_style_tool.qt.main_window as mw
        before = mw.resolve_theme(
            window.current_mode(), mw.system_is_dark(qapp))
        window._toggle_theme()
        assert window.current_mode() in ("dark", "light")
        assert window.current_mode() != before or before not in ("dark", "light")
        after = mw.resolve_theme(window.current_mode(), mw.system_is_dark(qapp))
        assert after != before          # 真的翻面了
        window._toggle_theme()
        assert mw.resolve_theme(
            window.current_mode(), mw.system_is_dark(qapp)) == before
    finally:
        window.deleteLater()


def test_toggle_syncs_menu_checkmark(qapp, monkeypatch, tmp_path):
    """左鍵切換後,右鍵選單的勾選必須同步,否則會顯示過期狀態。"""
    window = _window(monkeypatch, tmp_path)
    try:
        window._toggle_theme()
        mode = window.current_mode()
        assert window._theme_actions[mode].isChecked() is True
    finally:
        window.deleteLater()


def test_button_symbols_distinguish_auto_from_pinned(qapp, monkeypatch, tmp_path):
    """系統本身是深色時,自動與手動深色的顏色完全一樣,只能靠符號分辨:
    兩個符號 = 跟隨系統,單一符號 = 已鎖定該模式。"""
    window = _window(monkeypatch, tmp_path)
    try:
        assert window.current_mode() == "system"
        auto_text = window.theme_button.text()
        assert "☀" in auto_text and "🌙" in auto_text        # 兩個符號 = 自動

        window._toggle_theme()                                # 變成手動鎖定
        pinned = window.theme_button.text()
        assert ("☀" in pinned) != ("🌙" in pinned)            # 只剩一個符號

        window._set_theme_mode("system")                      # 右鍵選單的路徑
        restored = window.theme_button.text()
        assert "☀" in restored and "🌙" in restored
    finally:
        window.deleteLater()


def test_language_list_keeps_common_three_first_and_und_last(qapp):
    """新增語言不能打亂原本最順手的前三個,「未定」也要留在最後。"""
    from ass_style_tool.qt.mux_tab import _LANGUAGES
    codes = [code for _label, code in _LANGUAGES]
    assert codes[:3] == ["chi", "jpn", "eng"]
    assert codes[-1] == "und"
    assert len(set(codes)) == len(codes)          # 沒有重複代碼
    for _label, code in _LANGUAGES:
        assert len(code) == 3                     # ISO 639-2 一律三碼


def test_theme_button_lives_in_the_tab_bar_corner(qapp, monkeypatch, tmp_path):
    """按鈕要在分頁籤同一列,不是自成一列。"""
    from PySide6.QtCore import Qt
    window = _window(monkeypatch, tmp_path)
    try:
        assert window.tabs.cornerWidget(Qt.TopRightCorner) is window.theme_button
    finally:
        window.deleteLater()
