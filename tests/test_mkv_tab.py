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


def test_scan_done_closes_dialog_and_populates(qapp, monkeypatch):
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    tab = _tab(monkeypatch)
    tab._scan_dialog = ScanProgressDialog(tab)
    tab._on_scan_done(FILES)
    assert tab._scan_dialog is None                    # 對話框已關閉並釋放
    assert tab.tree.topLevelItemCount() == len(FILES)  # 結果有填進表格


def test_scan_cancelled_keeps_previous_results(qapp, monkeypatch):
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    tab = _tab(monkeypatch)
    tab.populate(FILES)                          # 先有一次成功掃描的結果
    before = tab.tree.topLevelItemCount()
    tab.run_button.setEnabled(False)             # 模擬 _on_scan 把按鈕變灰
    tab._scan_dialog = ScanProgressDialog(tab)
    tab._on_scan_cancelled()
    assert tab._scan_dialog is None              # 對話框已關閉
    assert tab.tree.topLevelItemCount() == before  # 舊結果保留,未被清空
    assert tab.run_button.isEnabled() is True    # 依既有結果恢復,不會卡在灰色


# ---------- 取消功能相關回歸測試 ----------

def test_scan_cancelled_clears_scanned_folder(qapp, monkeypatch):
    """Fix 3 回歸:取消後 _scanned_folder 要清空,同一資料夾才能重新觸發掃描。"""
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    tab = _tab(monkeypatch)
    tab._scanned_folder = "some/folder"
    tab._scan_dialog = ScanProgressDialog(tab)
    tab._on_scan_cancelled()
    assert tab._scanned_folder is None


def test_scan_done_with_shown_dialog_does_not_emit_cancelled(qapp, monkeypatch):
    """Fix 2 回歸:成功掃描收尾用 hide() 而非 close(),不應觸發 cancelled 信號。

    ScanProgressDialog.reject() 會在使用者按取消/Esc/X 時發出 cancelled,
    而 QDialog.closeEvent 預設會呼叫 reject()。若收尾呼叫 close(),
    一次成功的掃描收尾也會誤發 cancelled——必須實際 show() 對話框,
    這個行為才會被觸發。
    """
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    tab = _tab(monkeypatch)
    dialog = ScanProgressDialog(tab)
    dialog.show()
    tab._scan_dialog = dialog
    cancelled_calls = []
    dialog.cancelled.connect(lambda: cancelled_calls.append(1))
    tab._on_scan_done(FILES)
    assert cancelled_calls == []
    assert tab._scan_dialog is None


def test_dialog_cancel_actually_aborts_scan(qapp, monkeypatch, tmp_path):
    """Fix 1 回歸(重點測試):走真正的使用者路徑(對話框 Cancel/Esc/X)取消掃描。

    本檔其餘測試全是單執行緒的同步呼叫,這正是這個 bug 完全不會被抓到的
    原因:signal→worker slot 的連線在 worker 已 moveToThread 後會被 Qt
    解析成 queued connection,而 worker 所在的執行緒在 run() 執行期間
    不會跑事件迴圈,queued 的 cancel() 因此完全不會被處理。

    這裡不自建 worker/thread,而是讓 MkvTab._on_scan 自己的接線建立真正的
    QThread,並透過 ScanProgressDialog.reject()(對應使用者按 Cancel/Esc/
    右上角 X)觸發取消,驗證掃描確實提早中止、表格未被填入。
    """
    import time

    from ass_style_tool.qt.batch_worker import MkvScanWorker

    calls = []

    def slow_list_fn(path, mkvmerge):
        calls.append(path)
        time.sleep(0.05)
        return []

    def factory(folder, mkvmerge, list_fn=None):
        return MkvScanWorker(folder, mkvmerge, list_fn=slow_list_fn)

    monkeypatch.setattr("ass_style_tool.qt.mkv_tab.MkvScanWorker", factory)

    total_files = 20
    for i in range(total_files):
        (tmp_path / f"e{i:02d}.mkv").write_bytes(b"")

    tab = _tab(monkeypatch)
    tab.folder_edit.setText(str(tmp_path))
    tab._on_scan()
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
        assert tab.tree.topLevelItemCount() == 0, "取消後的掃描仍填入了表格"
    finally:
        if thread is not None:
            thread.quit()
            thread.wait(3000)


# ---------- Fix 1:關閉分頁不能留下孤兒的掃描對話框 ----------

def test_shutdown_closes_orphaned_scan_dialog(qapp, monkeypatch):
    """重點測試:掃描中途關閉整個分頁(對應使用者關掉主視窗)時,
    shutdown() 之前只收執行緒、沒收掉模態的 ScanProgressDialog——打包版
    是 console=False,主視窗關閉後 quitOnLastWindowClosed 因為這個還
    可見的對話框永遠不成立,process 會卡著不退出。shutdown() 現在要
    比照 MuxTab.shutdown() 呼叫 _finish_scan() 把對話框真的關掉。"""
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


def test_tree_has_alternating_rows(qapp, monkeypatch):
    # QSS 的 alternate-background-color 只有在控件端開啟時才生效
    tab = _tab(monkeypatch)
    assert tab.tree.alternatingRowColors() is True


def test_run_button_tagged_accent(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.run_button.property("accent") is True
