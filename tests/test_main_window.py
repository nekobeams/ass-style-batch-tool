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
