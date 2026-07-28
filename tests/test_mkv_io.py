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


def test_list_ass_tracks_suppresses_console_window(monkeypatch):
    import subprocess
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return FakeCompleted(0, FIXTURE.read_text(encoding="utf-8"))

    monkeypatch.setattr("ass_style_tool.mkv_io.subprocess.run", fake_run)
    monkeypatch.setattr("ass_style_tool.subprocess_utils.sys.platform", "win32")
    list_ass_tracks(Path("show.mkv"), Path(r"C:\mkvmerge.exe"))
    assert captured.get("creationflags") == subprocess.CREATE_NO_WINDOW


def test_list_ass_tracks_bad_json_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.mkv_io.subprocess.run",
        lambda cmd, **k: FakeCompleted(0, "not json"),
    )
    assert list_ass_tracks(Path("x.mkv"), Path("mkvmerge")) == []


def test_list_ass_tracks_preserves_chinese_track_name(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.mkv_io.subprocess.run",
        lambda cmd, **k: FakeCompleted(0, FIXTURE.read_text(encoding="utf-8")),
    )
    tracks = list_ass_tracks(Path("show.mkv"), Path("mkvmerge"))
    assert tracks[0].track_name == "繁體中文"
    # 確認呼叫有指定 utf-8 編碼(避免 cp950 解 UTF-8 亂碼/例外)


