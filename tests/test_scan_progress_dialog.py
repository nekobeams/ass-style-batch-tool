from __future__ import annotations


def test_dialog_starts_indeterminate(qapp):
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    d = ScanProgressDialog()
    # 總數未知 → 不確定狀態(min==max==0)
    assert d.bar.minimum() == 0
    assert d.bar.maximum() == 0
    assert "尋找" in d.label.text()


def test_dialog_switches_to_determinate_on_first_progress(qapp):
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    d = ScanProgressDialog()
    d.set_progress(9, 24)
    assert d.bar.maximum() == 24
    assert d.bar.value() == 9
    assert d.label.text() == "掃描影片 9/24"


def test_dialog_reject_emits_cancelled(qapp):
    from ass_style_tool.qt.scan_progress_dialog import ScanProgressDialog
    d = ScanProgressDialog()
    seen = []
    d.cancelled.connect(lambda: seen.append(True))
    d.reject()                 # 等同按取消 / X / Esc
    assert seen == [True]
