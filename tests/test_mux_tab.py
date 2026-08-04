from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_mux import MuxPair
from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values


def _tab(monkeypatch, available=True):
    fake = (lambda: Path("x.exe")) if available else (lambda: None)
    monkeypatch.setattr("ass_style_tool.qt.mux_tab.mkvmerge_path", fake)
    monkeypatch.setattr("ass_style_tool.qt.mux_tab.mkvextract_path", fake)
    from ass_style_tool.qt.mux_tab import MuxTab
    return MuxTab(lambda: profile_from_values(DEFAULT_VALUES))


PAIRS = [
    MuxPair(Path("a [01].mkv"), Path("a [01].ass"), 1, "matched"),
    MuxPair(Path("b [02].mkv"), None, 2, "no_subtitle"),
    MuxPair(Path("c [03].mkv"), Path("c [03].ass"), 3, "matched"),
]


def test_populate_checks_matched_only(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    assert tab.table.rowCount() == 3
    checked = tab.checked_pairs()
    assert {p.video_path for p in checked} == {Path("a [01].mkv"), Path("c [03].mkv")}


def test_checked_pairs_respects_unchecking(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    tab.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    checked = tab.checked_pairs()
    assert {p.video_path for p in checked} == {Path("c [03].mkv")}


def test_current_meta(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.trackname_edit.setText("繁中")
    tab.default_check.setChecked(True)
    tab.forced_check.setChecked(False)
    meta = tab.current_meta()
    assert meta.track_name == "繁中"
    assert meta.default is True
    assert meta.forced is False
    assert meta.language                      # 有語言值(下拉預設)


def test_mode_switch_shows_scale_panel(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.scale_panel.isHidden() is True
    tab.scale_mode_radio.setChecked(True)
    assert tab.scale_panel.isHidden() is False


def test_run_button_enabled_after_populate(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.run_button.isEnabled() is False
    tab.populate(PAIRS)
    assert tab.run_button.isEnabled() is True


def test_tools_missing_disables(qapp, monkeypatch):
    tab = _tab(monkeypatch, available=False)
    assert tab.tools_available is False
    assert tab.run_button.isEnabled() is False
    assert tab.scan_button.isEnabled() is False


def test_operation_none_when_direct(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.direct_mode_radio.setChecked(True)
    assert tab.current_operation() is None


def test_operation_profile_when_apply(qapp, monkeypatch):
    from ass_style_tool.profile import Profile
    tab = _tab(monkeypatch)
    tab.apply_mode_radio.setChecked(True)
    assert isinstance(tab.current_operation(), Profile)


# ---------- 各群組 RadioButton 互不干擾 ----------

def test_radio_groups_do_not_interfere(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.scale_mode_radio.setChecked(True)
    tab.replace_radio.setChecked(True)      # 點輸出模式(取代原影片)
    assert tab.scale_mode_radio.isChecked() is True   # 封裝前處理不得被取消
    tab.outdir_radio.setChecked(True)
    assert tab.scale_mode_radio.isChecked() is True
    # 封裝前處理的三個 radio 仍應在同一群組內互斥
    tab.apply_mode_radio.setChecked(True)
    assert tab.direct_mode_radio.isChecked() is False
    assert tab.scale_mode_radio.isChecked() is False


# ---------- 手動配對:set_row_subtitle 模型變更 ----------

def test_set_row_subtitle_assigns_and_checks(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    # 第 1 列原本 no_subtitle → 手動指定字幕
    tab.set_row_subtitle(1, Path("manual [02].ass"))
    assert tab.table.item(1, 0).checkState() == Qt.CheckState.Checked
    checked = {p.video_path: p for p in tab.checked_pairs()}
    assert Path("b [02].mkv") in checked
    assert checked[Path("b [02].mkv")].subtitle_path == Path("manual [02].ass")


def test_set_row_subtitle_clear_unchecks(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    # 第 0 列原本 matched → 清除指定
    tab.set_row_subtitle(0, None)
    assert tab.table.item(0, 0).checkState() == Qt.CheckState.Unchecked
    assert Path("a [01].mkv") not in {p.video_path for p in tab.checked_pairs()}


def test_set_row_subtitle_reassign_matched(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    # 第 0 列原本 matched(a [01].ass)→ 改指定別的字幕
    tab.set_row_subtitle(0, Path("other [01].ass"))
    checked = {p.video_path: p for p in tab.checked_pairs()}
    assert checked[Path("a [01].mkv")].subtitle_path == Path("other [01].ass")


def test_set_row_subtitle_recovers_ambiguous_row(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    pairs = [MuxPair(Path("d [04].mkv"), None, 4, "ambiguous")]
    tab.populate(pairs)
    tab.set_row_subtitle(0, Path("chosen [04].ass"))
    checked = {p.video_path: p for p in tab.checked_pairs()}
    assert Path("d [04].mkv") in checked
    assert checked[Path("d [04].mkv")].subtitle_path == Path("chosen [04].ass")


def test_set_row_subtitle_recovers_no_episode_row(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    pairs = [MuxPair(Path("movie.mkv"), None, None, "no_episode")]
    tab.populate(pairs)
    tab.set_row_subtitle(0, Path("movie.ass"))
    checked = {p.video_path: p for p in tab.checked_pairs()}
    assert Path("movie.mkv") in checked
    assert checked[Path("movie.mkv")].subtitle_path == Path("movie.ass")


# ---------- 手動配對:字幕欄下拉選單 ----------

def test_populate_builds_subtitle_combos(qapp, monkeypatch):
    from PySide6.QtWidgets import QComboBox
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    combo0 = tab.table.cellWidget(0, 2)
    assert isinstance(combo0, QComboBox)
    # matched 列:初始選取為其字幕
    assert combo0.currentData() == Path("a [01].ass")
    # no_subtitle 列:初始選取「(無)」→ None
    combo1 = tab.table.cellWidget(1, 2)
    assert combo1.currentData() is None


def test_subtitle_combo_stylesheet_is_scoped(qapp, monkeypatch):
    """背景透明樣式表必須限定 QComboBox 型別,不可用裸字串,
    否則會 cascade 到彈出視窗導致其背景消失。"""
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    for row in range(tab.table.rowCount()):
        combo = tab.table.cellWidget(row, 2)
        assert combo.styleSheet().strip().startswith("QComboBox {")


def test_combo_options_include_available_and_current(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab._available_subtitles = [Path("x [01].ass"), Path("y [02].ass")]
    tab.populate(PAIRS)
    combo0 = tab.table.cellWidget(0, 2)
    datas = [combo0.itemData(i) for i in range(combo0.count())]
    assert None in datas                       # 「(無)」選項
    assert Path("x [01].ass") in datas          # 掃描到的可用字幕
    assert Path("y [02].ass") in datas
    assert Path("a [01].ass") in datas          # 該列現有字幕(即使不在掃描清單也保留)
    assert combo0.currentData() == Path("a [01].ass")


# ---------- 設定持久化 ----------

def test_save_and_restore_settings_roundtrip(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab_a = _tab(monkeypatch)
    tab_a.video_edit.setText(r"C:\mux\video")
    tab_a.subtitle_edit.setText(r"C:\mux\sub")
    tab_a.replace_radio.setChecked(True)
    tab_a.outdir_edit.setText(r"C:\mux\out")
    tab_a.save_settings(settings)

    tab_b = _tab(monkeypatch)
    tab_b.restore_settings(settings)
    assert tab_b.video_edit.text() == r"C:\mux\video"
    assert tab_b.subtitle_edit.text() == r"C:\mux\sub"
    assert tab_b.replace_radio.isChecked() is True
    assert tab_b.outdir_edit.text() == r"C:\mux\out"


def test_restore_settings_does_not_trigger_scan(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    settings.setValue("mux/video_folder", str(tmp_path))
    settings.setValue("mux/subtitle_folder", str(tmp_path))
    settings.setValue("mux/output_mode", "outdir")
    settings.setValue("mux/outdir", "")

    tab = _tab(monkeypatch)
    tab.restore_settings(settings)
    assert tab._scanned_key is None
    assert tab.table.rowCount() == 0


def test_restore_settings_defaults_outdir_when_unset(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)

    tab = _tab(monkeypatch)
    tab.restore_settings(settings)
    assert tab.video_edit.text() == ""
    assert tab.subtitle_edit.text() == ""
    assert tab.outdir_radio.isChecked() is True


def test_modify_tracks_stores_edits(qapp, monkeypatch):
    """`_on_modify_tracks` 現在是非同步批次掃描:啟動真正的 QThread,
    掃描完成後透過 `_on_track_scan_done` 開啟對話框。這裡讓 worker 使用
    一個快速的假 list_fn,並用 processEvents 等執行緒真正跑完,而不是
    直接假設它是同步呼叫(對應寫這個測試前那版同步實作)。
    """
    import time
    import ass_style_tool.qt.mux_tab as mux_tab_mod
    from ass_style_tool.qt.mux_tab import MuxTab
    from ass_style_tool.qt.batch_worker import TrackScanWorker
    from ass_style_tool.mkv_io import MediaTrack
    from ass_style_tool.mkv_mux import MuxPair
    from ass_style_tool.track_edit import TrackEdit
    from pathlib import Path

    # 讓 tools 視為可用
    monkeypatch.setattr(mux_tab_mod, "mkvmerge_path", lambda: Path("mkvmerge"))
    monkeypatch.setattr(mux_tab_mod, "mkvextract_path", lambda: Path("mkvextract"))
    tab = MuxTab(lambda: None)

    # 有一部 matched 影片
    tab._pairs = [MuxPair(Path("v.mkv"), None, 1, "matched")]

    def fake_list_fn(video, mkvmerge):
        return [MediaTrack(1, "audio", "A", "jpn", "", True, False)]

    def factory(video_paths, mkvmerge, list_fn=None):
        return TrackScanWorker(video_paths, mkvmerge, list_fn=fake_list_fn)

    monkeypatch.setattr(mux_tab_mod, "TrackScanWorker", factory)

    class FakeDialog:
        def __init__(self, tracks_by_file, existing, parent):
            pass
        def exec(self):
            return 1
        def get_edits(self):
            return {1: TrackEdit(keep=False)}

    monkeypatch.setattr(mux_tab_mod, "ModifyTracksDialog", FakeDialog)
    tab._on_modify_tracks()

    deadline = time.monotonic() + 5.0
    while tab._track_scan_thread is not None and time.monotonic() < deadline:
        qapp.processEvents()

    assert tab._track_scan_thread is None, "scan did not finish"
    assert tab._track_edits == {1: TrackEdit(keep=False)}


# ---------- Fix 1 回歸:MuxTab 這邊本來就有做,補上正式測試 ----------

def test_shutdown_closes_orphaned_track_scan_dialog(qapp, monkeypatch):
    """MuxTab.shutdown() 本來就會呼叫 _finish_track_scan() 收掉修改軌道
    掃描用的模態對話框(mkv_tab 那邊原本沒有,是 Fix 1 的重點)。這裡補上
    先前缺的 shutdown() 測試,釘住這個行為不會被日後改動悄悄弄丟。"""
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    tab = _tab(monkeypatch)
    dialog = ScanProgressDialog(tab)
    dialog.show()
    tab._track_scan_dialog = dialog
    assert dialog.isVisible() is True

    tab.shutdown()

    assert dialog.isVisible() is False
    assert tab._track_scan_dialog is None
    assert tab._track_scan_thread is None
    assert tab._track_scan_worker is None


def test_table_has_alternating_rows(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.table.alternatingRowColors() is True


def test_table_selects_full_rows(qapp, monkeypatch):
    from PySide6.QtWidgets import QAbstractItemView
    tab = _tab(monkeypatch)
    assert tab.table.selectionBehavior() == QAbstractItemView.SelectRows


def test_run_button_tagged_accent(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.run_button.property("accent") is True


def test_track_scan_done_opens_dialog_with_map(qapp, monkeypatch):
    import ass_style_tool.qt.mux_tab as mux_tab_mod
    from pathlib import Path
    from ass_style_tool.mkv_io import MediaTrack
    from ass_style_tool.track_edit import TrackEdit

    monkeypatch.setattr(mux_tab_mod, "mkvmerge_path", lambda: Path("mkvmerge"))
    monkeypatch.setattr(mux_tab_mod, "mkvextract_path", lambda: Path("mkvx"))
    tab = mux_tab_mod.MuxTab(lambda: None)

    seen = {}

    class FakeDialog:
        def __init__(self, tracks_by_file, existing, parent):
            seen["map"] = tracks_by_file
        def exec(self):
            return 1
        def get_edits(self):
            return {2: TrackEdit(keep=False, track_type="subtitles")}

    monkeypatch.setattr(mux_tab_mod, "ModifyTracksDialog", FakeDialog)
    scanned = {Path("a.mkv"): [MediaTrack(2, "subtitles", "S", "chi", "",
                                          False, False)]}
    tab._on_track_scan_done(scanned)
    assert seen["map"] == scanned                  # 整份 map 傳進對話框
    assert tab._track_edits == {2: TrackEdit(keep=False,
                                             track_type="subtitles")}


def test_track_scan_cancelled_leaves_edits_untouched(qapp, monkeypatch):
    import ass_style_tool.qt.mux_tab as mux_tab_mod
    from pathlib import Path

    monkeypatch.setattr(mux_tab_mod, "mkvmerge_path", lambda: Path("mkvmerge"))
    monkeypatch.setattr(mux_tab_mod, "mkvextract_path", lambda: Path("mkvx"))
    tab = mux_tab_mod.MuxTab(lambda: None)

    def boom(*a, **k):
        raise AssertionError("取消後不該開啟對話框")

    monkeypatch.setattr(mux_tab_mod, "ModifyTracksDialog", boom)
    tab._track_edits = {}
    tab._on_track_scan_cancelled()
    assert tab._track_edits == {}


def test_empty_scan_result_does_not_open_dialog(qapp, monkeypatch):
    import ass_style_tool.qt.mux_tab as mux_tab_mod
    from pathlib import Path

    monkeypatch.setattr(mux_tab_mod, "mkvmerge_path", lambda: Path("mkvmerge"))
    monkeypatch.setattr(mux_tab_mod, "mkvextract_path", lambda: Path("mkvx"))
    tab = mux_tab_mod.MuxTab(lambda: None)

    def boom(*a, **k):
        raise AssertionError("沒有任何軌道時不該開啟對話框")

    monkeypatch.setattr(mux_tab_mod, "ModifyTracksDialog", boom)
    messages = []
    tab.log.connect(messages.append)
    tab._on_track_scan_done({Path("a.mkv"): []})    # 全部讀不到軌道
    assert any("所有影片都讀不到軌道資訊" in m for m in messages)


def test_scan_dialog_cancel_genuinely_stops_the_scan(qapp, monkeypatch):
    """釘住取消路徑本身,而不只是「取消後不開對話框」的表面行為。

    `_track_scan_dialog.cancelled` 必須接到 `_request_track_scan_cancel`
    (直接呼叫 worker.cancel(),同執行緒同步呼叫),不能改接
    `worker.cancel`(跨執行緒排入 worker 自己的事件佇列——但 worker 在
    run() 執行期間根本不跑事件迴圈,排進去的 cancel() 要等整批掃完才會
    被處理,等於形同虛設)。這正是本專案先前出過、被抓到的那個 bug。

    用真正的 QThread + 會拖時間的假 list_fn,跑到至少完成一檔後,呼叫
    使用者實際會走的路徑——`_track_scan_dialog.reject()`——確認掃描
    真的提早停止(未跑完全部檔案),且對話框從未開啟。
    """
    import time
    import ass_style_tool.qt.mux_tab as mux_tab_mod
    from ass_style_tool.qt.batch_worker import TrackScanWorker
    from ass_style_tool.mkv_io import MediaTrack
    from ass_style_tool.mkv_mux import MuxPair

    monkeypatch.setattr(mux_tab_mod, "mkvmerge_path", lambda: Path("mkvmerge"))
    monkeypatch.setattr(mux_tab_mod, "mkvextract_path", lambda: Path("mkvextract"))
    tab = mux_tab_mod.MuxTab(lambda: None)

    total = 20
    tab._pairs = [MuxPair(Path(f"v{i}.mkv"), None, i, "matched")
                  for i in range(total)]

    completed: list = []

    def slow_list_fn(video, mkvmerge):
        time.sleep(0.05)
        completed.append(video)
        return [MediaTrack(1, "audio", "A", "jpn", "", True, False)]

    def factory(video_paths, mkvmerge, list_fn=None):
        return TrackScanWorker(video_paths, mkvmerge, list_fn=slow_list_fn)

    monkeypatch.setattr(mux_tab_mod, "TrackScanWorker", factory)

    def boom(*a, **k):
        raise AssertionError("取消後不該開啟修改軌道對話框")

    monkeypatch.setattr(mux_tab_mod, "ModifyTracksDialog", boom)

    try:
        tab._on_modify_tracks()

        deadline = time.monotonic() + 5.0
        while len(completed) < 1 and time.monotonic() < deadline:
            qapp.processEvents()
        assert len(completed) >= 1, "scan never completed a single file"
        assert tab._track_scan_dialog is not None

        tab._track_scan_dialog.reject()   # 使用者實際點取消/Esc/叉叉的路徑

        deadline = time.monotonic() + 5.0
        while tab._track_scan_thread is not None and time.monotonic() < deadline:
            qapp.processEvents()

        assert tab._track_scan_thread is None, "scan did not finish/cancel"
        assert len(completed) < total, "cancel did not stop the scan early"
    finally:
        if tab._track_scan_worker is not None:
            tab._track_scan_worker.cancel()
        if tab._track_scan_thread is not None:
            tab._track_scan_thread.quit()
            tab._track_scan_thread.wait(2000)


# ---------- 方案 C:設定側欄 ----------

def test_settings_live_in_the_sidebar_not_under_the_table(qapp, monkeypatch):
    """方案 C:封裝分頁原本 9 條裸露橫列把表格擠成兩三列高,設定改進側欄。"""
    tab = _tab(monkeypatch)
    assert tab.splitter.widget(0) is tab.table
    sidebar = tab.splitter.widget(1)
    for widget in (tab.direct_mode_radio, tab.apply_mode_radio,
                   tab.scale_mode_radio, tab.scale_panel,
                   tab.language_combo, tab.trackname_edit,
                   tab.default_check, tab.forced_check,
                   tab.modify_tracks_button,
                   tab.outdir_radio, tab.outdir_edit, tab.replace_radio):
        assert sidebar.isAncestorOf(widget), f"{widget} 不在設定側欄裡"


def test_save_settings_records_splitter_state(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)
    tab = _tab(monkeypatch)
    tab.save_settings(settings)
    assert settings.value("mux/splitter") is not None


def test_restore_settings_without_saved_splitter_is_safe(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / "empty.ini"), QSettings.Format.IniFormat)
    tab = _tab(monkeypatch)
    tab.restore_settings(settings)      # 不可拋例外
    assert tab.splitter.count() == 2


# ---------- 目標樣式清單 ----------

def test_style_picker_hidden_when_direct_mux(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    # direct_mode_radio 建構時就已經是勾選狀態,若直接再 setChecked(True)
    # 是 no-op(Qt 對已勾選的 QRadioButton 再勾一次不會發 toggled),完全
    # 測不到 handler 的「切回直接封裝」這條路徑。要先切到別的模式,
    # 再切回來,才是真的走過 _on_preprocess_mode_changed 的切換邏輯。
    tab.apply_mode_radio.setChecked(True)
    assert tab.style_group.isHidden() is False
    tab.direct_mode_radio.setChecked(True)
    assert tab.style_group.isHidden() is True


def test_style_picker_shown_when_applying_style(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.apply_mode_radio.setChecked(True)
    assert tab.style_group.isHidden() is False


def test_style_picker_hidden_when_scale_mux(qapp, monkeypatch):
    """先縮放字級模式下 current_operation() 回傳 scale_panel.get_options(),
    根本不會讀 style_picker——側欄勾了樣式也會在執行時被靜默忽略,所以
    這個模式下 style_group 必須跟直接封裝一樣被隱藏。"""
    tab = _tab(monkeypatch)
    tab.scale_mode_radio.setChecked(True)
    assert tab.style_group.isHidden() is True


def test_effective_profile_uses_picker_selection(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.style_picker.set_available(["CHT"])
    tab.style_picker.set_selected(["CHT"])
    assert tab.effective_profile().target_style_names == ["CHT"]


def test_auto_scan_once_only_scans_one_time(qapp, monkeypatch, tmp_path):
    tab = _tab(monkeypatch)
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab.video_edit.setText(str(tmp_path))
    tab.subtitle_edit.setText(str(tmp_path))
    tab.auto_scan_once()
    tab.auto_scan_once()
    assert calls == [1]


def test_auto_scan_once_skips_when_a_folder_is_missing(qapp, monkeypatch,
                                                       tmp_path):
    tab = _tab(monkeypatch)
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab.video_edit.setText(str(tmp_path))
    tab.subtitle_edit.setText("")          # 字幕資料夾還沒選
    tab.auto_scan_once()
    assert calls == []


def test_auto_scan_once_skips_while_scan_in_flight(qapp, monkeypatch, tmp_path):
    tab = _tab(monkeypatch)
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab.video_edit.setText(str(tmp_path))
    tab.subtitle_edit.setText(str(tmp_path))
    tab._scan_thread = object()            # 模擬掃描已在進行中
    tab.auto_scan_once()
    assert calls == []


def test_auto_scan_once_skips_while_run_in_flight(qapp, monkeypatch, tmp_path):
    tab = _tab(monkeypatch)
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab.video_edit.setText(str(tmp_path))
    tab.subtitle_edit.setText(str(tmp_path))
    tab._thread = object()                 # 模擬封裝已在進行中
    tab.auto_scan_once()
    assert calls == []


# ---------- 執行按鈕:套用模式下沒勾樣式不能執行 ----------

def test_run_button_disabled_in_apply_mode_without_styles(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    assert tab.run_button.isEnabled() is True    # 直接封裝:不吃樣式勾選
    tab.apply_mode_radio.setChecked(True)
    assert tab.run_button.isEnabled() is False   # 套用模式沒勾任何樣式


def test_run_button_enabled_in_apply_mode_with_styles(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    tab.apply_mode_radio.setChecked(True)
    assert tab.run_button.isEnabled() is False
    tab.style_picker.set_available(["CHT"])
    tab.style_picker.set_selected(["CHT"])
    assert tab.run_button.isEnabled() is True


def test_run_button_enabled_in_scale_mode_without_styles(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    tab.scale_mode_radio.setChecked(True)
    assert tab.run_button.isEnabled() is True    # 縮放模式不吃樣式勾選


def test_run_button_enabled_in_direct_mode_without_styles(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    tab.apply_mode_radio.setChecked(True)
    assert tab.run_button.isEnabled() is False
    tab.direct_mode_radio.setChecked(True)       # 切回直接封裝
    assert tab.run_button.isEnabled() is True


# ---------- _on_scan_done:消費 MuxScanWorker 已經算好的 MuxScanResult ----------
# 「未配對到字幕的列不能餵給 scan_styles」這條過濾邏輯本身已經搬進
# MuxScanWorker.run()(最終審查 I10:大季同步解析會卡住視窗),
# 見 tests/test_mux_worker.py 的
# test_scan_worker_scans_styles_for_matched_pairs_only /
# test_scan_worker_all_unmatched_skips_scan_styles——那裡才是這條規則
# 真正的邏輯所在地。這裡改成驗證 _on_scan_done 正確消費一份已經算好的
# MuxScanResult,不重新推導 file_styles。

def test_on_scan_done_wires_file_styles_from_result(qapp, monkeypatch):
    from ass_style_tool.style_scan import FileStyles
    from ass_style_tool.qt.batch_worker import MuxScanResult
    tab = _tab(monkeypatch)
    sub = Path("a [01].ass")
    result = MuxScanResult(
        pairs=[MuxPair(Path("a [01].mkv"), sub, 1, "matched"),
              MuxPair(Path("b [02].mkv"), None, 2, "no_subtitle")],
        file_styles={sub: FileStyles(path=sub, styles={"CHT": 40.0})})
    tab._on_scan_done(result)
    assert tab._file_styles == result.file_styles
    assert "CHT" in tab.style_picker._available


def test_on_scan_done_all_unmatched_yields_empty_styles_without_raising(
        qapp, monkeypatch):
    """整批都沒配對到字幕時,MuxScanResult.file_styles 是空字典——這裡
    確認分頁端不會因為空字典而拋例外,樣式清單顯示為空。"""
    from ass_style_tool.qt.batch_worker import MuxScanResult
    tab = _tab(monkeypatch)
    result = MuxScanResult(
        pairs=[MuxPair(Path("a [01].mkv"), None, 1, "no_subtitle"),
              MuxPair(Path("b [02].mkv"), None, 2, "ambiguous")],
        file_styles={})
    tab._on_scan_done(result)               # 不應拋例外
    assert tab.table.rowCount() == 2
    assert tab.style_picker.list.count() == 0


# ---------- Task 10: 「預計 / 結果」欄 ----------

def test_plan_column_header_label(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    assert tab.table.horizontalHeaderItem(5).text() == "預計 / 結果"


def test_direct_mode_plan_shows_no_modification_marker(qapp, monkeypatch):
    from ass_style_tool.style_scan import FileStyles
    tab = _tab(monkeypatch)
    assert tab.direct_mode_radio.isChecked() is True
    tab._file_styles = {
        Path("a [01].ass"): FileStyles(Path("a [01].ass"), {"Default": 48.0},
                                       (1920, 1080))}
    tab.populate(PAIRS)
    assert tab.table.item(0, 5).text() == "直接封裝,不修改字幕"


def test_direct_mode_plan_blank_for_no_subtitle_row(qapp, monkeypatch):
    """Task 10 review Finding 3:direct 模式下沒配對到字幕的列(PAIRS 的
    第 1 列,status="no_subtitle")不能顯示「直接封裝,不修改字幕」——
    process_mux 對 subtitle_path is None 的列一律直接以 skipped 略過
    (「無配對字幕,略過」),顯示直封標記會誤導使用者以為這列真的會被
    處理。"""
    tab = _tab(monkeypatch)
    assert tab.direct_mode_radio.isChecked() is True
    tab.populate(PAIRS)
    assert tab.table.item(1, 5).text() == ""


def test_apply_mode_plan_shows_predicted_size(qapp, monkeypatch):
    from ass_style_tool.style_scan import FileStyles
    tab = _tab(monkeypatch)
    tab.apply_mode_radio.setChecked(True)
    tab._file_styles = {
        Path("a [01].ass"): FileStyles(Path("a [01].ass"), {"Default": 48.0},
                                       (1920, 1080))}
    tab.populate(PAIRS)
    tab.style_picker.set_available(["Default"])
    tab.style_picker.set_selected(["Default"])
    text = tab.table.item(0, 5).text()
    assert "Default 48 →" in text


def test_switching_preprocess_mode_recomputes_plan_column(qapp, monkeypatch):
    """跟字幕檔分頁同一個 Task 6 review 缺陷:封裝分頁有三種前處理模式,
    切換時如果不重算,畫面會留著前一個模式的預告文字。"""
    from ass_style_tool.style_scan import FileStyles
    tab = _tab(monkeypatch)
    tab._file_styles = {
        Path("a [01].ass"): FileStyles(Path("a [01].ass"), {"Default": 48.0},
                                       (1920, 1080))}
    tab.populate(PAIRS)
    tab.apply_mode_radio.setChecked(True)
    tab.style_picker.set_available(["Default"])
    tab.style_picker.set_selected(["Default"])
    apply_text = tab.table.item(0, 5).text()
    assert "Default 48 →" in apply_text

    tab.direct_mode_radio.setChecked(True)
    direct_text = tab.table.item(0, 5).text()
    assert direct_text == "直接封裝,不修改字幕"
    assert direct_text != apply_text

    tab.scale_mode_radio.setChecked(True)
    scale_text = tab.table.item(0, 5).text()
    assert "×" in scale_text
    assert scale_text not in (apply_text, direct_text)


def test_style_selection_change_recomputes_plan_column(qapp, monkeypatch):
    from ass_style_tool.style_scan import FileStyles
    tab = _tab(monkeypatch)
    tab.apply_mode_radio.setChecked(True)
    tab._file_styles = {
        Path("a [01].ass"): FileStyles(
            Path("a [01].ass"), {"Default": 48.0, "CHT": 52.0}, (1920, 1080))}
    tab.populate(PAIRS)
    tab.style_picker.set_available(["Default", "CHT"])
    tab.style_picker.set_selected(["Default"])
    first_text = tab.table.item(0, 5).text()
    tab.style_picker.set_selected(["CHT"])
    second_text = tab.table.item(0, 5).text()
    assert "Default" in first_text
    assert "CHT" in second_text
    assert first_text != second_text


def test_mark_rows_pending_sets_processing_text(qapp, monkeypatch):
    """Task 10 review Finding 1:只有真的會被這批工作處理的列(勾選且
    status=="matched",跟 checked_pairs() 同一套判斷)會換成
    「處理中…」;PAIRS 的第 1 列是 no_subtitle(從未勾選),不屬於這批
    工作,必須維持原狀。"""
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    before = tab.table.item(1, 5).text()
    tab.mark_rows_pending()
    assert tab.table.item(0, 5).text() == "處理中…"
    assert tab.table.item(2, 5).text() == "處理中…"
    assert tab.table.item(1, 5).text() == before


def test_set_row_result_replaces_cell(qapp, monkeypatch):
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    tab.mark_rows_pending()
    tab._set_row_result("a [01].mkv", "ok")
    assert "✓" in tab.table.item(0, 5).text()


def test_run_to_completion_reconciles_job_rows_and_preserves_others(
        qapp, monkeypatch):
    """Task 10 review Finding 1:一個 3 列的表格裡有一列 no_subtitle
    (PAIRS 第 1 列),批次跑到底之後,那一列不能被誤標成「處理中…」,
    也不能在跑完之後留在「處理中…」;真正在這批工作裡的兩列則要拿到
    各自的結果(混合 ok/error)。驅動真正的 MuxWorker(注入假
    process_fn,不呼叫外部 mkvmerge),監聽它的 file_done/finished
    signal,不是逐列手動呼叫 _set_row_result。"""
    from ass_style_tool.mkv_batch import MkvFileReport
    from ass_style_tool.qt.batch_worker import MuxWorker

    tab = _tab(monkeypatch)
    # Finding 4(最終審查 Batch A3)之後,「結果」欄的「ok」標籤依
    # direct_mode_radio(分頁預設勾選)而定;這個測試關心的是 Task 10
    # Finding 1 的列狀態追蹤,不是標籤內容本身,切到套用模式讓「✓ 已
    # 套用」這個既有斷言維持原本的意義。
    tab.apply_mode_radio.setChecked(True)
    tab.populate(PAIRS)
    before_row1 = tab.table.item(1, 5).text()

    pairs = tab.checked_pairs()
    assert {p.video_path for p in pairs} == {
        Path("a [01].mkv"), Path("c [03].mkv")}

    reports = {
        Path("a [01].mkv"): MkvFileReport(Path("a [01].mkv"), "ok"),
        Path("c [03].mkv"): MkvFileReport(Path("c [03].mkv"), "error"),
    }

    def fake_process(pair, meta, operation, tools, out_path=None,
                     progress_cb=None, edits=None):
        return reports[pair.video_path]

    tab.mark_rows_pending()
    assert tab.table.item(0, 5).text() == "處理中…"
    assert tab.table.item(2, 5).text() == "處理中…"
    # 沒配對到字幕、不屬於這批工作的列維持原狀
    assert tab.table.item(1, 5).text() == before_row1

    worker = MuxWorker(pairs, tab.current_meta(), None, tab._tools,
                       output_dir=None, process_fn=fake_process)
    worker.file_done.connect(tab._set_row_result)
    worker.finished.connect(tab._on_finished)
    worker.run()

    assert tab.table.item(0, 5).text() == "✓ 已套用"
    assert tab.table.item(2, 5).text() == "✗ 失敗"
    assert tab.table.item(1, 5).text() == before_row1


def test_result_cell_distinguishes_unstyled_mux_from_styled(qapp, monkeypatch):
    """Finding 4(最終審查 Batch A2):目標樣式在字幕裡找不到時,
    process_mux 仍然把字幕原樣封進去(report.status 保持 "ok"),但
    transform_track_file()(mkv_batch.py)已經在 report.messages 裡留下
    「找不到目標 Style,未修改」,MuxWorker 原封不動經由 message 訊號
    往外送給 log。舊的「結果」欄一律套用 RESULT_ICONS["ok"](「✓ 已
    套用」),讀起來像『有套用樣式』,但這個 case 底下字幕其實完全沒被
    改動——驅動真正的 MuxWorker(注入假 process_fn 回傳這個訊息),
    確認結果欄的文字跟『真的套用了樣式』的那一列不一樣。

    這個訊息只在套用模式底下才會出現(direct 模式從不嘗試套用任何
    樣式,連「找不到」都不會發生),Finding 4 之後「結果」欄的標籤也會
    依 direct_mode_radio 而變——這裡切到套用模式,讓這個測試繼續測它
    本來要測的東西(message-based 的「找不到目標 Style」偵測),不被
    Batch A3 新加的 direct-mode 標籤蓋過去。"""
    from ass_style_tool.mkv_batch import MkvFileReport
    from ass_style_tool.qt.batch_worker import MuxWorker

    tab = _tab(monkeypatch)
    tab.apply_mode_radio.setChecked(True)
    matched_only = [
        MuxPair(Path("a [01].mkv"), Path("a [01].ass"), 1, "matched"),
        MuxPair(Path("b [02].mkv"), Path("b [02].ass"), 2, "matched"),
    ]
    tab.populate(matched_only)
    pairs = tab.checked_pairs()

    reports = {
        Path("a [01].mkv"): MkvFileReport(
            Path("a [01].mkv"), "ok", ["已套用樣式到: Default"]),
        Path("b [02].mkv"): MkvFileReport(
            Path("b [02].mkv"), "ok", ["找不到目標 Style,未修改"]),
    }

    def fake_process(pair, meta, operation, tools, out_path=None,
                     progress_cb=None, edits=None):
        return reports[pair.video_path]

    tab.mark_rows_pending()
    worker = MuxWorker(pairs, tab.current_meta(), None, tab._tools,
                       output_dir=None, process_fn=fake_process)
    worker.file_done.connect(tab._set_row_result)
    worker.message.connect(tab._on_worker_message)
    worker.finished.connect(tab._on_finished)
    worker.run()

    styled_text = tab.table.item(0, 5).text()
    unstyled_text = tab.table.item(1, 5).text()
    assert styled_text == "✓ 已套用"
    assert unstyled_text != styled_text
    assert "✓" in unstyled_text            # 仍然是「成功」,只是沒套用樣式
    assert unstyled_text != "✓ 已套用"


def test_direct_mode_run_result_does_not_claim_styled(qapp, monkeypatch):
    """Finding 4(最終審查 Batch A3):direct_mode_radio 是這個分頁「封裝
    前處理」預設勾選的模式,current_operation() 在這個模式下一律回傳
    None,process_mux 完全不會嘗試套用任何樣式——上一批修復只處理了
    套用模式底下『目標樣式找不到』的例外情況(靠 worker 訊息辨識),
    但 direct 模式從頭到尾不會走到套用邏輯,自然也不會產生那則訊息,
    「結果」欄因此一路落回泛用的 RESULT_ICONS["ok"](「✓ 已套用」),
    對每一個成功的直接封裝檔案都是錯誤的宣稱。這裡確認分頁本身預設
    就在 direct 模式,驅動真正的 MuxWorker(direct 模式的 operation 是
    None),確認結果欄不再讀起來像『套用了樣式』。"""
    from ass_style_tool.mkv_batch import MkvFileReport
    from ass_style_tool.qt.batch_worker import MuxWorker

    tab = _tab(monkeypatch)
    assert tab.direct_mode_radio.isChecked() is True   # 分頁預設模式
    assert tab.current_operation() is None

    matched_only = [
        MuxPair(Path("a [01].mkv"), Path("a [01].ass"), 1, "matched"),
    ]
    tab.populate(matched_only)
    pairs = tab.checked_pairs()

    def fake_process(pair, meta, operation, tools, out_path=None,
                     progress_cb=None, edits=None):
        return MkvFileReport(pair.video_path, "ok")

    tab.mark_rows_pending()
    # Finding 1(最終審查 Batch A4)之後,_set_row_result() 讀的是派工
    # 當下記下的 _run_was_direct,不是即時的 radio 狀態——這裡繞過
    # _on_run() 直接組 worker,所以要自己把這個記號設成派工當下(direct
    # 模式)本該有的值,才能讓 _set_row_result() 收到跟真的跑一次 _on_run()
    # 相同的輸入。
    tab._run_was_direct = True
    worker = MuxWorker(pairs, tab.current_meta(), tab.current_operation(),
                       tab._tools, output_dir=None, process_fn=fake_process)
    worker.file_done.connect(tab._set_row_result)
    worker.finished.connect(tab._on_finished)
    worker.run()

    result_text = tab.table.item(0, 5).text()
    assert result_text != "✓ 已套用"
    assert "✓" in result_text          # 仍然是「成功」,只是不宣稱套用了樣式


def test_mid_run_switch_to_direct_keeps_dispatched_apply_result(
        qapp, monkeypatch):
    """Finding 1(最終審查 Batch A4):_set_row_result 原本讀的是即時的
    direct_mode_radio.isChecked(),不是這批工作實際派工當下用的模式——
    這顆 radio 在批次跑的期間並未被停用(見 _on_finished() 的說明)。
    這裡在套用模式底下真的呼叫 _on_run() 派工(QThread.start() monkeypatch
    成不執行,worker.run() 因此不會被觸發,不會碰任何真正的外部工具),
    確認 _run_was_direct 記住了派工當下的模式;接著在結果送達前把 radio
    切回「直接封」,模擬使用者中途切換模式,確認一個真的套用過樣式的
    檔案不會被誤標成「原字幕直接封,未套用樣式」。"""
    from PySide6.QtCore import QThread
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    tab.replace_radio.setChecked(True)   # 免去挑輸出資料夾
    tab.apply_mode_radio.setChecked(True)
    tab.style_picker.set_selected(["Default"])
    monkeypatch.setattr(QThread, "start", lambda self: None)

    tab._on_run()
    assert tab._run_was_direct is False   # 派工當下是套用模式

    # 使用者在結果送達前把模式切回「直接封」
    tab.direct_mode_radio.setChecked(True)
    tab._set_row_result("a [01].mkv", "ok")

    assert tab.table.item(0, 5).text() == "✓ 已套用"


def test_mid_run_switch_to_apply_keeps_dispatched_direct_result(
        qapp, monkeypatch):
    """Finding 1(最終審查 Batch A4)的另一個方向:direct 模式派工後,
    使用者在結果送達前切成套用模式——不能讓一個根本沒被套用任何樣式的
    直接封裝檔案被誤標成「✓ 已套用」(這正是 _RESULT_DIRECT_TEXT 這個
    分支最初要修的那個 bug,以模式中途切換的方式重現)。"""
    from PySide6.QtCore import QThread
    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    assert tab.direct_mode_radio.isChecked() is True   # 分頁預設模式
    tab.replace_radio.setChecked(True)   # 免去挑輸出資料夾
    monkeypatch.setattr(QThread, "start", lambda self: None)

    tab._on_run()
    assert tab._run_was_direct is True   # 派工當下是直接封裝模式

    # 使用者在結果送達前把模式切成「先套用目前樣式」
    tab.style_picker.set_selected(["Default"])
    tab.apply_mode_radio.setChecked(True)
    tab._set_row_result("a [01].mkv", "ok")

    assert tab.table.item(0, 5).text() == "✓ 已封裝(原字幕直接封,未套用樣式)"


def test_cancelled_run_reconciles_remaining_rows(qapp, monkeypatch):
    """Task 10 review Finding 2:取消封裝時 MuxWorker.run() 一偵測到取消
    旗標就直接 break,還沒輪到的影片不會發出 file_done。這裡驅動真正的
    worker,在第一部影片完成後立刻取消,確認排在後面、從未被處理過的列
    不會卡在「處理中…」。"""
    from ass_style_tool.mkv_batch import MkvFileReport
    from ass_style_tool.qt.batch_worker import MuxWorker

    tab = _tab(monkeypatch)
    # 這個測試關心的是列狀態追蹤(Task 10 Finding 2),不是 Finding 4 的
    # direct-mode 標籤;切到套用模式讓既有的「✓ 已套用」斷言維持原意。
    tab.apply_mode_radio.setChecked(True)
    matched_only = [
        MuxPair(Path("a [01].mkv"), Path("a [01].ass"), 1, "matched"),
        MuxPair(Path("b [02].mkv"), Path("b [02].ass"), 2, "matched"),
        MuxPair(Path("c [03].mkv"), Path("c [03].ass"), 3, "matched"),
    ]
    tab.populate(matched_only)
    pairs = tab.checked_pairs()
    assert len(pairs) == 3

    def fake_process(pair, meta, operation, tools, out_path=None,
                     progress_cb=None, edits=None):
        return MkvFileReport(pair.video_path, "ok")

    tab.mark_rows_pending()

    worker = MuxWorker(pairs, tab.current_meta(), None, tab._tools,
                       output_dir=None, process_fn=fake_process)
    worker.file_done.connect(tab._set_row_result)
    # 模擬使用者在第一部影片完成後立刻按下取消
    worker.file_done.connect(lambda name, status: worker.cancel())
    worker.finished.connect(tab._on_finished)
    worker.run()

    assert tab.table.item(0, 5).text() == "✓ 已套用"
    assert tab.table.item(1, 5).text() != "處理中…"
    assert tab.table.item(2, 5).text() != "處理中…"


# ---------- C1:編輯器欄位壞掉時,「預計」欄的重算不能讓分頁卡死 ----------

def test_plan_column_resize_mode_does_not_elide_text(qapp, monkeypatch):
    """Minor bullet:「預計 / 結果」欄要有 resize 政策,不然長文字會被
    裁到剩幾個字。"""
    from PySide6.QtWidgets import QHeaderView
    tab = _tab(monkeypatch)
    assert (tab.table.horizontalHeader().sectionResizeMode(5)
           == QHeaderView.ResizeToContents)


def test_plan_text_for_marks_error_when_profile_is_invalid(qapp, monkeypatch):
    """C1(最終審查 Finding):_plan_text_for() 呼叫 effective_profile()
    完全沒接住 profile_from_values() 可能拋出的 ValueError(編輯器欄位
    壞掉,例如字型名稱被清空)。用一個保證拋例外的假 get_profile 模擬,
    確認 populate() 不會讓例外逃出去,而是秀出明確標記。"""
    from ass_style_tool.style_scan import FileStyles

    def boom():
        raise ValueError("字型名稱不可為空")

    monkeypatch.setattr("ass_style_tool.qt.mux_tab.mkvmerge_path",
                        lambda: Path("x.exe"))
    monkeypatch.setattr("ass_style_tool.qt.mux_tab.mkvextract_path",
                        lambda: Path("x.exe"))
    from ass_style_tool.qt.mux_tab import MuxTab
    tab = MuxTab(boom)
    tab.apply_mode_radio.setChecked(True)
    tab._file_styles = {
        Path("a [01].ass"): FileStyles(Path("a [01].ass"), {"Default": 48.0},
                                       (1920, 1080))}
    tab.style_picker.set_selected(["Default"])
    tab.populate(PAIRS)      # 不應拋例外
    assert tab.table.item(0, 5).text() == "⚠ 樣式設定有誤"


def test_scan_done_completes_bookkeeping_when_profile_is_invalid(qapp, monkeypatch):
    """C1 的真正後果:populate() 若讓 ValueError 逃出 _on_scan_done(),
    PySide6 印出 traceback 並吞掉例外,但 slot 在拋出點提前中斷——這裡
    直接驅動 _on_scan_done()(_plan_text_for() 的真正呼叫路徑之一),
    確認 log.emit() 等收尾動作真的都跑完。"""
    def boom():
        raise ValueError("alignment 必須是 1-9")

    monkeypatch.setattr("ass_style_tool.qt.mux_tab.mkvmerge_path",
                        lambda: Path("x.exe"))
    monkeypatch.setattr("ass_style_tool.qt.mux_tab.mkvextract_path",
                        lambda: Path("x.exe"))
    from ass_style_tool.qt.mux_tab import MuxTab
    tab = MuxTab(boom)
    tab.apply_mode_radio.setChecked(True)
    tab.style_picker.set_selected(["Default"])
    messages = []
    tab.log.connect(messages.append)

    from ass_style_tool.qt.batch_worker import MuxScanResult
    tab._on_scan_done(MuxScanResult(pairs=PAIRS, file_styles={}))

    assert any("配對完成" in m for m in messages)
    assert tab.scan_button.isEnabled() is True


# ---------- C2:封裝分頁的「找不到」不是「略過」,是「原樣封裝」 ----------

def test_apply_mode_plan_not_found_reads_as_muxed_unstyled_not_skip(
        qapp, monkeypatch):
    """process_mux 對找不到目標樣式的字幕是原樣封裝、不套用樣式
    (report.status 仍是 "ok"),不是整個流程被跳過——「預計」欄的文字
    不能讓人讀成「這個檔不會被動」,否則使用者以為安全,實際上輸出
    MKV(尤其是『取代原影片』模式)會被覆蓋。"""
    from ass_style_tool.style_scan import FileStyles
    tab = _tab(monkeypatch)
    tab.apply_mode_radio.setChecked(True)
    tab._file_styles = {
        Path("a [01].ass"): FileStyles(Path("a [01].ass"), {"CHS": 48.0},
                                       (1920, 1080))}   # 檔案裡沒有 Default
    tab.populate(PAIRS)
    tab.style_picker.set_available(["CHS"])
    tab.style_picker.set_selected(["Default"])
    text = tab.table.item(0, 5).text()
    assert "找不到" in text
    assert "略過" not in text          # 不能讀成「略過」
    assert "原樣封裝" in text          # 要講清楚實際會發生的事


def test_style_picker_not_found_hint_reflects_mux_semantics(qapp, monkeypatch):
    """StylePicker 預設的『這些檔案會被略過』對封裝分頁不準——這裡確認
    mux_tab.py 建構 StylePicker 時真的換了措辭(C2)。"""
    tab = _tab(monkeypatch)
    tab.style_picker.set_available(["CHS"])
    tab.style_picker.set_selected(["Default"])   # Default 不在掃描結果裡
    assert "略過" not in tab.style_picker.hint.text()
    assert "原樣封裝" in tab.style_picker.hint.text()


# ---------- I3 邊界:mux_tab 的 apply_plan_text 呼叫不套用「.srt 全部樣式」規則 ----------

def test_apply_mode_plan_srt_source_does_not_claim_convert_all(qapp, monkeypatch):
    """封裝分頁透過 mkv_mux.process_mux -> transform_track_file 執行,
    那條路徑沒有 apply_to_all_styles=True——即使字幕來源是 .srt,「預計」
    欄也不能宣稱『轉檔後套用到全部樣式』,那是字幕檔分頁
    (batch_runner.process_file)才有的行為(Finding I3 的範圍不含這裡)。"""
    from ass_style_tool.style_scan import FileStyles
    tab = _tab(monkeypatch)
    tab.apply_mode_radio.setChecked(True)
    srt_path = Path("a [01].srt")
    tab._file_styles = {
        srt_path: FileStyles(srt_path, {"CHS": 48.0}, (1920, 1080))}
    pairs = [MuxPair(Path("a [01].mkv"), srt_path, 1, "matched")]
    tab.populate(pairs)
    tab.style_picker.set_available(["CHS"])
    tab.style_picker.set_selected(["Default"])
    text = tab.table.item(0, 5).text()
    assert "全部樣式" not in text
    assert "找不到" in text


# ---------- Minor bullet:auto_scan_once 漏掉 tools_available 檢查 ----------

def test_auto_scan_once_skips_when_tools_missing(qapp, monkeypatch, tmp_path):
    tab = _tab(monkeypatch, available=False)
    calls = []
    monkeypatch.setattr(tab, "_on_scan", lambda: calls.append(1))
    tab.video_edit.setText(str(tmp_path))
    tab.subtitle_edit.setText(str(tmp_path))
    tab.auto_scan_once()
    assert calls == []


def test_rescan_restores_plan_column(qapp, monkeypatch):
    from ass_style_tool.style_scan import FileStyles
    tab = _tab(monkeypatch)
    tab._file_styles = {
        Path("a [01].ass"): FileStyles(Path("a [01].ass"), {"Default": 48.0},
                                       (1920, 1080))}
    tab.apply_mode_radio.setChecked(True)
    tab.style_picker.set_available(["Default"])
    tab.style_picker.set_selected(["Default"])
    tab.populate(PAIRS)
    tab.mark_rows_pending()
    tab._set_row_result("a [01].mkv", "error")
    assert tab.table.item(0, 5).text() != ""
    tab.populate(PAIRS)      # 重新配對 == 重新掃描的等效路徑
    text = tab.table.item(0, 5).text()
    assert "Default 48 →" in text


# ---------- F2:執行中不得覆寫共用的「預計 / 結果」欄 ----------

def _mid_run_table(monkeypatch):
    """建一個「批次執行中」的表格:一列已有結果、一列仍是「處理中…」。"""
    from unittest.mock import Mock
    tab = _tab(monkeypatch)
    tab.apply_mode_radio.setChecked(True)
    tab.populate(PAIRS)
    tab.mark_rows_pending()
    tab._set_row_result("a [01].mkv", "ok")
    resulted = tab.table.item(0, 5).text()
    assert tab.table.item(2, 5).text() == "處理中…"
    tab._thread = Mock()          # 模擬批次執行緒仍在跑
    return tab, resulted


def test_mode_switch_during_run_does_not_repaint_plan_column(qapp, monkeypatch):
    """執行中切換前處理模式會走 _on_preprocess_mode_changed →
    _recompute_plan_column,整欄重畫會把已定案的結果換成新模式的預測
    文字,PENDING_TEXT 標記也會被蓋掉,_reconcile_stuck_rows() 就再也
    找不到那些列(取消後停在假的預告文字上,跟從未開始處理分不出來)。"""
    tab, resulted = _mid_run_table(monkeypatch)

    tab.scale_mode_radio.setChecked(True)      # 執行中途切模式

    assert tab.table.item(0, 5).text() == resulted
    assert tab.table.item(2, 5).text() == "處理中…"


def test_styles_changed_during_run_does_not_repaint_plan_column(
        qapp, monkeypatch):
    """同一條規則的另一個入口:執行中改目標樣式勾選。"""
    tab, resulted = _mid_run_table(monkeypatch)

    tab.style_picker.set_available(["Default", "CHT"])
    tab.style_picker.set_selected(["CHT"])     # 執行中途改勾選

    assert tab.table.item(0, 5).text() == resulted
    assert tab.table.item(2, 5).text() == "處理中…"


def test_set_row_subtitle_during_run_does_not_repaint_plan_column(
        qapp, monkeypatch):
    """第三個入口:set_row_subtitle() 直接寫格子,沒有經過
    _recompute_plan_column(),所以要各自擋一次。"""
    tab, resulted = _mid_run_table(monkeypatch)

    tab.set_row_subtitle(0, Path("manual.ass"))   # 執行中途手動改配對

    assert tab.table.item(0, 5).text() == resulted


def test_plan_column_still_repaints_when_not_running(qapp, monkeypatch):
    """防護不能過寬:沒有在跑批次時,切模式仍然必須重算整欄,否則畫面會
    留著前一個模式的預告(Task 10 當初修的就是這個)。"""
    tab = _tab(monkeypatch)
    tab.apply_mode_radio.setChecked(True)
    tab.populate(PAIRS)
    before = tab.table.item(0, 5).text()

    tab.direct_mode_radio.setChecked(True)     # 沒有在跑,應該要重算

    assert tab.table.item(0, 5).text() != before
    assert "直接封裝" in tab.table.item(0, 5).text()


# ---------- 回歸:QThread/worker 銷毀時機不再交給 Python GC ----------
#
# 背景:三組背景執行緒(配對掃描、修改既有軌道掃描、封裝批次)原本收尾時
# 是 quit()/wait() 之後直接把 Python 參照設成 None——C++ 端 worker/
# QThread 的實際銷毀時機因此落到 Python 的分代 GC 手上:分頁與執行緒/
# worker 之間的訊號連線構成參照循環,單靠 refcount 歸不了零。GC 動手的
# 時機不可控,可能落在 Qt 正在派送事件的中途,在 CI 上造成間歇性的
# Windows heap corruption(0xc0000374)。
#
# 修法是兩處成對:建立時 thread.finished.connect(worker.deleteLater)
#(worker 在 wait() 回來之前就確定銷毀),收尾時額外呼叫
# thread.deleteLater()(把 QThread 的所有權從 GC 交給 Qt)。這裡直接檢查
# worker 的 C++ 物件在收尾之後是否真的已經銷毀,而不只是 Python 參照被
# 清空——退回舊寫法(只設 = None)的話,這裡會抓到 isValid() 仍是 True
#(因為缺了 thread.finished -> deleteLater 這條線,worker 根本不會在
# wait() 回來前被刪除)。與 test_mkv_tab.py 同一組回歸,道理相同。

def _cpp_object_destroyed(obj) -> bool:
    from shiboken6 import isValid
    return not isValid(obj)


def test_scan_worker_cpp_object_destroyed_after_teardown(
        qapp, monkeypatch, tmp_path):
    import time
    from ass_style_tool.qt.batch_worker import MuxScanWorker

    captured = {}

    def factory(video_folder, subtitle_folder):
        worker = MuxScanWorker(video_folder, subtitle_folder,
                               pair_fn=lambda videos, subs: [],
                               scan_styles_fn=lambda p: None)
        captured["worker"] = worker
        return worker

    monkeypatch.setattr("ass_style_tool.qt.mux_tab.MuxScanWorker", factory)

    tab = _tab(monkeypatch)
    tab.video_edit.setText(str(tmp_path))
    tab.subtitle_edit.setText(str(tmp_path))
    tab._on_scan()

    deadline = time.monotonic() + 5.0
    while tab._scan_thread is not None and time.monotonic() < deadline:
        qapp.processEvents()
    assert tab._scan_thread is None, "配對掃描沒有跑完"

    assert _cpp_object_destroyed(captured["worker"])


def test_track_scan_worker_cpp_object_destroyed_after_teardown(
        qapp, monkeypatch):
    import time
    from ass_style_tool.qt.batch_worker import TrackScanWorker

    captured = {}

    def factory(video_paths, mkvmerge, list_fn=None):
        # list_fn 回傳空清單:_on_track_scan_done() 的 any(...) 檢查會擋下
        # 開啟 ModifyTracksDialog(那是真正的 modal exec(),會卡住測試)。
        worker = TrackScanWorker(video_paths, mkvmerge,
                                 list_fn=lambda p, m: [])
        captured["worker"] = worker
        return worker

    monkeypatch.setattr("ass_style_tool.qt.mux_tab.TrackScanWorker", factory)

    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    tab._on_modify_tracks()

    deadline = time.monotonic() + 5.0
    while tab._track_scan_thread is not None and time.monotonic() < deadline:
        qapp.processEvents()
    assert tab._track_scan_thread is None, "軌道掃描沒有跑完"

    assert _cpp_object_destroyed(captured["worker"])


def test_mux_worker_cpp_object_destroyed_after_teardown(qapp, monkeypatch):
    import time
    from ass_style_tool.mkv_batch import MkvFileReport
    from ass_style_tool.qt.batch_worker import MuxWorker

    captured = {}

    def factory(pairs, meta, operation, tools, output_dir, edits=None):
        def fake_process(pair, meta, operation, tools, out_path=None,
                         progress_cb=None, edits=None):
            return MkvFileReport(pair.video_path, "ok")
        worker = MuxWorker(pairs, meta, operation, tools, output_dir,
                           process_fn=fake_process, edits=edits)
        captured["worker"] = worker
        return worker

    monkeypatch.setattr("ass_style_tool.qt.mux_tab.MuxWorker", factory)

    tab = _tab(monkeypatch)
    tab.populate(PAIRS)
    tab.replace_radio.setChecked(True)     # 免選輸出資料夾
    tab._on_run()

    deadline = time.monotonic() + 5.0
    while tab._thread is not None and time.monotonic() < deadline:
        qapp.processEvents()
    assert tab._thread is None, "封裝沒有跑完"

    assert _cpp_object_destroyed(captured["worker"])


def test_shutdown_clears_batch_and_scan_thread_references(qapp, monkeypatch):
    """shutdown() 原本沒有清 _thread/_worker/_scan_thread/_scan_worker 的
    參照——這些執行緒是被 shutdown() 開頭那個 quit()+wait() 迴圈收掉的,
    _on_finished()/_on_scan_done() 這兩條正常收尾路徑並不會跑,若不在這裡
    補上,會留著指向已銷毀 C++ 物件的空殼 wrapper,之後任何人再去 touch
    它(例如又呼叫一次 shutdown() 裡的 worker.cancel())就會炸
    RuntimeError。_track_scan_* 那組本來就有清(見
    test_shutdown_closes_orphaned_track_scan_dialog),這裡補的是另外
    兩組。"""
    from unittest.mock import Mock
    tab = _tab(monkeypatch)
    thread, worker = Mock(), Mock()
    scan_thread, scan_worker = Mock(), Mock()
    tab._thread = thread
    tab._worker = worker
    tab._scan_thread = scan_thread
    tab._scan_worker = scan_worker

    tab.shutdown()

    thread.quit.assert_called_once()
    thread.wait.assert_called_once()
    scan_thread.quit.assert_called_once()
    scan_thread.wait.assert_called_once()
    assert tab._thread is None
    assert tab._worker is None
    assert tab._scan_thread is None
    assert tab._scan_worker is None
