from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_batch import MkvFileReport, MkvTools
from ass_style_tool.mkv_io import SubtitleTrack
from tests.test_profile import make_profile

TOOLS = MkvTools(mkvmerge=Path("mkvmerge.exe"), mkvextract=Path("mkvextract.exe"))


def _track(tid=2):
    return SubtitleTrack(tid, "S_TEXT/ASS", "chi", "繁中", False, False)


def test_scan_worker_lists_tracks(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MkvScanWorker
    (tmp_path / "e1.mkv").write_bytes(b"")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "e2.mkv").write_bytes(b"")
    (tmp_path / "note.txt").write_text("x")

    def fake_list(path, mkvmerge):
        return [_track(2)] if path.name == "e1.mkv" else []

    worker = MkvScanWorker(tmp_path, Path("mkvmerge.exe"), list_fn=fake_list)
    got = {}
    worker.finished.connect(lambda d: got.update(d))
    worker.run()
    names = sorted(p.name for p in got)
    assert names == ["e1.mkv", "e2.mkv"]
    assert [t.track_id for t in got[tmp_path / "e1.mkv"]] == [2]
    assert got[tmp_path / "sub" / "e2.mkv"] == []


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
