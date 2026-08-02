from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_batch import MkvFileReport, MkvTools
from ass_style_tool.mkv_mux import MuxMeta, MuxPair

TOOLS = MkvTools(mkvmerge=Path("mkvmerge.exe"), mkvextract=Path("mkvextract.exe"))
META = MuxMeta(language="chi", track_name="繁中", default=True, forced=False)


def test_scan_worker_pairs_two_folders(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MuxScanWorker
    vdir = tmp_path / "video"
    sdir = tmp_path / "sub"
    vdir.mkdir()
    sdir.mkdir()
    (vdir / "Show [01].mkv").write_bytes(b"")
    (vdir / "Show [02].mkv").write_bytes(b"")
    (sdir / "Show - 01.ass").write_bytes(b"")
    worker = MuxScanWorker(vdir, sdir)
    got = {}
    worker.finished.connect(lambda result: got.update(result=result))
    worker.run()
    by_ep = {p.episode: p.status for p in got["result"].pairs}
    assert by_ep[1] == "matched"
    assert by_ep[2] == "no_subtitle"


def test_scan_worker_scans_styles_for_matched_pairs_only(qapp, tmp_path):
    """樣式解析(scan_styles)在 worker 執行緒裡跑,不留給 GUI 端的
    slot——這裡直接測 worker 本身,不必透過分頁(最終審查 I10)。
    「未配對到字幕的列不能餵給 scan_styles」的過濾也在這裡驗證:這條
    真正的邏輯位置就是 MuxScanWorker.run(),不是 mux_tab 的 slot。"""
    from ass_style_tool.qt.batch_worker import MuxScanWorker
    from ass_style_tool.style_scan import FileStyles
    vdir = tmp_path / "video"
    sdir = tmp_path / "sub"
    vdir.mkdir()
    sdir.mkdir()
    (vdir / "Show [01].mkv").write_bytes(b"")
    (vdir / "Show [02].mkv").write_bytes(b"")
    (sdir / "Show - 01.ass").write_bytes(b"")

    scanned = []

    def fake_scan_styles(path):
        assert path is not None, "scan_styles 不該收到 None(subtitle_path 未過濾)"
        scanned.append(path)
        return FileStyles(path=path, styles={"CHT": 40.0})

    worker = MuxScanWorker(vdir, sdir, scan_styles_fn=fake_scan_styles)
    got = {}
    worker.finished.connect(lambda result: got.update(result=result))
    worker.run()

    result = got["result"]
    assert scanned == [sdir / "Show - 01.ass"]     # 只掃有配對到的那個
    assert set(result.file_styles) == {sdir / "Show - 01.ass"}


def test_scan_worker_all_unmatched_skips_scan_styles(qapp, tmp_path):
    """整批都沒配對到字幕時,scan_styles 完全不該被呼叫。"""
    from ass_style_tool.qt.batch_worker import MuxScanWorker
    vdir = tmp_path / "video"
    sdir = tmp_path / "sub"
    vdir.mkdir()
    sdir.mkdir()
    (vdir / "Show [01].mkv").write_bytes(b"")

    def boom(path):
        raise AssertionError("全部未配對時不該呼叫 scan_styles")

    worker = MuxScanWorker(vdir, sdir, scan_styles_fn=boom)
    got = {}
    worker.finished.connect(lambda result: got.update(result=result))
    worker.run()               # 不應拋例外
    assert got["result"].file_styles == {}


def test_mux_worker_runs_and_reports(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MuxWorker

    def fake_process(pair, meta, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        if progress_cb:
            progress_cb(100)
        if out_path is not None:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(b"x")
        return MkvFileReport(pair.video_path, "ok", ["done"])

    pairs = [
        MuxPair(tmp_path / "a [01].mkv", tmp_path / "a.ass", 1, "matched"),
        MuxPair(tmp_path / "b [02].mkv", tmp_path / "b.ass", 2, "matched"),
    ]
    worker = MuxWorker(pairs, META, None, TOOLS,
                       output_dir=tmp_path / "out", process_fn=fake_process)
    done, pcts = {}, []
    worker.file_progress.connect(pcts.append)
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done == {"ok": 2, "skipped": 0, "error": 0}
    assert 100 in pcts


def test_mux_worker_exception_isolated(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MuxWorker

    def fake_process(pair, meta, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        if pair.episode == 2:
            raise RuntimeError("boom")
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"x")
        return MkvFileReport(pair.video_path, "ok", [])

    pairs = [
        MuxPair(tmp_path / f"e{i} [{i:02d}].mkv", tmp_path / f"s{i}.ass", i,
                "matched") for i in (1, 2, 3)]
    worker = MuxWorker(pairs, META, None, TOOLS,
                       output_dir=tmp_path / "out", process_fn=fake_process)
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done == {"ok": 2, "skipped": 0, "error": 1}   # 不崩、續跑


def test_mux_worker_cancel(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MuxWorker

    def fake_process(pair, meta, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"x")
        return MkvFileReport(pair.video_path, "ok", [])

    pairs = [MuxPair(tmp_path / f"e{i} [{i:02d}].mkv", tmp_path / f"s{i}.ass",
                     i, "matched") for i in (1, 2, 3)]
    worker = MuxWorker(pairs, META, None, TOOLS,
                       output_dir=tmp_path / "out", process_fn=fake_process)
    worker.file_done.connect(lambda n, s: worker.cancel())
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done["ok"] < 3


def test_mux_worker_output_name_collision(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import MuxWorker

    def fake_process(pair, meta, operation, tools, out_path=None,
                     progress_cb=None, **kwargs):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"x")
        return MkvFileReport(pair.video_path, "ok", [])

    pairs = [
        MuxPair(tmp_path / "a" / "show.mkv", tmp_path / "a.ass", 1, "matched"),
        MuxPair(tmp_path / "b" / "show.mkv", tmp_path / "b.ass", 1, "matched"),
    ]
    worker = MuxWorker(pairs, META, None, TOOLS,
                       output_dir=tmp_path / "out", process_fn=fake_process)
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done == {"ok": 1, "skipped": 0, "error": 1}


def test_mux_worker_forwards_edits(qapp):
    from ass_style_tool.qt.batch_worker import MuxWorker
    from ass_style_tool.mkv_mux import MuxMeta, MuxPair
    from ass_style_tool.track_edit import TrackEdit
    captured = {}

    def fake_process(pair, meta, operation, tools, out_path=None,
                     progress_cb=None, edits=None):
        captured["edits"] = edits
        from ass_style_tool.mkv_batch import MkvFileReport
        return MkvFileReport(pair.video_path, "ok")

    pairs = [MuxPair(__import__("pathlib").Path("v.mkv"),
                     __import__("pathlib").Path("s.ass"), 1, "matched")]
    edits = {1: TrackEdit(keep=False)}
    worker = MuxWorker(pairs, MuxMeta(), None, None, None,
                       process_fn=fake_process, edits=edits)
    worker.run()
    assert captured["edits"] == edits


def test_track_scan_worker_emits_progress_and_map(qapp):
    from pathlib import Path
    from ass_style_tool.qt.batch_worker import TrackScanWorker
    from ass_style_tool.mkv_io import MediaTrack

    paths = [Path("a.mkv"), Path("b.mkv"), Path("c.mkv")]

    def fake_list(path, mkvmerge):
        return [MediaTrack(0, "video", "V", "und", "", True, False)]

    worker = TrackScanWorker(paths, Path("mkvmerge.exe"), list_fn=fake_list)
    seen = []
    got = {}
    worker.progress.connect(lambda d, t: seen.append((d, t)))
    worker.finished.connect(lambda m: got.update(m))
    worker.run()
    # (0, 3) 先發出:讓對話框在第一個檔案跑完前就切到確定範圍的進度條(Fix 6)
    assert seen == [(0, 3), (1, 3), (2, 3), (3, 3)]
    assert sorted(p.name for p in got) == ["a.mkv", "b.mkv", "c.mkv"]
    assert got[Path("a.mkv")][0].track_type == "video"


def test_track_scan_worker_cancel_stops_early(qapp):
    from pathlib import Path
    from ass_style_tool.qt.batch_worker import TrackScanWorker

    paths = [Path("a.mkv"), Path("b.mkv"), Path("c.mkv")]
    calls = []

    def fake_list(path, mkvmerge):
        calls.append(path)
        worker.cancel()          # 第一個檔掃完就要求取消
        return []

    worker = TrackScanWorker(paths, Path("mkvmerge.exe"), list_fn=fake_list)
    events = []
    worker.finished.connect(lambda m: events.append("finished"))
    worker.cancelled.connect(lambda: events.append("cancelled"))
    worker.run()
    assert events == ["cancelled"]   # 取消不可發 finished
    assert len(calls) == 1           # 真的提早停,不是跑完才丟棄


def test_track_scan_worker_empty_list_finishes_empty(qapp):
    from pathlib import Path
    from ass_style_tool.qt.batch_worker import TrackScanWorker

    worker = TrackScanWorker([], Path("mkvmerge.exe"), list_fn=lambda p, m: [])
    got = {"finished": None, "progress": []}
    worker.finished.connect(lambda m: got.__setitem__("finished", m))
    worker.progress.connect(lambda a, b: got["progress"].append((a, b)))
    worker.run()
    assert got["finished"] == {}
    # (0, 0) 仍會先發出(Fix 6:進度在迴圈前無條件送一次),即使總數是 0
    assert got["progress"] == [(0, 0)]
