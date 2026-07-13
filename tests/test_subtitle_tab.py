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
