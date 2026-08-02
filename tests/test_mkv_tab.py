from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_io import SubtitleTrack, TemplateExtraction
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


def test_open_select_dialog_applies_the_chosen_keys(qapp, monkeypatch):
    """實際走 _open_select_dialog:對話框接受後,選定的鍵要真的落進 _track_keys。"""
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)

    class FakeDialog:
        def __init__(self, available, existing, parent):
            self.available = available
            self.existing = existing

        def exec(self):
            return 1

        def get_keys(self):
            return {("chi", "繁中")}

    monkeypatch.setattr("ass_style_tool.qt.mkv_tab.SelectTracksDialog", FakeDialog)
    tab._open_select_dialog()
    assert tab._track_keys == {("chi", "繁中")}
    assert tab.modify_tracks_button.text() == "修改既有軌道…(已選 1 條)"


def test_reopening_dialog_preserves_keys_the_new_template_cannot_show(qapp, monkeypatch):
    """回歸(最終審查抓到的真實 bug):換範本檔(取消勾選某檔)後重開對話框,
    對話框只能顯示/切換新範本檔本身有的鍵——舊規則裡新範本檔沒有的鍵,
    對話框無從呈現,絕不能因為重開一次就被靜默清掉。

    同時驗證:新範本檔 CAN 顯示但使用者這次未選的鍵,必須被清掉(不能只因為
    它以前在 _track_keys 裡就保留)。"""
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)
    # e1(範本檔,繁中/简中)先被取消勾選;e2(简中/繁中)變成新範本檔。
    tab.file_table.item(0, 0).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Unchecked)
    # 初始規則:三個鍵
    # - ("chi", "繁中"): e2 CAN 顯示,但使用者這次不勾 → 必須被清掉
    # - ("chi", "简中"): e2 CAN 顯示,使用者會勾 → 保留
    # - ("jpn", ""): e2 無法顯示 → 保留
    tab._track_keys = {("chi", "繁中"), ("chi", "简中"), ("jpn", "")}

    class FakeDialog:
        def __init__(self, available, existing, parent):
            self.available = available

        def exec(self):
            return 1

        def get_keys(self):
            # 使用者在對話框裡看到的只有範本檔(e2)本身的鍵,只勾了簡中
            return {("chi", "简中")}

    monkeypatch.setattr("ass_style_tool.qt.mkv_tab.SelectTracksDialog", FakeDialog)
    tab._open_select_dialog()
    # 驗證三個行為:
    # 1. ("chi", "简中") 保留(使用者選了)
    # 2. ("jpn", "") 保留(範本檔顯示不出來)
    # 3. ("chi", "繁中") 被清掉(範本檔能顯示,但使用者沒選)
    assert tab._track_keys == {("chi", "简中"), ("jpn", "")}


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
    # Task 9:「開始處理」在套用樣式模式下還要求側欄至少勾選一個目標樣式
    # (不然按下去也找不到要改哪個 Style),跟字幕檔/封裝分頁同一套語意。
    tab.style_picker.set_available(["Default"])
    tab.style_picker.set_selected(["Default"])
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


def test_read_styles_button_disabled_when_tools_missing(qapp, monkeypatch):
    tab = _tab(monkeypatch, available=False)
    assert tab.read_styles_button.isEnabled() is False


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


def test_shutdown_waits_for_template_thread(qapp, monkeypatch):
    """讀取樣式名稱進行中關閉分頁時,shutdown() 要等 _template_thread
    收尾(quit + wait),不能留著一條沒人管的執行緒——這條執行緒沒有
    cancel() 可呼叫(見 TemplateStyleWorker 的說明:單一子行程呼叫沒有
    中途檢查點可以插),shutdown() 只需要負責等它,不必也不能取消它。"""
    from unittest.mock import Mock
    tab = _tab(monkeypatch)
    thread, worker = Mock(), Mock()
    tab._template_thread = thread
    tab._template_worker = worker

    tab.shutdown()

    # 先留住 Mock 參照再呼叫:shutdown() 收尾時會把這兩個欄位放掉
    # (見 test_shutdown_clears_template_references),不能等它跑完才從
    # tab 上取。
    thread.quit.assert_called_once()
    thread.wait.assert_called_once()
    # 沒有 cancel() 可呼叫,shutdown() 也真的沒去呼叫它
    worker.cancel.assert_not_called()