def test_list_ass_tracks_uses_utf8_encoding(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return FakeCompleted(0, FIXTURE.read_text(encoding="utf-8"))

    monkeypatch.setattr("ass_style_tool.mkv_io.subprocess.run", fake_run)
    list_ass_tracks(Path("x.mkv"), Path("mkvmerge"))
    assert captured.get("encoding") == "utf-8"


from ass_style_tool.mkv_io import (Replacement, build_extract_command,
                                   build_remux_command, parse_progress)


def _track(tid, lang="chi", name="繁中", default=True, forced=False):
    return SubtitleTrack(tid, "S_TEXT/ASS", lang, name, default, forced)


def test_build_extract_command():
    cmd = build_extract_command(
        Path("show.mkv"), 2, Path("out.ass"), Path(r"C:\mkvextract.exe"))
    assert cmd == [r"C:\mkvextract.exe", "show.mkv", "tracks", "2:out.ass"]


def test_build_remux_excludes_replaced_subtitle_ids():
    cmd = build_remux_command(
        Path("show.mkv"), Path("out.mkv"),
        [Replacement(_track(2), Path("styled2.ass"))],
        Path(r"C:\mkvmerge.exe"),
    )
    # 原檔只排除被替換的字幕軌 2
    i = cmd.index("--subtitle-tracks")
    assert cmd[i + 1] == "!2"
    # 原檔在被替換 .ass 之前
    assert cmd.index("show.mkv") < cmd.index("styled2.ass")


def test_build_remux_restores_track_flags():
    cmd = build_remux_command(
        Path("s.mkv"), Path("o.mkv"),
        [Replacement(_track(2, lang="chi", name="繁中", default=True, forced=False),
                     Path("styled.ass"))],
        Path("mkvmerge"),
    )
    joined = " ".join(cmd)
    assert "--language 0:chi" in joined
    assert "--track-name 0:繁中" in joined
    assert "--default-track 0:yes" in joined
    assert "--forced-track 0:no" in joined


def test_build_remux_multiple_replacements_exclude_list():
    cmd = build_remux_command(
        Path("s.mkv"), Path("o.mkv"),
        [Replacement(_track(2), Path("a.ass")),
         Replacement(_track(3), Path("b.ass"))],
        Path("mkvmerge"),
    )
    i = cmd.index("--subtitle-tracks")
    assert cmd[i + 1] == "!2,3"


def test_build_remux_empty_replacements_raises():
    import pytest
    with pytest.raises(ValueError):
        build_remux_command(Path("s.mkv"), Path("o.mkv"), [], Path("mkvmerge"))


def test_build_remux_omits_empty_track_name():
    cmd = build_remux_command(
        Path("s.mkv"), Path("o.mkv"),
        [Replacement(_track(2, name=""), Path("a.ass"))],
        Path("mkvmerge"),
    )
    assert "--track-name" not in cmd


def test_parse_progress():
    assert parse_progress("Progress: 42%") == 42
    assert parse_progress("Progress: 100%") == 100


def test_parse_progress_none():
    assert parse_progress("Multiplexing...") is None
    assert parse_progress("") is None


def test_extract_track_suppresses_console_window(monkeypatch):
    import subprocess
    from ass_style_tool.mkv_io import extract_track
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return FakeCompleted(0, "")

    monkeypatch.setattr("ass_style_tool.mkv_io.subprocess.run", fake_run)
    monkeypatch.setattr("ass_style_tool.subprocess_utils.sys.platform", "win32")
    extract_track(Path("show.mkv"), 2, Path("out.ass"), Path("mkvextract"))
    assert captured.get("creationflags") == subprocess.CREATE_NO_WINDOW


def test_remux_suppresses_console_window(monkeypatch):
    import subprocess
    from ass_style_tool.mkv_io import remux
    captured = {}

    class FakeProc:
        def __init__(self, *a, **kwargs):
            captured.update(kwargs)
            self.stdout = iter([])
            self.returncode = 0

        def wait(self):
            pass

    monkeypatch.setattr("ass_style_tool.mkv_io.subprocess.Popen", FakeProc)
    monkeypatch.setattr("ass_style_tool.subprocess_utils.sys.platform", "win32")
    remux(Path("s.mkv"), Path("o.mkv"),
         [Replacement(_track(2), Path("styled.ass"))], Path("mkvmerge"))
    assert captured.get("creationflags") == subprocess.CREATE_NO_WINDOW


from ass_style_tool.mkv_io import MediaTrack, parse_all_tracks, list_all_tracks


def test_parse_all_tracks_all_types_sorted():
    tracks = parse_all_tracks(_sample())
    assert [t.track_id for t in tracks] == [0, 1, 2, 3, 4]
    assert [t.track_type for t in tracks] == [
        "video", "audio", "subtitles", "subtitles", "subtitles"]


def test_parse_all_tracks_reads_fields():
    audio = parse_all_tracks(_sample())[1]
    assert audio.track_type == "audio"
    assert audio.codec_id == "A_FLAC"
    assert audio.language == "jpn"


def test_list_all_tracks_runs_and_parses(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.mkv_io.subprocess.run",
        lambda cmd, **k: FakeCompleted(0, FIXTURE.read_text(encoding="utf-8")))
    tracks = list_all_tracks(Path("show.mkv"), Path("mkvmerge"))
    assert [t.track_id for t in tracks] == [0, 1, 2, 3, 4]


def test_list_all_tracks_nonzero_returns_empty(monkeypatch):
    monkeypatch.setattr("ass_style_tool.mkv_io.subprocess.run",
                        lambda cmd, **k: FakeCompleted(2, ""))
    assert list_all_tracks(Path("x.mkv"), Path("mkvmerge")) == []


def test_list_all_tracks_oserror_returns_empty(monkeypatch):
    def boom(cmd, **k):
        raise OSError("not found")
    monkeypatch.setattr("ass_style_tool.mkv_io.subprocess.run", boom)
    assert list_all_tracks(Path("x.mkv"), Path("mkvmerge")) == []


# ---------- extract_template_subtitle ----------
# 直接測這裡的接線(選第一條軌、組暫存路徑、傳遞 extract_track 的失敗),
# 不呼叫真的 mkvmerge/mkvextract——list_ass_tracks/extract_track 都用假的
# 函式注入。test_mkv_tab.py 只測到分頁層的訊息,這條軌道選擇/路徑組合的
# 邏輯本身在那邊是整個被 monkeypatch 掉的,完全沒被驗到。

from ass_style_tool.mkv_io import TemplateExtraction, extract_template_subtitle


def test_extract_template_subtitle_picks_first_track(monkeypatch, tmp_path):
    tracks = [_track(2), _track(3)]
    monkeypatch.setattr(
        "ass_style_tool.mkv_io.list_ass_tracks", lambda mkv, mkvmerge: tracks)
    seen = {}

    def fake_extract_track(mkv, track_id, out_path, mkvextract):
        seen["track_id"] = track_id
        seen["out_path"] = out_path
        return True

    monkeypatch.setattr(
        "ass_style_tool.mkv_io.extract_track", fake_extract_track)
    result = extract_template_subtitle(
        Path("show.mkv"), Path("mkvmerge"), Path("mkvextract"), tmp_path)
    assert seen["track_id"] == 2                      # 永遠選第一條,不是 3
    assert seen["out_path"] == tmp_path / "show.template.ass"
    assert result == TemplateExtraction(path=tmp_path / "show.template.ass")


def test_extract_template_subtitle_no_track_returns_no_track_reason(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.mkv_io.list_ass_tracks", lambda mkv, mkvmerge: [])

    def fail_if_called(*a, **k):
        raise AssertionError("沒有字幕軌就不該呼叫 extract_track")

    monkeypatch.setattr(
        "ass_style_tool.mkv_io.extract_track", fail_if_called)
    result = extract_template_subtitle(
        Path("show.mkv"), Path("mkvmerge"), Path("mkvextract"))
    assert result == TemplateExtraction(path=None, error="no_track")


def test_extract_template_subtitle_extraction_failure_returns_extract_failed_reason(
        monkeypatch, tmp_path):
    monkeypatch.setattr(
        "ass_style_tool.mkv_io.list_ass_tracks",
        lambda mkv, mkvmerge: [_track(2)])
    monkeypatch.setattr(
        "ass_style_tool.mkv_io.extract_track",
        lambda mkv, track_id, out_path, mkvextract: False)
    result = extract_template_subtitle(
        Path("show.mkv"), Path("mkvmerge"), Path("mkvextract"), tmp_path)
    assert result == TemplateExtraction(path=None, error="extract_failed")


def test_extract_template_subtitle_defaults_to_system_temp_dir(monkeypatch):
    import tempfile
    monkeypatch.setattr(
        "ass_style_tool.mkv_io.list_ass_tracks",
        lambda mkv, mkvmerge: [_track(2)])
    seen = {}

    def fake_extract_track(mkv, track_id, out_path, mkvextract):
        seen["out_path"] = out_path
        return True

    monkeypatch.setattr(
        "ass_style_tool.mkv_io.extract_track", fake_extract_track)
    extract_template_subtitle(
        Path("show.mkv"), Path("mkvmerge"), Path("mkvextract"))
    assert seen["out_path"] == (
        Path(tempfile.gettempdir()) / "show.template.ass")
