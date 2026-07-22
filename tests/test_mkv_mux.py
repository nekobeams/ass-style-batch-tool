from __future__ import annotations

from pathlib import Path

from ass_style_tool.mkv_batch import MkvTools
from ass_style_tool.mkv_mux import (MuxMeta, MuxPair, build_mux_command,
                                    pair_for_mux, process_mux)
from ass_style_tool.scale_engine import ScaleOptions
from tests.test_ass_style import SAMPLE_ASS
from tests.test_profile import make_profile

TOOLS = MkvTools(mkvmerge=Path("mkvmerge.exe"), mkvextract=Path("mkvextract.exe"))


# ---------- 配對 ----------

def test_pair_matches_by_episode():
    videos = [Path("[G] Show [01].mkv"), Path("[G] Show [02].mkv")]
    subs = [Path("[X] Show - 02.ass"), Path("[X] Show - 01.ass")]
    pairs = {p.video_path: p for p in pair_for_mux(videos, subs)}
    assert pairs[Path("[G] Show [01].mkv")].subtitle_path == Path("[X] Show - 01.ass")
    assert pairs[Path("[G] Show [01].mkv")].status == "matched"
    assert pairs[Path("[G] Show [02].mkv")].subtitle_path == Path("[X] Show - 02.ass")


def test_pair_no_subtitle():
    pairs = pair_for_mux([Path("a [03].mkv")], [Path("b [04].ass")])
    assert pairs[0].status == "no_subtitle"
    assert pairs[0].subtitle_path is None


def test_pair_no_episode():
    pairs = pair_for_mux([Path("movie.mkv")], [Path("x [01].ass")])
    assert pairs[0].status == "no_episode"


def test_pair_ambiguous_multiple_subs():
    pairs = pair_for_mux(
        [Path("a [01].mkv")],
        [Path("a [01].tc.ass"), Path("a [01].sc.ass")])
    assert pairs[0].status == "ambiguous"
    assert pairs[0].subtitle_path is None


# ---------- build_mux_command ----------

def _meta(**kw):
    base = dict(language="chi", track_name="繁中", default=True, forced=False)
    base.update(kw)
    return MuxMeta(**base)


def test_build_mux_command_basic():
    cmd = build_mux_command(
        Path("show.mkv"), Path("show.ass"), Path("out.mkv"),
        _meta(), Path("mkvmerge.exe"))
    assert cmd[:3] == ["mkvmerge.exe", "-o", "out.mkv"]
    # 影片在字幕之前
    assert cmd.index("show.mkv") < cmd.index("show.ass")
    joined = " ".join(cmd)
    assert "--language 0:chi" in joined
    assert "--track-name 0:繁中" in joined
    assert "--default-track 0:yes" in joined
    assert "--forced-track 0:no" in joined


def test_build_mux_command_omits_empty_track_name():
    cmd = build_mux_command(
        Path("s.mkv"), Path("s.ass"), Path("o.mkv"),
        _meta(track_name=""), Path("mkvmerge"))
    assert "--track-name" not in cmd


# ---------- process_mux ----------

def _write_ass(tmp_path, name="sub.ass"):
    p = tmp_path / name
    p.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    return p


def test_process_mux_direct_outdir(tmp_path):
    sub = _write_ass(tmp_path)
    calls = {}

    def fake_mux(video, subtitle, out, meta, mkvmerge, progress_cb=None, source_flags=None):
        calls["subtitle"] = Path(subtitle)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"muxed")
        if progress_cb:
            progress_cb(100)
        return True

    pair = MuxPair(Path("show.mkv"), sub, 1, "matched")
    out = tmp_path / "out" / "show.mkv"
    report = process_mux(pair, _meta(), None, TOOLS, out_path=out,
                         mux_fn=fake_mux)
    assert report.status == "ok"
    assert calls["subtitle"] == sub          # 原字幕直封
    assert out.exists()


