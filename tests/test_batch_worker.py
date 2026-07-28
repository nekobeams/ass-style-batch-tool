"""tests for batch_worker module."""
import pytest


# ---------- ScanWorker 進度與取消 ----------

def test_scan_worker_forwards_progress_and_cancel(monkeypatch, tmp_path):
    from ass_style_tool.qt.batch_worker import ScanWorker

    captured = {}

    def fake_scan_folder(folder, *, progress=None, should_cancel=None):
        captured["folder"] = folder
        progress(1, 2)
        captured["cancelled_before"] = should_cancel()
        return "SCAN"

    monkeypatch.setattr("ass_style_tool.batch_runner.scan_folder",
                        fake_scan_folder)
    worker = ScanWorker(tmp_path)
    seen_progress = []
    worker.progress.connect(lambda d, t: seen_progress.append((d, t)))
    results = []
    worker.finished.connect(results.append)

    worker.cancel()          # 開跑前就取消,should_cancel 必須回報 True
    worker.run()

    assert captured["folder"] == tmp_path
    assert captured["cancelled_before"] is True
    assert seen_progress == [(1, 2)]
    assert results == ["SCAN"]
