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


def test_button_keeps_the_sun_moon_symbol_across_modes(qapp, monkeypatch,
                                                       tmp_path):
    """按鈕外觀固定是 ☀ / 🌙,不隨模式變動。"""
    window = _window(monkeypatch, tmp_path)
    try:
        before = window.theme_button.text()
        assert "☀" in before and "🌙" in before
        window._toggle_theme()
        assert window.theme_button.text() == before
        window._set_theme_mode("system")
        assert window.theme_button.text() == before
    finally:
        window.deleteLater()


def test_tooltip_reflects_auto_versus_pinned(qapp, monkeypatch, tmp_path):
    """符號固定不變,所以目前是自動還是手動鎖定改由 tooltip 呈現。"""
    window = _window(monkeypatch, tmp_path)
    try:
        assert window.current_mode() == "system"
        # 要比對「目前:跟隨系統」而不是只比對「跟隨系統」——後者在提示文字
        # 「右鍵選擇跟隨系統」裡永遠都在,不管什麼模式都會通過。
        assert "目前:跟隨系統" in window.theme_button.toolTip()
        window._toggle_theme()                                # 手動鎖定
        tip = window.theme_button.toolTip()
        assert "目前:深色" in tip or "目前:淺色" in tip
        window._set_theme_mode("system")
        assert "目前:跟隨系統" in window.theme_button.toolTip()
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


# ---------- 切分頁自動掃描 ----------

def test_tab_change_triggers_auto_scan_once(qapp, monkeypatch, tmp_path):
    """用 _window() 建構(暫存 ini),避免動到使用者真正的 QSettings——
    與本檔其他測試一致的作法,brief 原本用的裸 MainWindow() 會寫到
    使用者登錄檔/系統設定檔。"""
    window = _window(monkeypatch, tmp_path)
    try:
        calls = []
        monkeypatch.setattr(window.subtitle_tab, "auto_scan_once",
                            lambda: calls.append("subtitle"))
        # MkvTab 尚未有 auto_scan_once(Task 8 才加),raising=False 讓
        # monkeypatch 直接把它掛到這個實例上,驗證 _on_tab_changed 的
        # getattr 判斷式能吃到後續補上的方法。
        monkeypatch.setattr(window.mkv_tab, "auto_scan_once",
                            lambda: calls.append("mkv"), raising=False)
        window.tabs.setCurrentIndex(1)     # MKV
        window.tabs.setCurrentIndex(0)     # 字幕檔
        assert calls == ["mkv", "subtitle"]
    finally:
        window.deleteLater()


def test_tab_change_ignores_tabs_without_auto_scan(qapp, monkeypatch, tmp_path):
    """「樣式與預覽」分頁沒有 auto_scan_once,切過去不可炸。"""
    window = _window(monkeypatch, tmp_path)
    try:
        window.tabs.setCurrentIndex(window.tabs.count() - 1)
    finally:
        window.deleteLater()


# ---------- I4:StyleEditor 存/讀 profile 要接得到分頁的 StylePicker ----------
#
# 這裡是唯一同時拿得到 StyleEditor 與三個工作分頁的地方(組裝點),
# 所以 I4 的接線只能在這裡測——StyleEditor 自己那一側的契約
# (get_target_style_names / profile_loaded)由 test_style_editor.py 覆蓋。

def test_save_uses_target_tab_selection_even_after_switching_to_style_tab(
        qapp, monkeypatch, tmp_path):
    """真實使用者流程:先在字幕檔分頁的側欄勾好樣式,再切到「樣式與
    預覽」分頁按下「另存」——這時 tabs.currentWidget() 已經是沒有
    style_picker 的分頁了。_last_work_tab 要記住『字幕檔』分頁,而不是
    『目前分頁』,不然存檔時完全抓不到使用者剛才勾了什麼(這正是 I4
    描述的第二個方向:存檔寫進去的是過期的隱藏值)。"""
    window = _window(monkeypatch, tmp_path)
    try:
        window.subtitle_tab.style_picker.set_available(["CHT", "Default"])
        window.subtitle_tab.style_picker.set_selected(["CHT"])
        assert window._last_work_tab is window.subtitle_tab

        window.tabs.setCurrentWidget(window._preview_split)   # 切到樣式與預覽
        assert window._last_work_tab is window.subtitle_tab   # 記憶不被覆蓋

        profile = window.style_editor._profile_to_save()
        assert profile.target_style_names == ["CHT"]
    finally:
        window.deleteLater()


def test_save_falls_back_to_hidden_value_before_any_work_tab_was_active(
        qapp, monkeypatch, tmp_path):
    """程式剛啟動、_on_tab_changed 從未被『使用者切換』觸發過(初始分頁
    是字幕檔,_last_work_tab 已經指向它)以外的情境——直接把
    _last_work_tab 清成 None,模擬『判斷不出是哪個分頁』,存檔不該用
    空清單覆蓋掉隱藏值。"""
    window = _window(monkeypatch, tmp_path)
    try:
        window._last_work_tab = None
        profile = window.style_editor._profile_to_save()
        from ass_style_tool.profile_fields import DEFAULT_VALUES
        assert profile.target_style_names == [DEFAULT_VALUES["target_style_names"]]
    finally:
        window.deleteLater()


def test_loading_profile_feeds_names_into_the_active_tab_picker(
        qapp, monkeypatch, tmp_path):
    """載入一個帶有 target_style_names 的 profile,要把那些名字塞進
    『最後作用中』分頁的 StylePicker 選取——不然「載入 profile」對任何
    分頁的畫面都毫無效果(I4 描述的第一個方向)。"""
    from ass_style_tool.profile import save_profile
    from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values

    window = _window(monkeypatch, tmp_path)
    try:
        window.tabs.setCurrentWidget(window.mux_tab)
        assert window._last_work_tab is window.mux_tab

        profile_path = tmp_path / "loaded.json"
        save_profile(profile_from_values(
            {**DEFAULT_VALUES, "target_style_names": "CHT, CHS"}), profile_path)

        window.style_editor.load_profile_from(profile_path)

        assert window.mux_tab.style_picker.selected() == ["CHT", "CHS"]
    finally:
        window.deleteLater()


def test_loading_profile_does_not_touch_a_different_tabs_picker(
        qapp, monkeypatch, tmp_path):
    """載入 profile 只能影響『最後作用中』的那個分頁,不能悄悄改到使用者
    根本沒在看的另一個分頁的勾選。"""
    from ass_style_tool.profile import save_profile
    from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values

    window = _window(monkeypatch, tmp_path)
    try:
        window.mkv_tab.style_picker.set_available(["Default"])
        window.mkv_tab.style_picker.set_selected(["Default"])
        window.tabs.setCurrentWidget(window.mux_tab)

        profile_path = tmp_path / "loaded.json"
        save_profile(profile_from_values(
            {**DEFAULT_VALUES, "target_style_names": "CHT"}), profile_path)
        window.style_editor.load_profile_from(profile_path)

        assert window.mux_tab.style_picker.selected() == ["CHT"]
        assert window.mkv_tab.style_picker.selected() == ["Default"]   # 沒被動到
    finally:
        window.deleteLater()