def test_shutdown_without_template_thread_does_not_raise(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab._template_thread is None
    tab.shutdown()          # 不應拋例外


def test_template_styles_done_ignored_after_closing(qapp, monkeypatch):
    """shutdown() 對 _template_thread 呼叫 wait() 之後,worker 排隊的
    finished 訊號會在下一輪事件迴圈才送達分頁——這時分頁可能已經在銷毀
    路上,_on_template_styles_done() 不能在這個時間點還去碰
    read_styles_button/style_picker/log 這些元件。"""
    from unittest.mock import Mock
    from ass_style_tool.mkv_io import TemplateExtraction
    from ass_style_tool.qt.batch_worker import TemplateStyleResult
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._template_thread = Mock()
    tab._template_worker = Mock()
    tab.read_styles_button.setEnabled(False)   # 模擬讀取仍在進行中的狀態
    tab._closing = True

    messages = []
    tab.log.connect(messages.append)
    tab._on_template_styles_done(
        TemplateStyleResult(extraction=TemplateExtraction(path=None,
                                                           error="no_track")))

    assert messages == []                              # 沒有任何 log
    assert tab.read_styles_button.isEnabled() is False  # 沒有被重新啟用
    assert tab._template_thread is not None             # 沒有被清空
    tab._template_thread.quit.assert_not_called()       # 也沒有去動這條執行緒


# ---------- 範本檔樣式讀取 ----------

def _drive_read_template_styles(tab, qapp, monkeypatch, *,
                                extract_fn=None, scan_fn=None):
    """呼叫 tab.read_template_styles() 並跑完真正的 QThread + TemplateStyleWorker。

    抽取(mkvmerge -J + mkvextract)+ 解析已經搬進背景執行緒跑(最終審查
    I8),不再是 read_template_styles() 這個 slot 裡的同步呼叫——跟
    MkvScanWorker 既有的測試手法一樣:monkeypatch 掉分頁自己拿來建構
    worker 的那個名字(這裡是 TemplateStyleWorker),用同樣的呼叫簽章包一
    層 factory,把假的 extract_fn/scan_fn 注入到真正的 worker 類別裡,
    而不是 monkeypatch 早就在模組載入時就綁定死的預設參數(那樣不會有
    任何效果)。"""
    import time
    from ass_style_tool.qt.batch_worker import TemplateStyleWorker

    def factory(mkv_path, mkvmerge, mkvextract, out_dir):
        kwargs = {}
        if extract_fn is not None:
            kwargs["extract_fn"] = extract_fn
        if scan_fn is not None:
            kwargs["scan_fn"] = scan_fn
        return TemplateStyleWorker(mkv_path, mkvmerge, mkvextract, out_dir,
                                   **kwargs)

    monkeypatch.setattr("ass_style_tool.qt.mkv_tab.TemplateStyleWorker",
                        factory)
    tab.read_template_styles()
    deadline = time.monotonic() + 5.0
    while tab._template_thread is not None and time.monotonic() < deadline:
        qapp.processEvents()
    assert tab._template_thread is None, "read_template_styles 沒有跑完"


def test_read_template_styles_fills_picker(qapp, monkeypatch, tmp_path):
    from ass_style_tool.style_scan import FileStyles
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    _drive_read_template_styles(
        tab, qapp, monkeypatch,
        extract_fn=lambda mkv, mkvmerge, mkvextract, out_dir:
            TemplateExtraction(path=tmp_path / "t.ass"),
        scan_fn=lambda path:
            FileStyles(path, {"Default": 48.0, "CHT": 52.0}))
    from PySide6.QtCore import Qt
    names = [tab.style_picker.list.item(i).data(Qt.ItemDataRole.UserRole)
             for i in range(tab.style_picker.list.count())]
    assert sorted(names) == ["CHT", "Default"]


def test_read_template_styles_reports_no_text_track(qapp, monkeypatch):
    """真的沒有 ASS/SSA 字幕軌(可能是 PGS/VobSub)——訊息要指向「這批影片
    沒有文字字幕軌」,不能跟抽取失敗混為一談(見下面的
    test_read_template_styles_reports_extraction_failure)。"""
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    messages = []
    tab.log.connect(messages.append)
    _drive_read_template_styles(
        tab, qapp, monkeypatch,
        extract_fn=lambda mkv, mkvmerge, mkvextract, out_dir:
            TemplateExtraction(path=None, error="no_track"))
    assert any("沒有文字字幕軌" in m for m in messages)
    # 不能同時冒出「抽取失敗」的措辭,兩種情況的訊息必須是互斥的。
    assert not any("失敗" in m for m in messages)


def test_read_template_styles_no_text_track_message_names_the_first_file_only(
        qapp, monkeypatch):
    """Minor bullet:read_template_styles() 只抽 files[0] 當範本,不逐檔
    確認——訊息原本講『這批影片沒有文字字幕軌』,會讓人誤以為整批都被
    檢查過,其實後面的檔案根本沒被碰過。這裡釘住訊息要點名第一個檔案,
    且明講其餘影片未被檢查,不能誇大成整批的結論。"""
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    messages = []
    tab.log.connect(messages.append)
    _drive_read_template_styles(
        tab, qapp, monkeypatch,
        extract_fn=lambda mkv, mkvmerge, mkvextract, out_dir:
            TemplateExtraction(path=None, error="no_track"))
    assert any(FILES[0].name in m and "其餘影片未逐一確認" in m
              for m in messages)


def test_read_template_styles_reports_unknown_reason_honestly(qapp, monkeypatch):
    """最終審查 Minor:三個已知原因(no_track/extract_failed/
    identify_failed)都比對過還落到 else 分支,代表出現了目前沒處理過的
    新原因——這裡不能像原本那樣把它冒充成「確認過沒有字幕軌」(跟 I9 是
    同一種錯,只是換了一層),要老實講出原因字串。"""
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    messages = []
    tab.log.connect(messages.append)
    _drive_read_template_styles(
        tab, qapp, monkeypatch,
        extract_fn=lambda mkv, mkvmerge, mkvextract, out_dir:
            TemplateExtraction(path=None, error="some_future_reason"))
    assert any("some_future_reason" in m for m in messages)
    assert not any("沒有文字字幕軌" in m for m in messages)


def test_read_template_styles_reports_identify_failure(qapp, monkeypatch):
    """連 mkvmerge -J 都沒能成功問出這個檔案有哪些軌(逾時/損毀/被占用/
    mkvmerge 當掉)——根本不知道有沒有字幕軌,不能講成「確認過沒有」
    (那會把使用者導去查圖形字幕,但真正的原因可能是檔案損毀或
    MKVToolNix 本身出問題),也不能跟「軌道存在但抽取失敗」混為一談。"""
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    messages = []
    tab.log.connect(messages.append)
    _drive_read_template_styles(
        tab, qapp, monkeypatch,
        extract_fn=lambda mkv, mkvmerge, mkvextract, out_dir:
            TemplateExtraction(path=None, error="identify_failed"))
    assert any("無法讀取" in m and "字幕軌清單" in m for m in messages)
    assert not any("沒有文字字幕軌" in m for m in messages)
    assert not any("抽取" in m and "失敗" in m for m in messages)


def test_read_template_styles_reports_extraction_failure(qapp, monkeypatch):
    """軌道存在,但 mkvextract 抽取失敗(壞檔/磁碟空間/權限…)——訊息要
    講「抽取失敗」,不能說成「沒有文字字幕軌」,否則使用者會被導去檢查
    根本不存在的問題(圖形字幕),而錯過真正的原因。"""
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    messages = []
    tab.log.connect(messages.append)
    _drive_read_template_styles(
        tab, qapp, monkeypatch,
        extract_fn=lambda mkv, mkvmerge, mkvextract, out_dir:
            TemplateExtraction(path=None, error="extract_failed"))
    assert any("失敗" in m for m in messages)
    # 不能同時冒出「沒有文字字幕軌」的措辭,兩種情況的訊息必須是互斥的。
    assert not any("沒有文字字幕軌" in m for m in messages)


def test_read_template_styles_uses_the_first_file(qapp, monkeypatch, tmp_path):
    """範本只抽第一個檔案,不是逐檔抽——這正是這個分頁跟其他兩個分頁最大
    的不同(其他分頁讀外部 .ass 是毫秒級,這裡抽字幕軌要跑 mkvextract,
    整季抽一輪太慢)。"""
    from ass_style_tool.style_scan import FileStyles
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    seen = []

    def fake_extract(mkv, mkvmerge, mkvextract, out_dir):
        seen.append(mkv)
        return TemplateExtraction(path=tmp_path / "t.ass")

    _drive_read_template_styles(
        tab, qapp, monkeypatch, extract_fn=fake_extract,
        scan_fn=lambda path: FileStyles(path, {"Default": 48.0}))
    assert seen == [FILES[0]]


def test_read_template_styles_passes_the_tracked_temp_dir(qapp, monkeypatch, tmp_path):
    """範本檔要寫進分頁自己會清理的暫存目錄(_preview_dir),不是系統暫存
    目錄——否則每次讀樣式名稱都會在 %TEMP% 底下多留一個檔案,永遠沒人清
    (見 shutdown() 對 _preview_dir 的 rmtree)。"""
    from ass_style_tool.style_scan import FileStyles
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    seen_dirs = []

    def fake_extract(mkv, mkvmerge, mkvextract, out_dir):
        seen_dirs.append(out_dir)
        return TemplateExtraction(path=tmp_path / "t.ass")

    _drive_read_template_styles(
        tab, qapp, monkeypatch, extract_fn=fake_extract,
        scan_fn=lambda path: FileStyles(path, {"Default": 48.0}))
    assert seen_dirs == [tab._preview_dir]
    tab.shutdown()


def test_read_template_styles_requires_a_scanned_folder(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    messages = []
    tab.log.connect(messages.append)
    tab.read_template_styles()
    assert any("請先掃描資料夾" in m for m in messages)


def test_read_template_styles_reports_tools_missing(qapp, monkeypatch):
    tab = _tab(monkeypatch, available=False)
    tab.populate(FILES)
    messages = []
    tab.log.connect(messages.append)
    tab.read_template_styles()
    assert any("找不到 MKVToolNix" in m for m in messages)


def test_read_template_styles_disables_button_while_running(qapp, monkeypatch):
    """最終審查 I8:抽取+解析原本直接在這個 slot 裡同步跑,最多 360 秒的
    子行程逾時會讓視窗整個「沒有回應」。搬到背景執行緒後,至少要讓使用者
    看得出「正在讀取」——按鈕在 worker 還沒 emit finished 之前必須是停用
    的,而不是靜靜地卡住看起來像沒反應。"""
    import time
    from ass_style_tool.qt.batch_worker import TemplateStyleWorker

    release = {"go": False}

    def slow_extract(mkv, mkvmerge, mkvextract, out_dir):
        # 模擬子行程還在跑:worker 執行緒等到測試主動放行才回傳,
        # 讓測試有機會在「執行中」這個時間點檢查按鈕狀態。
        deadline = time.monotonic() + 5.0
        while not release["go"] and time.monotonic() < deadline:
            time.sleep(0.01)
        return TemplateExtraction(path=None, error="no_track")

    def factory(mkv_path, mkvmerge, mkvextract, out_dir):
        return TemplateStyleWorker(mkv_path, mkvmerge, mkvextract, out_dir,
                                   extract_fn=slow_extract)

    tab = _tab(monkeypatch)
    tab.populate(FILES)
    monkeypatch.setattr("ass_style_tool.qt.mkv_tab.TemplateStyleWorker",
                        factory)

    assert tab.read_styles_button.isEnabled() is True
    tab.read_template_styles()
    assert tab.read_styles_button.isEnabled() is False, (
        "worker 還在跑(release 還沒放行),按鈕應該維持停用")

    release["go"] = True
    deadline = time.monotonic() + 5.0
    while tab._template_thread is not None and time.monotonic() < deadline:
        qapp.processEvents()

    assert tab._template_thread is None, "read_template_styles 沒有跑完"
    assert tab.read_styles_button.isEnabled() is True


def test_read_template_styles_ignores_click_while_already_running(
        qapp, monkeypatch):
    """讀取進行中再按一次按鈕不該再開一條執行緒(那會讓兩個 worker 同時
    寫 self._template_video_name,結果錯亂),只提示使用者稍候。"""
    import time
    from ass_style_tool.qt.batch_worker import TemplateStyleWorker

    release = {"go": False}

    def slow_extract(mkv, mkvmerge, mkvextract, out_dir):
        deadline = time.monotonic() + 5.0
        while not release["go"] and time.monotonic() < deadline:
            time.sleep(0.01)
        return TemplateExtraction(path=None, error="no_track")

    def factory(mkv_path, mkvmerge, mkvextract, out_dir):
        return TemplateStyleWorker(mkv_path, mkvmerge, mkvextract, out_dir,
                                   extract_fn=slow_extract)

    tab = _tab(monkeypatch)
    tab.populate(FILES)
    monkeypatch.setattr("ass_style_tool.qt.mkv_tab.TemplateStyleWorker",
                        factory)
    messages = []
    tab.log.connect(messages.append)

    tab.read_template_styles()
    first_thread = tab._template_thread
    tab.read_template_styles()          # 讀取進行中,再點一次

    assert tab._template_thread is first_thread    # 沒有另外開一條執行緒
    assert any("請稍候" in m for m in messages)

    release["go"] = True
    deadline = time.monotonic() + 5.0
    while tab._template_thread is not None and time.monotonic() < deadline:
        qapp.processEvents()
    assert tab._template_thread is None, "read_template_styles 沒有跑完"


def test_read_template_styles_reports_parse_error(qapp, monkeypatch, tmp_path):
    from ass_style_tool.style_scan import FileStyles
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    messages = []
    tab.log.connect(messages.append)
    _drive_read_template_styles(
        tab, qapp, monkeypatch,
        extract_fn=lambda mkv, mkvmerge, mkvextract, out_dir:
            TemplateExtraction(path=tmp_path / "t.ass"),
        scan_fn=lambda path: FileStyles(path, error="壞檔"))
    assert any("壞檔" in m for m in messages)


def test_current_files_returns_the_listed_videos(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    assert tab.current_files() == FILES


# ---------- effective_profile ----------

def test_effective_profile_uses_picker_selection(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.style_picker.set_available(["CHT"])
    tab.style_picker.set_selected(["CHT"])
    assert tab.effective_profile().target_style_names == ["CHT"]


# ---------- 目標樣式:可見度與執行鈕依模式而定(防重複出現的缺陷) ----------
#
# 這個坑在字幕檔分頁跟封裝分頁都各自出現過一次:控件或啟用閘門沒有依
# 操作模式設置,導致「縮放字級」模式下依然顯示/要求一個它根本不會讀
# 的目標樣式勾選(縮放走 scale_panel.get_options(),完全不看
# style_picker)。這裡照封裝分頁(mux_tab.py)最終採用的作法——不只是
# 執行鈕的啟用條件要看模式,樣式清單本身在縮放模式下要整組隱藏,不然
# 使用者會誤以為勾選有作用。

def test_style_group_visible_in_apply_mode_by_default(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.apply_mode_radio.isChecked() is True
    assert tab.style_group.isHidden() is False


def test_style_group_hidden_in_scale_mode(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.scale_mode_radio.setChecked(True)
    assert tab.style_group.isHidden() is True


def test_style_group_shown_again_after_switching_back_to_apply_mode(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.scale_mode_radio.setChecked(True)
    assert tab.style_group.isHidden() is True
    tab.apply_mode_radio.setChecked(True)
    assert tab.style_group.isHidden() is False


def test_run_button_disabled_in_apply_mode_without_styles(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    assert tab.run_button.isEnabled() is False


def test_run_button_enabled_in_apply_mode_with_styles(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab.style_picker.set_available(["CHT"])
    tab.style_picker.set_selected(["CHT"])
    assert tab.run_button.isEnabled() is True


def test_run_button_enabled_in_scale_mode_without_styles(qapp, monkeypatch):
    """縮放模式不吃側欄的目標樣式勾選,只看有沒有檔案可跑。"""
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab.scale_mode_radio.setChecked(True)
    assert tab.run_button.isEnabled() is True


def test_run_button_rechecks_styles_after_switching_back_to_apply_mode(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab.scale_mode_radio.setChecked(True)
    assert tab.run_button.isEnabled() is True
    tab.apply_mode_radio.setChecked(True)
    assert tab.run_button.isEnabled() is False   # 套用模式下還沒勾任何樣式


def test_run_button_reacts_to_style_picker_changed_signal(qapp, monkeypatch):
    """style_picker 勾選變動要即時反映到執行鈕,不必等下一次 populate。"""
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab.style_picker.set_available(["CHT", "Default"])
    assert tab.run_button.isEnabled() is False
    tab.style_picker.set_selected(["CHT"])
    assert tab.run_button.isEnabled() is True
    tab.style_picker.set_selected([])
    assert tab.run_button.isEnabled() is False


# ---------- 設定持久化:目標樣式 ----------

def test_save_and_restore_settings_roundtrip_includes_styles(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab_a = _tab(monkeypatch)
    tab_a.style_picker.set_available(["CHT", "Default"])
    tab_a.style_picker.set_selected(["CHT", "Default"])
    tab_a.save_settings(settings)

    tab_b = _tab(monkeypatch)
    tab_b.restore_settings(settings)
    assert sorted(tab_b.style_picker.selected()) == ["CHT", "Default"]


def test_save_and_restore_settings_roundtrip_single_style_does_not_degrade(
        qapp, monkeypatch, tmp_path):
    """QSettings 存單元素清單時容易退化成裸字串,還原時要補救回清單。"""
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab_a = _tab(monkeypatch)
    tab_a.style_picker.set_available(["CHT"])
    tab_a.style_picker.set_selected(["CHT"])
    tab_a.save_settings(settings)

    tab_b = _tab(monkeypatch)
    tab_b.restore_settings(settings)
    assert tab_b.style_picker.selected() == ["CHT"]


# ---------- Task 10: 「結果」欄(MKV 分頁沒有逐檔預告,只有結果) ----------

def test_result_column_header_label(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.file_table.horizontalHeaderItem(2).text() == "結果"


def test_result_column_resize_mode_does_not_elide_text(qapp, monkeypatch):
    """Minor bullet:「結果」欄跟另外兩個分頁的「預計 / 結果」欄一樣,
    要有 resize 政策,不然長文字(例如「✗ 失敗」以外還有訊息時)會被
    裁到剩幾個字。"""
    from PySide6.QtWidgets import QHeaderView
    tab = _tab(monkeypatch)
    assert (tab.file_table.horizontalHeader().sectionResizeMode(2)
           == QHeaderView.ResizeToContents)


def test_result_column_blank_after_populate(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    assert [tab.file_table.item(r, 2).text() for r in range(3)] == ["", "", ""]


def test_mark_rows_pending_sets_processing_text(qapp, monkeypatch):
    """Task 10 review Finding 1:只有目前規則下真的解析出至少一條軌道、
    會被這批工作處理的檔案(跟 current_jobs() 同一套判斷)會換成
    「處理中…」;e3 在 TRACKS 裡沒有任何軌道,不屬於這批工作,必須維持
    原狀。"""
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)
    before_e3 = tab.file_table.item(2, 2).text()
    tab.mark_rows_pending()
    assert tab.file_table.item(0, 2).text() == "處理中…"
    assert tab.file_table.item(1, 2).text() == "處理中…"
    assert tab.file_table.item(2, 2).text() == before_e3


def test_set_row_result_replaces_cell(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)
    tab.mark_rows_pending()
    tab._set_row_result("e1.mkv", "ok")
    assert "✓" in tab.file_table.item(0, 2).text()


def test_run_to_completion_reconciles_job_rows_and_preserves_others(
        qapp, monkeypatch):
    """Task 10 review Finding 1:e3 在 TRACKS 裡沒有任何軌道,current_jobs()
    本來就不會排進它——批次跑到底之後,e3 那一列不能被誤標成「處理
    中…」,也不能在跑完之後留在「處理中…」;真正在這批工作裡的 e1/e2
    則要拿到各自的結果(混合 ok/error)。驅動真正的 MkvWorker(注入假
    process_fn,不呼叫外部 mkvmerge),監聽它的 file_done/finished
    signal,不是逐列手動呼叫 _set_row_result。"""
    from ass_style_tool.mkv_batch import MkvFileReport
    from ass_style_tool.qt.batch_worker import MkvWorker

    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)
    before_e3 = tab.file_table.item(2, 2).text()

    jobs = tab.current_jobs()
    assert [p.name for p, _ in jobs] == ["e1.mkv", "e2.mkv"]

    reports = {
        Path("e1.mkv"): MkvFileReport(Path("e1.mkv"), "ok"),
        Path("e2.mkv"): MkvFileReport(Path("e2.mkv"), "error"),
    }

    def fake_process(mkv_path, tracks, operation, tools, out_path=None,
                     progress_cb=None):
        return reports[mkv_path]

    tab.mark_rows_pending()
    assert tab.file_table.item(0, 2).text() == "處理中…"
    assert tab.file_table.item(1, 2).text() == "處理中…"
    # 沒有任何可套用軌道、不屬於這批工作的列維持原狀
    assert tab.file_table.item(2, 2).text() == before_e3

    worker = MkvWorker(jobs, tab.effective_profile(), tab._tools,
                       output_dir=None, process_fn=fake_process)
    worker.file_done.connect(tab._set_row_result)
    worker.finished.connect(tab._on_finished)
    worker.run()

    assert tab.file_table.item(0, 2).text() == "✓ 已套用"
    assert tab.file_table.item(1, 2).text() == "✗ 失敗"
    assert tab.file_table.item(2, 2).text() == before_e3


def test_cancelled_run_reconciles_remaining_rows(qapp, monkeypatch):
    """Task 10 review Finding 2:取消處理時 MkvWorker.run() 一偵測到取消
    旗標就直接 break,還沒輪到的檔案不會發出 file_done。這裡驅動真正的
    worker,在第一個檔案完成後立刻取消,確認排在後面、從未被處理過的列
    不會卡在「處理中…」。"""
    from ass_style_tool.mkv_batch import MkvFileReport
    from ass_style_tool.qt.batch_worker import MkvWorker

    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)
    jobs = tab.current_jobs()
    assert len(jobs) == 2   # e1, e2(e3 沒有任何軌道)

    def fake_process(mkv_path, tracks, operation, tools, out_path=None,
                     progress_cb=None):
        return MkvFileReport(mkv_path, "ok")

    tab.mark_rows_pending()

    worker = MkvWorker(jobs, tab.effective_profile(), tab._tools,
                       output_dir=None, process_fn=fake_process)
    worker.file_done.connect(tab._set_row_result)
    # 模擬使用者在第一個檔案完成後立刻按下取消
    worker.file_done.connect(lambda name, status: worker.cancel())
    worker.finished.connect(tab._on_finished)
    worker.run()

    assert tab.file_table.item(0, 2).text() == "✓ 已套用"
    assert tab.file_table.item(1, 2).text() != "處理中…"


def test_rescan_restores_blank_result_column(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab.mark_rows_pending()
    tab._set_row_result("e1.mkv", "error")
    assert tab.file_table.item(0, 2).text() != ""
    tab.populate(FILES)      # 重新列出 == 重新掃描的等效路徑
    assert tab.file_table.item(0, 2).text() == ""


# ---------- 最終審查 Minor:讀取樣式名稱與掃描的互斥、shutdown 收尾 ----------

def test_scan_blocked_while_template_read_in_flight(qapp, monkeypatch):
    """讀取樣式名稱搬到背景執行緒之後,GUI 不再被卡住,使用者因此有機會
    在讀取途中按重新掃描/換資料夾。若放行,_on_template_styles_done()
    會拿一個已經不在目前清單裡的影片抽到的樣式去填 style_picker。"""
    from unittest.mock import Mock
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._template_thread = Mock()
    messages = []
    tab.log.connect(messages.append)

    tab._on_scan()

    assert any("正在讀取樣式名稱" in m for m in messages)
    assert tab._scan_thread is None          # 沒有真的開掃描


def test_auto_scan_skipped_while_template_read_in_flight(qapp, monkeypatch,
                                                         tmp_path):
    """_auto_scan 的忙碌判斷也要含 _template_thread,跟 _on_scan 一致。"""
    from unittest.mock import Mock
    tab = _tab(monkeypatch)
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab.folder_edit.setText(str(tmp_path))
    tab._template_thread = Mock()

    tab._auto_scan()

    assert calls == []


def test_shutdown_clears_template_references(qapp, monkeypatch):
    """_closing 會讓 _on_template_styles_done() 提早 return,那條路徑的
    收尾不會執行——shutdown() 要自己把參照放掉,不要留著一個已經 quit()
    +wait() 過的 QThread 與它的 worker(跟 _finish_scan() 對掃描 worker
    做的事同一個道理)。"""
    from unittest.mock import Mock
    tab = _tab(monkeypatch)
    tab._template_thread = Mock()
    tab._template_worker = Mock()

    tab.shutdown()

    assert tab._template_thread is None
    assert tab._template_worker is None


# ---------- 送進預覽:抽取搬到背景執行緒(最終審查,I8 同類缺陷) ----------

def _drive_send_preview(tab, qapp, monkeypatch, *, extract_fn=None):
    """呼叫 tab._on_send_preview() 並跑完真正的 QThread + PreviewExtractWorker。

    跟 _drive_read_template_styles() 同一個理由:extract_fn 是 worker 的
    預設參數,在模組載入時就綁定死了,test 時 monkeypatch 模組層級的
    函式名稱不會有任何效果,要用同一套「monkeypatch 掉分頁拿來建構
    worker 的那個名字,factory 包一層注入假函式」的手法。"""
    import time
    from ass_style_tool.qt.batch_worker import PreviewExtractWorker

    def factory(mkv_path, track_id, out_path, mkvextract):
        kwargs = {}
        if extract_fn is not None:
            kwargs["extract_fn"] = extract_fn
        return PreviewExtractWorker(mkv_path, track_id, out_path, mkvextract,
                                    **kwargs)

    monkeypatch.setattr("ass_style_tool.qt.mkv_tab.PreviewExtractWorker",
                        factory)
    tab._on_send_preview()
    deadline = time.monotonic() + 5.0
    while tab._preview_extract_thread is not None and time.monotonic() < deadline:
        qapp.processEvents()
    assert tab._preview_extract_thread is None, "_on_send_preview 沒有跑完"


def test_send_preview_requires_a_selected_file(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    messages = []
    tab.log.connect(messages.append)
    tab._on_send_preview()
    assert any("請先選取一個 MKV 檔" in m for m in messages)
    assert tab._preview_extract_thread is None


def test_send_preview_requires_scanned_tracks(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab.file_table.setCurrentCell(0, 0)
    messages = []
    tab.log.connect(messages.append)
    tab._on_send_preview()
    assert any("還沒掃過字幕軌" in m for m in messages)
    assert tab._preview_extract_thread is None


def test_send_preview_requires_matching_tracks(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)
    tab._track_keys = {("jpn", "")}      # 三個檔都沒有這個鍵
    tab.file_table.setCurrentCell(0, 0)
    messages = []
    tab.log.connect(messages.append)
    tab._on_send_preview()
    assert any("沒有符合目前選擇的字幕軌" in m for m in messages)
    assert tab._preview_extract_thread is None


def test_send_preview_emits_signal_on_success(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)
    tab.file_table.setCurrentCell(0, 0)     # e1.mkv,軌 2/3 都符合(無規則)

    seen = []
    tab.preview_requested.connect(lambda temp, path: seen.append((temp, path)))

    _drive_send_preview(
        tab, qapp, monkeypatch,
        extract_fn=lambda mkv, track_id, out_path, mkvextract: True)

    assert len(seen) == 1
    temp, path = seen[0]
    assert path == Path("e1.mkv")
    assert temp == tab._preview_dir / "e1_track2.ass"   # 永遠選第一條
    assert tab.preview_button.isEnabled() is True


def test_send_preview_reports_extraction_failure(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)
    tab.file_table.setCurrentCell(0, 0)
    messages = []
    tab.log.connect(messages.append)
    seen = []
    tab.preview_requested.connect(lambda temp, path: seen.append(1))

    _drive_send_preview(
        tab, qapp, monkeypatch,
        extract_fn=lambda mkv, track_id, out_path, mkvextract: False)

    assert any("抽取軌 2 失敗" in m for m in messages)
    assert seen == []                          # 失敗不能送進預覽
    assert tab.preview_button.isEnabled() is True


def test_send_preview_reports_worker_exception(qapp, monkeypatch):
    """最終審查已在 TemplateStyleWorker 上付過的學費:worker 裡未預期的
    例外若沒被接住,finished 永遠不會發出,按鈕就永久卡死——這裡直接在
    設計階段就補上同一道防護,不是等 review 抓到才修。"""
    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)
    tab.file_table.setCurrentCell(0, 0)
    messages = []
    tab.log.connect(messages.append)

    def boom(mkv, track_id, out_path, mkvextract):
        raise OSError("磁碟已滿")

    _drive_send_preview(tab, qapp, monkeypatch, extract_fn=boom)

    assert any("抽取軌 2 失敗" in m and "磁碟已滿" in m for m in messages)
    assert tab.preview_button.isEnabled() is True


def test_send_preview_ignores_click_while_already_running(qapp, monkeypatch):
    import time
    from ass_style_tool.qt.batch_worker import PreviewExtractWorker

    release = {"go": False}

    def slow_extract(mkv, track_id, out_path, mkvextract):
        deadline = time.monotonic() + 5.0
        while not release["go"] and time.monotonic() < deadline:
            time.sleep(0.01)
        return True

    def factory(mkv_path, track_id, out_path, mkvextract):
        return PreviewExtractWorker(mkv_path, track_id, out_path, mkvextract,
                                    extract_fn=slow_extract)

    tab = _tab(monkeypatch)
    tab.populate(FILES)
    tab._files_tracks = dict(TRACKS)
    tab.file_table.setCurrentCell(0, 0)
    monkeypatch.setattr("ass_style_tool.qt.mkv_tab.PreviewExtractWorker",
                        factory)
    messages = []
    tab.log.connect(messages.append)

    tab._on_send_preview()
    first_thread = tab._preview_extract_thread
    assert tab.preview_button.isEnabled() is False
    tab._on_send_preview()          # 抽取進行中,再點一次

    assert tab._preview_extract_thread is first_thread
    assert any("請稍候" in m for m in messages)

    release["go"] = True
    deadline = time.monotonic() + 5.0
    while tab._preview_extract_thread is not None and time.monotonic() < deadline:
        qapp.processEvents()
    assert tab._preview_extract_thread is None


def test_preview_extract_done_ignored_after_closing(qapp, monkeypatch):
    from unittest.mock import Mock
    from ass_style_tool.qt.batch_worker import PreviewExtractResult
    tab = _tab(monkeypatch)
    tab._preview_extract_thread = Mock()
    tab._preview_extract_worker = Mock()
    tab.preview_button.setEnabled(False)
    tab._closing = True

    messages = []
    tab.log.connect(messages.append)
    seen = []
    tab.preview_requested.connect(lambda temp, path: seen.append(1))

    tab._on_preview_extract_done(PreviewExtractResult(
        mkv_path=Path("e1.mkv"), track_id=2, out_path=Path("t.ass"),
        success=True))

    assert messages == []
    assert seen == []
    assert tab.preview_button.isEnabled() is False
    assert tab._preview_extract_thread is not None


def test_shutdown_waits_for_preview_extract_thread(qapp, monkeypatch):
    from unittest.mock import Mock
    tab = _tab(monkeypatch)
    thread, worker = Mock(), Mock()
    tab._preview_extract_thread = thread
    tab._preview_extract_worker = worker

    tab.shutdown()

    thread.quit.assert_called_once()
    thread.wait.assert_called_once()
    assert tab._preview_extract_thread is None
    assert tab._preview_extract_worker is None
