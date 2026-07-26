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
    worker.finished.connect(lambda pairs: got.update(pairs=pairs))
    worker.run()
    by_ep = {p.episode: p.status for p in got["pairs"]}
    assert by_ep[1] == "matched"
    assert by_ep[2] == "no_subtitle"


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
    assert seen == [(1, 3), (2, 3), (3, 3)]
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
    assert got["progress"] == []
