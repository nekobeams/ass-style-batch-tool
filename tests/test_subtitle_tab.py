from __future__ import annotations

from pathlib import Path

from ass_style_tool.batch_runner import ScanResult
from ass_style_tool.episode_match import MatchResult
from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values


def _scan():
    return ScanResult(matches=[
        MatchResult(sub_path=Path("a [01].ass"), episode=1,
                    video_path=Path("v01.mkv"), status="matched"),
        MatchResult(sub_path=Path("b [02].ass"), episode=2,
                    video_path=None, status="no_video"),
    ], warnings=[])


def _tab():
    from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    return SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))


def test_populate_preview_fills_table(qapp):
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    n = tab.populate_preview(_scan())
    assert n == 2
    assert tab.table.rowCount() == 2
    # 第一列的字幕檔名欄位
    assert tab.table.item(0, 1).text() == "a [01].ass"


def test_run_button_disabled_until_scan(qapp):
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    assert tab.run_button.isEnabled() is False
    # Task 6:「開始套用樣式」現在還要求側欄至少勾選一個目標樣式
    # (不然按下去也找不到要改哪個 Style)。populate_preview 才會重新
    # 判斷按鈕是否可按,所以要選在呼叫它之前。
    tab.style_picker.set_available(["Default"])
    tab.style_picker.set_selected(["Default"])
    tab.populate_preview(_scan())
    assert tab.run_button.isEnabled() is True


