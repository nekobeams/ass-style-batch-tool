from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_batch import MkvFileReport, MkvTools
from ass_style_tool.mkv_io import SubtitleTrack
from tests.test_profile import make_profile

TOOLS = MkvTools(mkvmerge=Path("mkvmerge.exe"), mkvextract=Path("mkvextract.exe"))


def _track(tid=2):
    return SubtitleTrack(tid, "S_TEXT/ASS", "chi", "繁中", False, False)


def test_scan_worker_lists_tracks_for_given_paths(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvScanWorker
    a = tmp_path / "e1.mkv"
    b = tmp_path / "e2.mkv"
    a.write_bytes(b"")
    b.write_bytes(b"")

    def fake_list(path, mkvmerge):
        return [_track(2)] if path.name == "e1.mkv" else []

    worker = MkvScanWorker([a, b], Path("mkvmerge.exe"), list_fn=fake_list)
    got = {}
    worker.finished.connect(lambda d: got.update(d))
    worker.run()
    assert sorted(p.name for p in got) == ["e1.mkv", "e2.mkv"]
    assert [t.track_id for t in got[a]] == [2]
    assert got[b] == []


def test_scan_worker_only_scans_the_paths_it_was_given(qapp, tmp_path):
    """回歸:worker 不再自己 rglob 資料夾,分頁給什麼就掃什麼。

    改版前它遞迴整個資料夾,會把子資料夾與未勾選的檔案一起送進
    mkvmerge -J。
    """
    from ass_style_tool.qt.batch_worker import MkvScanWorker
    wanted = tmp_path / "e1.mkv"
    wanted.write_bytes(b"")
    (tmp_path / "e2.mkv").write_bytes(b"")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "e3.mkv").write_bytes(b"")

    seen = []

    def fake_list(path, mkvmerge):
        seen.append(path)
        return []

    worker = MkvScanWorker([wanted], Path("mkvmerge.exe"), list_fn=fake_list)
    worker.run()
    assert seen == [wanted]


def test_mkv_worker_runs_and_reports(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvWorker

    def fake_process(mkv_path, tracks, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        if progress_cb:
            progress_cb(50)
            progress_cb(100)
        if out_path is not None:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(b"x")
        return MkvFileReport(Path(mkv_path), "ok", ["done"])

    jobs = [(tmp_path / "e1.mkv", [_track()]), (tmp_path / "e2.mkv", [_track()])]
    worker = MkvWorker(jobs, make_profile(), TOOLS,
                       output_dir=tmp_path / "out", process_fn=fake_process)
    done, pcts = {}, []
    worker.file_progress.connect(pcts.append)
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done == {"ok": 2, "skipped": 0, "error": 0}
    assert 100 in pcts


def test_mkv_worker_cancel_stops_between_files(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvWorker

    def fake_process(mkv_path, tracks, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        if out_path is not None:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(b"x")
        return MkvFileReport(Path(mkv_path), "ok", [])

    jobs = [(tmp_path / f"e{i}.mkv", [_track()]) for i in (1, 2, 3)]
    worker = MkvWorker(jobs, make_profile(), TOOLS,
                       output_dir=tmp_path / "out", process_fn=fake_process)
    worker.file_done.connect(lambda n, s: worker.cancel())
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done["ok"] < 3


def test_mkv_worker_process_fn_exception_reports_error_and_continues(qapp, tmp_path):
    """process_fn 對其中一個檔案拋例外:不應讓 worker 崩潰,
    該檔回報 error,批次繼續處理後續檔案,finished 仍會被觸發。"""
    from ass_style_tool.qt.batch_worker import MkvWorker

    def fake_process(mkv_path, tracks, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        if mkv_path.name == "e2.mkv":
            raise RuntimeError("boom")
        if out_path is not None:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(b"x")
        return MkvFileReport(Path(mkv_path), "ok", [])

    jobs = [(tmp_path / f"e{i}.mkv", [_track()]) for i in (1, 2, 3)]
    worker = MkvWorker(jobs, make_profile(), TOOLS,
                       output_dir=tmp_path / "out", process_fn=fake_process)
    statuses = []
    worker.file_done.connect(lambda n, s: statuses.append((n, s)))
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()  # 不應拋出例外
    assert done == {"ok": 2, "skipped": 0, "error": 1}
    assert ("e2.mkv", "error") in statuses
    assert ("e1.mkv", "ok") in statuses
    assert ("e3.mkv", "ok") in statuses   # 批次繼續處理後續檔案


def test_mkv_worker_output_name_collision(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvWorker

    def fake_process(mkv_path, tracks, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"x")
        return MkvFileReport(Path(mkv_path), "ok", [])

    a = tmp_path / "a" / "show.mkv"
    b = tmp_path / "b" / "show.mkv"      # 同名不同資料夾
    jobs = [(a, [_track()]), (b, [_track()])]
    worker = MkvWorker(jobs, make_profile(), TOOLS,
                       output_dir=tmp_path / "out", process_fn=fake_process)
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done == {"ok": 1, "skipped": 0, "error": 1}   # 第二個衝突報錯


def test_mkv_worker_replace_original_mode_no_collision_check(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvWorker

    def fake_process(mkv_path, tracks, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        assert out_path is None            # 取代原檔模式
        return MkvFileReport(Path(mkv_path), "ok", [])

    a = tmp_path / "a" / "show.mkv"
    b = tmp_path / "b" / "show.mkv"
    worker = MkvWorker([(a, [_track()]), (b, [_track()])], make_profile(),
                       TOOLS, output_dir=None, process_fn=fake_process)
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done == {"ok": 2, "skipped": 0, "error": 0}


def test_scan_worker_emits_progress_per_file(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvScanWorker
    paths = []
    for name in ("e1.mkv", "e2.mkv", "e3.mkv"):
        p = tmp_path / name
        p.write_bytes(b"")
        paths.append(p)
    worker = MkvScanWorker(paths, Path("mkvmerge.exe"), list_fn=lambda p, m: [])
    seen = []
    worker.progress.connect(lambda done, total: seen.append((done, total)))
    worker.run()
    # 開頭那筆 (0, 3) 讓進度對話框立刻切到確定範圍,不必等第一檔掃完
    assert seen == [(0, 3), (1, 3), (2, 3), (3, 3)]


def test_scan_worker_cancel_stops_early_and_emits_cancelled(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvScanWorker
    paths = []
    for name in ("e1.mkv", "e2.mkv", "e3.mkv"):
        p = tmp_path / name
        p.write_bytes(b"")
        paths.append(p)
    calls = []

    def fake_list(path, mkvmerge):
        calls.append(path)
        worker.cancel()          # 第一個檔掃完就要求取消
        return []

    worker = MkvScanWorker(paths, Path("mkvmerge.exe"), list_fn=fake_list)
    events = []
    worker.finished.connect(lambda d: events.append("finished"))
    worker.cancelled.connect(lambda: events.append("cancelled"))
    worker.run()
    assert events == ["cancelled"]   # 取消不可發 finished
    assert len(calls) == 1           # 真的提早停,不是跑完才丟棄


def test_scan_worker_empty_list_finishes_empty(qapp):
    from ass_style_tool.qt.batch_worker import MkvScanWorker
    worker = MkvScanWorker([], Path("mkvmerge.exe"), list_fn=lambda p, m: [])
    got = {"finished": None, "progress": []}
    worker.finished.connect(lambda d: got.__setitem__("finished", d))
    worker.progress.connect(lambda a, b: got["progress"].append((a, b)))
    worker.run()
    assert got["finished"] == {}
    assert got["progress"] == [(0, 0)]