def test_process_mux_with_style_transforms_first(tmp_path):
    sub = _write_ass(tmp_path)
    seen = {}

    def fake_mux(video, subtitle, out, meta, mkvmerge, progress_cb=None, source_flags=None):
        seen["subtitle"] = Path(subtitle)
        seen["text"] = Path(subtitle).read_text(encoding="utf-8-sig")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"x")
        return True

    pair = MuxPair(Path("show.mkv"), sub, 1, "matched")
    out = tmp_path / "out" / "show.mkv"
    report = process_mux(pair, _meta(), make_profile(), TOOLS, out_path=out,
                         mux_fn=fake_mux)
    assert report.status == "ok"
    # 封進去的是轉換後的暫存檔(非原字幕)
    assert seen["subtitle"] != sub
    import pysubs2
    styled = pysubs2.SSAFile.from_string(seen["text"])
    assert styled.styles["Default"].fontname == "思源黑體 CN"


def test_process_mux_scale_operation(tmp_path):
    sub = _write_ass(tmp_path)
    seen = {}

    def fake_mux(video, subtitle, out, meta, mkvmerge, progress_cb=None, source_flags=None):
        seen["text"] = Path(subtitle).read_text(encoding="utf-8-sig")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"x")
        return True

    pair = MuxPair(Path("show.mkv"), sub, 1, "matched")
    process_mux(pair, _meta(), ScaleOptions(factor=2), TOOLS,
                out_path=tmp_path / "o" / "show.mkv", mux_fn=fake_mux)
    assert "Style: Default,Arial,80," in seen["text"]


def test_process_mux_style_no_match_muxes_original(tmp_path):
    sub = _write_ass(tmp_path)
    seen = {}

    def fake_mux(video, subtitle, out, meta, mkvmerge, progress_cb=None, source_flags=None):
        seen["subtitle"] = Path(subtitle)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"x")
        return True

    pair = MuxPair(Path("show.mkv"), sub, 1, "matched")
    report = process_mux(pair, _meta(),
                         make_profile(target_style_names=["沒有這個"]),
                         TOOLS, out_path=tmp_path / "o" / "show.mkv",
                         mux_fn=fake_mux)
    assert report.status == "ok"
    assert seen["subtitle"] == sub     # 無匹配 → 封原字幕


def test_process_mux_no_subtitle_is_skipped(tmp_path):
    pair = MuxPair(Path("show.mkv"), None, 1, "no_subtitle")
    report = process_mux(pair, _meta(), None, TOOLS,
                         out_path=tmp_path / "o.mkv",
                         mux_fn=lambda *a, **k: True)
    assert report.status == "skipped"


def test_process_mux_mux_fail_is_error(tmp_path):
    sub = _write_ass(tmp_path)
    pair = MuxPair(Path("show.mkv"), sub, 1, "matched")
    report = process_mux(pair, _meta(), None, TOOLS,
                         out_path=tmp_path / "o" / "show.mkv",
                         mux_fn=lambda *a, **k: False)
    assert report.status == "error"


def test_process_mux_replace_verify_and_swap(tmp_path):
    video = tmp_path / "show.mkv"
    video.write_bytes(b"ORIGINAL")
    sub = _write_ass(tmp_path)

    def fake_mux(v, s, out, meta, mkvmerge, progress_cb=None, source_flags=None):
        Path(out).write_bytes(b"MUXED")
        return True

    pair = MuxPair(video, sub, 1, "matched")
    report = process_mux(pair, _meta(), None, TOOLS, out_path=None,
                         mux_fn=fake_mux, verify_fn=lambda p, m: True)
    assert report.status == "ok"
    assert video.read_bytes() == b"MUXED"
    assert not video.with_name(video.name + ".tmp.mkv").exists()


def test_process_mux_replace_verify_fail_keeps_original(tmp_path):
    video = tmp_path / "show.mkv"
    video.write_bytes(b"ORIGINAL")
    sub = _write_ass(tmp_path)

    def fake_mux(v, s, out, meta, mkvmerge, progress_cb=None, source_flags=None):
        Path(out).write_bytes(b"BROKEN")
        return True

    pair = MuxPair(video, sub, 1, "matched")
    report = process_mux(pair, _meta(), None, TOOLS, out_path=None,
                         mux_fn=fake_mux, verify_fn=lambda p, m: False)
    assert report.status == "error"
    assert video.read_bytes() == b"ORIGINAL"
    assert not video.with_name(video.name + ".tmp.mkv").exists()