def test_batch_worker_runs_and_reports(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import BatchWorker
    from tests.test_ass_style import SAMPLE_ASS
    sub = tmp_path / "a [01].ass"
    sub.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    scan = ScanResult(matches=[
        MatchResult(sub_path=sub, episode=1, status="no_video"),
    ], warnings=[])
    profile = profile_from_values(DEFAULT_VALUES)
    worker = BatchWorker(scan, profile, output_dir=tmp_path / "out")
    seen = []
    worker.file_done.connect(lambda name, status: seen.append((name, status)))
    results = {}
    worker.finished.connect(
        lambda ok, sk, er: results.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert results == {"ok": 1, "skipped": 0, "error": 0}
    assert seen == [("a [01].ass", "ok")]
    assert (tmp_path / "out" / "a [01].ass").exists()


def test_batch_worker_cancel_stops_early(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import BatchWorker
    from tests.test_ass_style import SAMPLE_ASS
    matches = []
    for i in (1, 2, 3):
        sub = tmp_path / f"a [{i:02d}].ass"
        sub.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
        matches.append(MatchResult(sub_path=sub, episode=i, status="no_video"))
    scan = ScanResult(matches=matches, warnings=[])
    profile = profile_from_values(DEFAULT_VALUES)
    worker = BatchWorker(scan, profile, output_dir=tmp_path / "out")
    # 第一個檔完成後就取消
    worker.file_done.connect(lambda name, status: worker.cancel())
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    # 取消後總處理數應少於 3
    assert done["ok"] < 3


def test_batch_worker_output_dir_collision(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import BatchWorker
    from tests.test_ass_style import SAMPLE_ASS
    a = tmp_path / "a [01].ass"
    a.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    nested = tmp_path / "nested"
    nested.mkdir()
    b = nested / "a [01].ass"
    b.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    scan = ScanResult(matches=[
        MatchResult(sub_path=a, episode=1, status="no_video"),
        MatchResult(sub_path=b, episode=1, status="no_video"),
    ], warnings=[])
    worker = BatchWorker(scan, profile_from_values(DEFAULT_VALUES),
                         output_dir=tmp_path / "out")
    statuses = []
    worker.file_done.connect(lambda n, s: statuses.append(s))
    worker.run()
    assert statuses == ["ok", "error"]  # 第二個同名 → 衝突


def test_scan_worker_emits_result(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import ScanWorker
    from tests.test_ass_style import SAMPLE_ASS
    (tmp_path / "a [01].ass").write_bytes(
        b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    worker = ScanWorker(tmp_path)
    got = {}
    worker.finished.connect(lambda scan: got.update(n=len(scan.matches)))
    worker.run()
    assert got["n"] == 1


def test_preview_requested_on_double_click(qapp):
    from pathlib import Path
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    tab.populate_preview(_scan())
    tab._scan = _scan()
    got = []
    tab.preview_requested.connect(lambda s, v: got.append((s, v)))
    tab._on_row_double_clicked(0, 0)
    assert got == [(Path("a [01].ass"), Path("v01.mkv"))]
    tab._on_row_double_clicked(1, 2)
    assert got[1] == (Path("b [02].ass"), None)


# ---------- 自動掃描(選資料夾即載入) ----------

def test_auto_scan_triggers_on_folder_chosen(qapp, monkeypatch, tmp_path):
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab._folder_chosen(str(tmp_path))
    assert calls == [1]
    assert tab.folder_edit.text() == str(tmp_path)


def test_auto_scan_skips_same_folder(qapp, monkeypatch, tmp_path):
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab._scanned_folder = str(tmp_path)      # 已掃過同一資料夾
    tab.folder_edit.setText(str(tmp_path))
    tab._auto_scan()
    assert calls == []


def test_auto_scan_skips_invalid_dir(qapp, monkeypatch):
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab.folder_edit.setText("Z:/no/such/dir")
    tab._auto_scan()
    assert calls == []


def test_auto_scan_skips_during_run(qapp, monkeypatch, tmp_path):
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab._thread = object()                    # 模擬批次進行中
    tab._folder_chosen(str(tmp_path))
    assert calls == []


# ---------- 各群組 RadioButton 互不干擾 ----------

def test_radio_groups_do_not_interfere(qapp):
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    tab.scale_mode_radio.setChecked(True)
    tab.outdir_radio.setChecked(True)      # 點輸出模式
    assert tab.scale_mode_radio.isChecked() is True   # 操作模式不得被取消
    tab.inplace_radio.setChecked(True)
    assert tab.scale_mode_radio.isChecked() is True


# ---------- 設定持久化 ----------

def test_save_and_restore_settings_roundtrip(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab_a = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    tab_a.folder_edit.setText(r"C:\videos\show")
    tab_a.outdir_radio.setChecked(True)
    tab_a.outdir_edit.setText(r"C:\videos\out")
    tab_a.save_settings(settings)

    tab_b = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    tab_b.restore_settings(settings)
    assert tab_b.folder_edit.text() == r"C:\videos\show"
    assert tab_b.outdir_radio.isChecked() is True
    assert tab_b.outdir_edit.text() == r"C:\videos\out"


def test_restore_settings_does_not_trigger_scan(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    settings.setValue("subtitle/folder", str(tmp_path))
    settings.setValue("subtitle/output_mode", "inplace")
    settings.setValue("subtitle/outdir", "")

    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    tab.restore_settings(settings)
    assert tab._scanned_folder is None
    assert tab.table.rowCount() == 0


def test_restore_settings_defaults_inplace_when_unset(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    tab.restore_settings(settings)
    assert tab.folder_edit.text() == ""
    assert tab.inplace_radio.isChecked() is True


def test_table_has_alternating_rows(qapp):
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    assert tab.table.alternatingRowColors() is True


def test_table_selects_full_rows(qapp):
    from PySide6.QtWidgets import QAbstractItemView
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    assert tab.table.selectionBehavior() == QAbstractItemView.SelectRows


def test_run_button_tagged_accent(qapp):
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    assert tab.run_button.property("accent") is True


def test_settings_live_in_the_sidebar_not_under_the_table(qapp):
    """方案 C:設定控件在分隔器右側的側欄裡,不再堆在表格下方搶垂直空間。"""
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    assert tab.splitter.widget(0) is tab.table
    sidebar = tab.splitter.widget(1)
    for widget in (tab.apply_mode_radio, tab.scale_mode_radio, tab.scale_panel,
                   tab.inplace_radio, tab.outdir_radio, tab.outdir_edit):
        assert sidebar.isAncestorOf(widget), f"{widget} 不在設定側欄裡"


def test_save_settings_records_splitter_state(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    tab.save_settings(settings)
    assert settings.value("subtitle/splitter") is not None


def test_restore_settings_without_saved_splitter_is_safe(qapp, tmp_path):
    """沒存過分隔器狀態時不得把 None 丟給 restoreState。"""
    from PySide6.QtCore import QSettings
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values
    settings = QSettings(str(tmp_path / "empty.ini"), QSettings.Format.IniFormat)
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    tab.restore_settings(settings)      # 不可拋例外
    assert tab.splitter.count() == 2


# ---------- 目標樣式清單與預計欄 ----------

def test_scan_fills_style_picker(qapp, tmp_path):
    from pathlib import Path
    from ass_style_tool.batch_runner import ScanResult
    from ass_style_tool.episode_match import MatchResult
    from ass_style_tool.style_scan import FileStyles
    tab = _tab()
    scan = ScanResult(
        matches=[MatchResult(Path("a.ass"), 1, status="no_video")],
        styles={Path("a.ass"): FileStyles(Path("a.ass"),
                                          {"Default": 48.0, "CHT": 52.0},
                                          (1920, 1080))})
    from PySide6.QtCore import Qt
    tab._on_scan_finished(scan)
    names = [tab.style_picker.list.item(i).data(Qt.ItemDataRole.UserRole)
             for i in range(tab.style_picker.list.count())]
    assert sorted(names) == ["CHT", "Default"]


def test_plan_column_shows_predicted_size(qapp):
    from pathlib import Path
    from ass_style_tool.batch_runner import ScanResult
    from ass_style_tool.episode_match import MatchResult
    from ass_style_tool.style_scan import FileStyles
    tab = _tab()
    scan = ScanResult(
        matches=[MatchResult(Path("a.ass"), 1, status="no_video")],
        styles={Path("a.ass"): FileStyles(Path("a.ass"), {"Default": 48.0},
                                          (1920, 1080))})
    tab._on_scan_finished(scan)
    tab.style_picker.set_selected(["Default"])
    text = tab.table.item(0, 4).text()
    assert "Default 48 →" in text


def test_effective_profile_uses_picker_selection(qapp):
    tab = _tab()
    tab.style_picker.set_available(["CHT"])
    tab.style_picker.set_selected(["CHT"])
    assert tab.effective_profile().target_style_names == ["CHT"]


def test_run_button_disabled_when_nothing_selected(qapp):
    from pathlib import Path
    from ass_style_tool.batch_runner import ScanResult
    from ass_style_tool.episode_match import MatchResult
    from ass_style_tool.style_scan import FileStyles
    tab = _tab()
    scan = ScanResult(
        matches=[MatchResult(Path("a.ass"), 1, status="no_video")],
        styles={Path("a.ass"): FileStyles(Path("a.ass"), {"Default": 48.0},
                                          (1920, 1080))})
    tab._on_scan_finished(scan)
    tab.style_picker.set_selected([])
    assert tab.run_button.isEnabled() is False
    tab.style_picker.set_selected(["Default"])
    assert tab.run_button.isEnabled() is True


# ---------- auto_scan_once ----------

def test_auto_scan_once_scans_then_stops(qapp, monkeypatch, tmp_path):
    tab = _tab()
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab.folder_edit.setText(str(tmp_path))
    tab.auto_scan_once()
    tab.auto_scan_once()
    assert calls == [1]


def test_auto_scan_once_skips_missing_folder(qapp, monkeypatch, tmp_path):
    tab = _tab()
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab.folder_edit.setText(str(tmp_path / "不存在"))
    tab.auto_scan_once()
    assert calls == []


# ---------- Task 6 review修正:縮放模式的執行按鈕閘門 ----------

def _scan_with_default_style():
    from ass_style_tool.batch_runner import ScanResult
    from ass_style_tool.episode_match import MatchResult
    from ass_style_tool.style_scan import FileStyles
    return ScanResult(
        matches=[MatchResult(Path("a.ass"), 1, status="no_video")],
        styles={Path("a.ass"): FileStyles(Path("a.ass"), {"Default": 48.0},
                                          (1920, 1080))})


def test_run_button_enabled_in_scale_mode_without_style_selection(qapp):
    """縮放模式不看側欄的目標樣式勾選(ScaleWorker 只吃 ScalePanel.get_options())。"""
    tab = _tab()
    tab.scale_mode_radio.setChecked(True)
    tab._on_scan_finished(_scan_with_default_style())
    assert tab.style_picker.selected() == []
    assert tab.run_button.isEnabled() is True


def test_run_button_disabled_in_apply_mode_without_style_selection(qapp):
    tab = _tab()
    tab._on_scan_finished(_scan_with_default_style())
    assert tab.apply_mode_radio.isChecked() is True
    assert tab.style_picker.selected() == []
    assert tab.run_button.isEnabled() is False


def test_switching_to_scale_mode_enables_run_button_immediately(qapp):
    """從套用模式(無勾選、按鈕關閉)切到縮放模式,不需要任何其他互動就要重新開放。"""
    tab = _tab()
    tab._on_scan_finished(_scan_with_default_style())
    assert tab.run_button.isEnabled() is False
    tab.scale_mode_radio.setChecked(True)
    assert tab.run_button.isEnabled() is True


def test_on_finished_respects_gate_after_mid_run_uncheck(qapp):
    """執行中途取消勾選唯一選取的樣式:結束時按鈕必須維持關閉,不能被強制打開。"""
    from unittest.mock import Mock
    tab = _tab()
    tab._on_scan_finished(_scan_with_default_style())
    tab.style_picker.set_selected(["Default"])
    assert tab.run_button.isEnabled() is True
    tab._thread = Mock()          # 模擬批次執行緒仍在跑
    tab.style_picker.set_selected([])   # 執行中途取消勾選
    tab._on_finished(1, 0, 0)
    assert tab.run_button.isEnabled() is False


# ---------- Task 6 review修正:縮放模式「預計」欄 ----------

def test_scale_mode_plan_text_shows_predicted_size(qapp):
    tab = _tab()
    tab.scale_mode_radio.setChecked(True)
    tab._on_scan_finished(_scan_with_default_style())
    text = tab.table.item(0, 4).text()
    assert text == "Default 48 → 60(×1.2)"


def test_scale_mode_scale_error_shows_marker_not_blank(qapp):
    tab = _tab()
    tab.scale_mode_radio.setChecked(True)
    tab.scale_panel.factor_edit.setText("")   # 倍率欄位空著 → get_options() 拋 ScaleError
    tab._on_scan_finished(_scan_with_default_style())
    text = tab.table.item(0, 4).text()
    assert text == "⚠ 縮放參數有誤"


# ---------- Task 10: 「預計 / 結果」的狀態轉換 ----------

def _scan_with_one_file():
    from pathlib import Path
    from ass_style_tool.batch_runner import ScanResult
    from ass_style_tool.episode_match import MatchResult
    from ass_style_tool.style_scan import FileStyles
    return ScanResult(
        matches=[MatchResult(Path("a.ass"), 1, status="no_video")],
        styles={Path("a.ass"): FileStyles(Path("a.ass"), {"Default": 48.0},
                                          (1920, 1080))})


def test_run_start_marks_rows_in_progress(qapp):
    tab = _tab()
    tab._on_scan_finished(_scan_with_one_file())
    tab.style_picker.set_selected(["Default"])
    tab.mark_rows_pending()
    assert tab.table.item(0, 4).text() == "處理中…"


def test_file_done_replaces_cell_with_result(qapp):
    tab = _tab()
    tab._on_scan_finished(_scan_with_one_file())
    tab.style_picker.set_selected(["Default"])
    tab.mark_rows_pending()
    tab._set_row_result("a.ass", "ok")
    assert "✓" in tab.table.item(0, 4).text()


def test_rescan_restores_plan_text(qapp):
    tab = _tab()
    tab._on_scan_finished(_scan_with_one_file())
    tab.style_picker.set_selected(["Default"])
    tab.mark_rows_pending()
    tab._set_row_result("a.ass", "error")
    tab._on_scan_finished(_scan_with_one_file())      # 重新掃描
    assert "Default 48 →" in tab.table.item(0, 4).text()


def test_run_to_completion_reconciles_every_row(qapp, monkeypatch):
    """Task 10 review Finding 2:批次真的跑到底(沒被取消)之後,不能有
    任何列卡在「處理中…」。字幕檔分頁的表格列跟 scan.matches 是 1:1
    對應的,所以這裡用「不同檔案吃到不同結果狀態(ok/skipped/error)」
    當作混合情境,並驅動真正的 BatchWorker(監聽它的 file_done/finished
    signal,不是逐列手動呼叫 _set_row_result)。"""
    import ass_style_tool.qt.batch_worker as batch_worker_mod
    from ass_style_tool.batch_runner import FileReport
    from ass_style_tool.qt.batch_worker import BatchWorker
    from ass_style_tool.style_scan import FileStyles

    matches = [
        MatchResult(sub_path=Path("a.ass"), episode=1, status="no_video"),
        MatchResult(sub_path=Path("b.ass"), episode=2, status="no_video"),
        MatchResult(sub_path=Path("c.ass"), episode=3, status="no_video"),
    ]
    scan = ScanResult(matches=matches, warnings=[],
                      styles={m.sub_path: FileStyles(m.sub_path, {"Default": 48.0},
                                                     (1920, 1080)) for m in matches})

    reports = {
        Path("a.ass"): FileReport(Path("a.ass"), "ok"),
        Path("b.ass"): FileReport(Path("b.ass"), "skipped"),
        Path("c.ass"): FileReport(Path("c.ass"), "error"),
    }
    monkeypatch.setattr(
        batch_worker_mod, "process_file",
        lambda match, profile, out: reports[match.sub_path])

    tab = _tab()
    tab.populate_preview(scan)
    tab._scan = scan
    tab.style_picker.set_available(["Default"])
    tab.style_picker.set_selected(["Default"])
    tab.mark_rows_pending()
    for r in range(3):
        assert tab.table.item(r, 4).text() == "處理中…"

    worker = BatchWorker(scan, tab.effective_profile(), output_dir=None)
    worker.file_done.connect(tab._set_row_result)
    worker.finished.connect(tab._on_finished)
    worker.run()

    assert tab.table.item(0, 4).text() == "✓ 已套用"
    assert tab.table.item(1, 4).text() == "⊘ 略過"
    assert tab.table.item(2, 4).text() == "✗ 失敗"
    assert all(tab.table.item(r, 4).text() != "處理中…" for r in range(3))


def test_cancelled_run_reconciles_remaining_rows(qapp, monkeypatch):
    """Task 10 review Finding 2:取消批次時 BatchWorker.run() 一偵測到
    取消旗標就直接 break,還沒輪到的檔案不會發出 file_done。既有的 17
    個測試都是逐列手動呼叫 _set_row_result 灌結果,完全不會踩到這個
    「worker 提早離開迴圈」的路徑——這裡改成驅動真正的 worker,在第一個
    檔案完成後立刻取消,確認排在後面、從未被處理過的列不會卡在
    「處理中…」。"""
    import ass_style_tool.qt.batch_worker as batch_worker_mod
    from ass_style_tool.batch_runner import FileReport
    from ass_style_tool.qt.batch_worker import BatchWorker
    from ass_style_tool.style_scan import FileStyles

    matches = [
        MatchResult(sub_path=Path("a.ass"), episode=1, status="no_video"),
        MatchResult(sub_path=Path("b.ass"), episode=2, status="no_video"),
        MatchResult(sub_path=Path("c.ass"), episode=3, status="no_video"),
    ]
    scan = ScanResult(matches=matches, warnings=[],
                      styles={m.sub_path: FileStyles(m.sub_path, {"Default": 48.0},
                                                     (1920, 1080)) for m in matches})
    monkeypatch.setattr(
        batch_worker_mod, "process_file",
        lambda match, profile, out: FileReport(match.sub_path, "ok"))

    tab = _tab()
    tab.populate_preview(scan)
    tab._scan = scan
    tab.style_picker.set_available(["Default"])
    tab.style_picker.set_selected(["Default"])
    tab.mark_rows_pending()

    worker = BatchWorker(scan, tab.effective_profile(), output_dir=None)
    worker.file_done.connect(tab._set_row_result)
    # 模擬使用者在第一個檔案處理完後立刻按下取消
    worker.file_done.connect(lambda name, status: worker.cancel())
    worker.finished.connect(tab._on_finished)
    worker.run()

    # 第一列真的跑完、拿到結果
    assert tab.table.item(0, 4).text() == "✓ 已套用"
    # 後面兩列從沒被 worker 碰過,取消後不能還卡在「處理中…」
    assert tab.table.item(1, 4).text() != "處理中…"
    assert tab.table.item(2, 4).text() != "處理中…"


# ---------- C1:編輯器欄位壞掉時,「預計」欄的重算不能讓分頁卡死 ----------

def test_plan_column_resize_mode_does_not_elide_text(qapp):
    """Minor bullet:「預計 / 結果」欄要有 resize 政策,不然長文字會被
    裁到剩幾個字。"""
    from PySide6.QtWidgets import QHeaderView
    tab = _tab()
    assert (tab.table.horizontalHeader().sectionResizeMode(4)
           == QHeaderView.ResizeToContents)


def test_plans_marks_error_when_profile_is_invalid_instead_of_raising(qapp):
    """C1(最終審查 Finding):_get_profile()(這裡是 style_editor 的
    current_profile,經 profile_from_values() 驗證)在編輯器欄位是壞的
    時候會拋 ValueError——effective_profile() 直接把它往上傳,而 _plans()
    完全沒接住。這裡直接把 get_profile 換成一個保證拋例外的假函式,模擬
    「字型名稱被清空」之類的欄位錯誤,確認 _plans() 不會讓例外逃出去,
    而是每一列都秀出明確標記。"""
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab

    def boom():
        raise ValueError("字型名稱不可為空")

    tab = SubtitleFileTab(boom)
    tab._on_scan_finished(_scan_with_default_style())
    tab.style_picker.set_selected(["Default"])
    text = tab.table.item(0, 4).text()
    assert text == "⚠ 樣式設定有誤"


def test_scan_finished_completes_bookkeeping_when_profile_is_invalid(qapp):
    """C1 的真正後果:populate_preview() 若讓 ValueError 逃出
    _on_scan_finished(),PySide6 會印出 traceback 並吞掉例外,但 slot
    在拋出點提前中斷——scan_button 重新啟用、_scan_thread/_scan_worker
    清空等收尾動作永遠不會執行,分頁從此卡死(scan_button 永遠是關的、
    auto_scan_once 永遠拒絕)。這裡直接驅動 _on_scan_finished()(不是
    _plans()),確認收尾動作真的都跑完了。"""
    from unittest.mock import Mock
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab

    def boom():
        raise ValueError("alignment 必須是 1-9")

    tab = SubtitleFileTab(boom)
    tab.style_picker.set_selected(["Default"])
    tab._scan_thread = Mock()            # 模擬掃描執行緒仍在跑
    tab._scan_worker = Mock()
    tab.scan_button.setEnabled(False)

    tab._on_scan_finished(_scan_with_default_style())

    assert tab.scan_button.isEnabled() is True
    assert tab._scan_thread is None
    assert tab._scan_worker is None


def test_switching_mode_recomputes_plan_column(qapp):
    """Task 6 review 發現、延到 Task 10 修:_on_mode_changed 之前不會重算
    預計欄,導致切模式後畫面還留著前一個模式的預告文字(例如切到縮放
    模式後仍顯示套用模式算出來的 Default 48 → 72)。"""
    tab = _tab()
    tab._on_scan_finished(_scan_with_default_style())
    tab.style_picker.set_selected(["Default"])
    apply_text = tab.table.item(0, 4).text()
    assert "×" not in apply_text          # 套用模式沒有倍率標記
    tab.scale_mode_radio.setChecked(True)
    scale_text = tab.table.item(0, 4).text()
    assert "×" in scale_text              # 縮放模式要秀出倍率,不能還是套用模式的舊文字
    assert scale_text != apply_text
