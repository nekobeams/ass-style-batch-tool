from __future__ import annotations

import json
from pathlib import Path

from ass_style_tool.mkv_io import (SubtitleTrack, list_ass_tracks,
                                   parse_ass_tracks)

FIXTURE = Path(__file__).parent / "fixtures" / "mkvmerge_identify_sample.json"


def _sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_filters_only_ass_tracks():
    tracks = parse_ass_tracks(_sample())
    assert [t.track_id for t in tracks] == [2, 3]  # SRT(4)被排除


def test_parse_reads_track_metadata():
    t = parse_ass_tracks(_sample())[0]
    assert t.track_id == 2
    assert t.codec_id == "S_TEXT/ASS"
    assert t.language == "chi"
    assert t.track_name == "繁體中文"
    assert t.default is True
    assert t.forced is False


def test_parse_includes_ssa():
    data = {"tracks": [{
        "id": 5, "type": "subtitles",
        "properties": {"codec_id": "S_TEXT/SSA", "language": "und"}
    }]}
    tracks = parse_ass_tracks(data)
    assert len(tracks) == 1
    assert tracks[0].codec_id == "S_TEXT/SSA"


def test_parse_missing_optional_fields_defaults():
    data = {"tracks": [{
        "id": 6, "type": "subtitles",
        "properties": {"codec_id": "S_TEXT/ASS"}
    }]}
    t = parse_ass_tracks(data)[0]
    assert t.language == "und"      # 缺 language 預設 und
    assert t.track_name == ""       # 缺 track_name 預設空字串
    assert t.default is False
    assert t.forced is False


def test_parse_empty_when_no_tracks_key():
    assert parse_ass_tracks({}) == []


class FakeCompleted:
    def __init__(self, returncode: int, stdout: str):
        self.returncode = returncode
        self.stdout = stdout


def test_list_ass_tracks_runs_mkvmerge(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeCompleted(0, FIXTURE.read_text(encoding="utf-8"))

    monkeypatch.setattr("ass_style_tool.mkv_io.subprocess.run", fake_run)
    tracks = list_ass_tracks(Path("show.mkv"), Path(r"C:\mkvmerge.exe"))
    assert [t.track_id for t in tracks] == [2, 3]
    assert captured["cmd"][0] == r"C:\mkvmerge.exe"
    assert "-J" in captured["cmd"]
    assert captured["cmd"][-1] == "show.mkv"


def test_list_ass_tracks_nonzero_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.mkv_io.subprocess.run",
        lambda cmd, **k: FakeCompleted(2, ""),
    )
    assert list_ass_tracks(Path("x.mkv"), Path("mkvmerge")) == []


def test_list_ass_tracks_oserror_returns_empty(monkeypatch):
    def boom(cmd, **k):
        raise OSError("not found")

    monkeypatch.setattr("ass_style_tool.mkv_io.subprocess.run", boom)
    assert list_ass_tracks(Path("x.mkv"), Path("mkvmerge")) == []


def test_list_ass_tracks_bad_json_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.mkv_io.subprocess.run",
        lambda cmd, **k: FakeCompleted(0, "not json"),
    )
    assert list_ass_tracks(Path("x.mkv"), Path("mkvmerge")) == []
