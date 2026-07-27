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


FILES = [Path("e1.mkv"), Path("e2.mkv"), Path("e3.mkv")]

TRACKS = {
    Path("e1.mkv"): [_track(2, "chi", "繁中"), _track(3, "chi", "简中")],
    Path("e2.mkv"): [_track(5, "chi", "简中"), _track(7, "chi", "繁中")],
    Path("e3.mkv"): [],
}


# ---------- 主畫面只列檔案 ----------

def test_populate_lists_files_all_checked(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    assert tab.file_table.rowCount() == 3
    assert [tab.file_table.item(r, 0).text() for r in range(3)] == [
        "e1.mkv", "e2.mkv", "e3.mkv"]
    assert all(tab.file_table.item(r, 0).checkState() == Qt.CheckState.Checked
               for r in range(3))
    assert tab.checked_files() == FILES


def test_track_column_is_blank_before_any_track_scan(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    assert [tab.file_table.item(r, 1).text() for r in range(3)] == ["", "", ""]


def test_checked_files_respects_unchecking(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab.file_table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    assert tab.checked_files() == [Path("e1.mkv"), Path("e3.mkv")]


# ---------- 規則解析 ----------

def test_jobs_use_every_ass_track_when_no_rule_was_set(qapp, monkeypatch):
    """從未開過對話框 = 所有 ASS 字幕軌都套(維持舊的預設行為)。"""
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)
    jobs = dict(tab.current_jobs())
    assert {t.track_id for t in jobs[Path("e1.mkv")]} == {2, 3}
    assert {t.track_id for t in jobs[Path("e2.mkv")]} == {5, 7}
    assert Path("e3.mkv") not in jobs        # 無軌檔不成 job


def test_jobs_follow_the_selected_rule_across_files(qapp, monkeypatch):
    """規則依語言+軌名,不是軌 ID:e1 的繁中是軌 2,e2 的繁中是軌 7。"""
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)
    tab._track_keys = {("chi", "繁中")}
    jobs = dict(tab.current_jobs())
    assert {t.track_id for t in jobs[Path("e1.mkv")]} == {2}
    assert {t.track_id for t in jobs[Path("e2.mkv")]} == {7}


def test_track_column_shows_resolution_per_file(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)
    tab._track_keys = {("chi", "繁中")}
    tab._refresh_track_column()
    assert tab.file_table.item(0, 1).text() == "✓ 軌 2"
    assert tab.file_table.item(1, 1).text() == "✓ 軌 7"
    assert tab.file_table.item(2, 1).text() == "✗ 無符合的軌"


def test_track_column_flags_multiple_matches(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate([Path("e1.mkv")])
    tab._files_tracks = {
        Path("e1.mkv"): [_track(2, "und", ""), _track(3, "und", "")]}
    tab._track_keys = {("und", "")}
    tab._refresh_track_column()
    assert tab.file_table.item(0, 1).text() == "⚠ 軌 2、軌 3"


def test_rescan_clears_the_previous_rule(qapp, monkeypatch, tmp_path):
    """換資料夾後舊規則必須失效——軌 ID 與軌組成都可能完全不同。"""
    tab = _tab(monkeypatch)
    (tmp_path / "a.mkv").write_bytes(b"")
    tab._files_tracks = dict(TRACKS)
    tab._track_keys = {("chi", "繁中")}
    tab.folder_edit.setText(str(tmp_path))
    tab._on_scan()
    assert tab._track_keys is None
    assert tab._files_tracks == {}
    assert tab.modify_tracks_button.text() == "修改既有軌道…"


def test_modify_button_shows_the_selected_count(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab._apply_keys({("chi", "繁中"), ("chi", "简中")})
    assert tab.modify_tracks_button.text() == "修改既有軌道…(已選 2 條)"


# ---------- 掃描資料夾只列檔案,不跑外部程序 ----------

def test_scan_lists_mkv_files_without_running_mkvmerge(qapp, monkeypatch, tmp_path):
    """回歸:選資料夾不應該對每個檔跑一次 mkvmerge -J。"""
    from ass_style_tool.qt import mkv_tab as mkv_tab_module
    started = []
    monkeypatch.setattr(mkv_tab_module, "MkvScanWorker",
                        lambda *a, **k: started.append(1))
    (tmp_path / "e1.mkv").write_bytes(b"")
    (tmp_path / "e2.mkv").write_bytes(b"")
    (tmp_path / "note.txt").write_text("x")
    tab = _tab(monkeypatch)
    tab.folder_edit.setText(str(tmp_path))
    tab._on_scan()
    assert started == []
    assert tab.file_table.rowCount() == 2


def test_scan_ignores_subfolders(qapp, monkeypatch, tmp_path):
    (tmp_path / "e1.mkv").write_bytes(b"")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "e2.mkv").write_bytes(b"")
    tab = _tab(monkeypatch)
    tab.folder_edit.setText(str(tmp_path))
    tab._on_scan()
    assert [tab.file_table.item(r, 0).text()
            for r in range(tab.file_table.rowCount())] == ["e1.mkv"]


# ---------- 掃軌完成後的分派 ----------

def test_track_scan_done_opens_the_dialog(qapp, monkeypatch):
    opened = []
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    monkeypatch.setattr(tab, "_open_select_dialog",
                        lambda: opened.append(1))
    tab._pending_action = "dialog"
    tab._on_track_scan_done(TRACKS)
    assert opened == [1]
    assert tab._files_tracks == TRACKS


def test_track_scan_done_starts_the_batch(qapp, monkeypatch):
    started = []
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    monkeypatch.setattr(tab, "_start_batch", lambda: started.append(1))
    tab._pending_action = "run"
    tab._on_track_scan_done(TRACKS)
    assert started == [1]


def test_track_scan_cancelled_does_neither(qapp, monkeypatch):
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    calls = []
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    monkeypatch.setattr(tab, "_open_select_dialog", lambda: calls.append("d"))
    monkeypatch.setattr(tab, "_start_batch", lambda: calls.append("r"))
    tab._pending_action = "run"
    tab._scan_dialog = ScanProgressDialog(tab)
    tab._on_track_scan_cancelled()
    assert calls == []
    assert tab._scan_dialog is None
    assert tab._pending_action is None


# ---------- 既有控件與行為 ----------

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
    assert tab.modify_tracks_button.isEnabled() is False


def test_run_button_enabled_after_populate(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.run_button.isEnabled() is False
    tab.populate(FILES)
    assert tab.run_button.isEnabled() is True


def test_radio_groups_do_not_interfere(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.scale_mode_radio.setChecked(True)
    tab.replace_radio.setChecked(True)
    assert tab.scale_mode_radio.isChecked() is True
    tab.outdir_radio.setChecked(True)
    assert tab.scale_mode_radio.isChecked() is True


def test_file_table_has_alternating_rows(qapp, monkeypatch):
    # QSS 的 alternate-background-color 只有在控件端開啟時才生效
    tab = _tab(monkeypatch)
    assert tab.file_table.alternatingRowColors() is True


def test_run_button_tagged_accent(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.run_button.property("accent") is True


# ---------- 自動掃描 ----------

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


# ---------- 版面方案 C ----------

def test_settings_live_in_the_sidebar_not_under_the_list(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.splitter.widget(0) is tab.file_table
    sidebar = tab.splitter.widget(1)
    for widget in (tab.apply_mode_radio, tab.scale_mode_radio, tab.scale_panel,
                   tab.modify_tracks_button, tab.outdir_radio, tab.outdir_edit,
                   tab.replace_radio):
        assert sidebar.isAncestorOf(widget), f"{widget} 不在設定側欄裡"


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


def test_save_settings_records_splitter_state(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    tab = _tab(monkeypatch)
    tab.save_settings(settings)
    assert settings.value("mkv/splitter") is not None


def test_restore_settings_without_saved_splitter_is_safe(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "empty.ini"), QSettings.Format.IniFormat)
    tab = _tab(monkeypatch)
    tab.restore_settings(settings)
    assert tab.splitter.count() == 2


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


# ---------- 取消掃描與關閉分頁(既有回歸,路徑改成掃軌) ----------

def test_dialog_cancel_actually_aborts_track_scan(qapp, monkeypatch, tmp_path):
    """重點測試:走真正的使用者路徑(對話框 Cancel/Esc/X)取消掃軌。

    本檔其餘測試全是單執行緒的同步呼叫,這正是這類 bug 完全不會被抓到的
    原因:signal→worker slot 的連線在 worker 已 moveToThread 後會被 Qt
    解析成 queued connection,而 worker 所在的執行緒在 run() 執行期間不跑
    事件迴圈,queued 的 cancel() 因此完全不會被處理。

    這裡不自建 worker/thread,而是讓 MkvTab 自己的接線建立真正的 QThread。
    """
    import time

    from ass_style_tool.qt.batch_worker import MkvScanWorker

    calls = []

    def slow_list_fn(path, mkvmerge):
        calls.append(path)
        time.sleep(0.05)
        return []

    def factory(paths, mkvmerge, list_fn=None):
        return MkvScanWorker(paths, mkvmerge, list_fn=slow_list_fn)

    monkeypatch.setattr("ass_style_tool.qt.mkv_tab.MkvScanWorker", factory)

    total_files = 20
    for i in range(total_files):
        (tmp_path / f"e{i:02d}.mkv").write_bytes(b"")

    tab = _tab(monkeypatch)
    tab.folder_edit.setText(str(tmp_path))
    tab._on_scan()
    assert tab.file_table.rowCount() == total_files
    tab._on_modify_tracks()
    thread = tab._scan_thread
    try:
        deadline = time.monotonic() + 5.0
        while not calls and time.monotonic() < deadline:
            qapp.processEvents()
        assert calls, "worker 在逾時內未開始掃描(環境問題,非本測試目的)"

        # 使用者按下 Cancel/Esc/X -> dialog.reject() -> cancelled 訊號
        # -> _request_scan_cancel -> 直接呼叫 worker.cancel()
        tab._scan_dialog.reject()

        deadline = time.monotonic() + 5.0
        while tab._scan_thread is not None and time.monotonic() < deadline:
            qapp.processEvents()

        assert len(calls) < total_files, (
            f"掃描未被中止:{len(calls)}/{total_files} 個檔案已掃描")
        assert tab._files_tracks == {}, "取消後的掃描結果仍被採用"
    finally:
        if thread is not None:
            thread.quit()
            thread.wait(3000)


def test_shutdown_closes_orphaned_scan_dialog(qapp, monkeypatch):
    """掃描中途關閉整個分頁時,shutdown() 要把模態的 ScanProgressDialog
    真的關掉——打包版是 console=False,主視窗關閉後 quitOnLastWindowClosed
    因為這個還可見的對話框永遠不成立,process 會卡著不退出。"""
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    tab = _tab(monkeypatch)
    dialog = ScanProgressDialog(tab)
    dialog.show()
    tab._scan_dialog = dialog
    assert dialog.isVisible() is True

    tab.shutdown()

    assert dialog.isVisible() is False
    assert tab._scan_dialog is None
    assert tab._scan_thread is None
    assert tab._scan_worker is None
