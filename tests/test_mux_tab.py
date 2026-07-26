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