def test_default_mux_suppresses_console_window(monkeypatch, tmp_path):
    import subprocess
    from ass_style_tool.mkv_mux import _default_mux
    captured = {}

    class FakeProc:
        def __init__(self, *a, **kwargs):
            captured.update(kwargs)
            self.stdout = iter([])
            self.returncode = 0

        def wait(self):
            pass

    monkeypatch.setattr("ass_style_tool.mkv_mux.subprocess.Popen", FakeProc)
    monkeypatch.setattr("ass_style_tool.subprocess_utils.sys.platform", "win32")
    _default_mux(tmp_path / "v.mkv", tmp_path / "s.ass", tmp_path / "o.mkv",
                _meta(), Path("mkvmerge"))
    assert captured.get("creationflags") == subprocess.CREATE_NO_WINDOW


def test_build_mux_command_source_flags_before_video():
    from ass_style_tool.mkv_mux import build_mux_command
    cmd = build_mux_command(
        Path("v.mkv"), Path("s.ass"), Path("o.mkv"), _meta(),
        Path("mkvmerge"), source_flags=["--no-audio", "--subtitle-tracks", "2"])
    assert cmd.index("--no-audio") > cmd.index("o.mkv")      # 在 -o out 之後
    assert cmd.index("--no-audio") < cmd.index("v.mkv")      # 在 video 之前
    assert cmd.index("--subtitle-tracks") < cmd.index("v.mkv")


def test_build_mux_command_no_source_flags_unchanged():
    from ass_style_tool.mkv_mux import build_mux_command
    cmd = build_mux_command(Path("v.mkv"), Path("s.ass"), Path("o.mkv"),
                            _meta(), Path("mkvmerge"))
    # video 緊接在 -o out 之後(無來源旗標)
    assert cmd[cmd.index("o.mkv") + 1] == "v.mkv"


def test_process_mux_applies_track_edits(tmp_path):
    from ass_style_tool.mkv_io import MediaTrack
    from ass_style_tool.track_edit import TrackEdit
    captured = {}

    def fake_mux(v, s, out, meta, mkvmerge, progress_cb=None, source_flags=None):
        captured["flags"] = source_flags
        Path(out).write_bytes(b"MUXED")
        return True

    def fake_tracks(video, mkvmerge):
        return [MediaTrack(0, "video", "V", "und", "", True, False),
                MediaTrack(1, "audio", "A", "jpn", "", True, False),
                MediaTrack(2, "subtitles", "S", "chi", "", False, False)]

    video = tmp_path / "show.mkv"
    video.write_bytes(b"X")
    pair = MuxPair(video, _write_ass(tmp_path), 1, "matched")
    report = process_mux(pair, _meta(), None, TOOLS,
                         out_path=tmp_path / "o" / "show.mkv",
                         mux_fn=fake_mux, edits={1: TrackEdit(keep=False)},
                         track_list_fn=fake_tracks)
    assert report.status == "ok"
    assert "--no-audio" in captured["flags"]


def test_process_mux_no_edits_empty_flags(tmp_path):
    captured = {}

    def fake_mux(v, s, out, meta, mkvmerge, progress_cb=None, source_flags=None):
        captured["flags"] = source_flags
        Path(out).write_bytes(b"M")
        return True

    video = tmp_path / "show.mkv"
    video.write_bytes(b"X")
    pair = MuxPair(video, _write_ass(tmp_path), 1, "matched")
    process_mux(pair, _meta(), None, TOOLS, out_path=tmp_path / "o" / "show.mkv",
                mux_fn=fake_mux)
    assert captured["flags"] == []


def test_process_mux_track_scan_failure_degrades(tmp_path):
    from ass_style_tool.track_edit import TrackEdit
    captured = {}

    def fake_mux(v, s, out, meta, mkvmerge, progress_cb=None, source_flags=None):
        captured["flags"] = source_flags
        Path(out).write_bytes(b"M")
        return True

    def boom(video, mkvmerge):
        raise OSError("scan fail")

    video = tmp_path / "show.mkv"
    video.write_bytes(b"X")
    pair = MuxPair(video, _write_ass(tmp_path), 1, "matched")
    process_mux(pair, _meta(), None, TOOLS, out_path=tmp_path / "o" / "show.mkv",
                mux_fn=fake_mux, edits={1: TrackEdit(keep=False)},
                track_list_fn=boom)
    assert captured["flags"] == []
