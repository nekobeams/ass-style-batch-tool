from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


class FakeMPV:
    """記錄呼叫的假 mpv 實例。"""

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.commands = []
        self.played = []
        self.pause = False
        self.terminated = False
        self.time_pos = 12.5
        self.duration = 90.0

    def play(self, path):
        self.played.append(path)

    def command(self, *args):
        self.commands.append(args)

    def terminate(self):
        self.terminated = True


def _patch_mpv(monkeypatch, module):
    monkeypatch.setattr("ass_style_tool.qt.player._import_mpv", lambda: module)


def test_unavailable_all_noop(qapp, monkeypatch):
    from ass_style_tool.qt.player import MpvPlayerWidget
    _patch_mpv(monkeypatch, None)
    w = MpvPlayerWidget()
    assert w.available() is False
    assert w.load_video(Path("x.mkv")) is False
    assert w.video_loaded() is False
    # 全部安全 no-op,不得丟例外
    w.show_subtitle(Path("a.ass"))
    w.seek(1.5)
    w.toggle_pause()
    assert w.position() is None
    assert w.duration() is None
    w.shutdown()


def test_load_video_creates_player_and_pauses(qapp, monkeypatch):
    from ass_style_tool.qt.player import MpvPlayerWidget
    fake_module = SimpleNamespace(MPV=FakeMPV)
    _patch_mpv(monkeypatch, fake_module)
    w = MpvPlayerWidget()
    assert w.available() is True
    assert w.load_video(Path("video.mkv")) is True
    assert w.video_loaded() is True
    assert w._mpv.played == ["video.mkv"]
    assert w._mpv.pause is True


def test_show_subtitle_add_then_reload(qapp, monkeypatch):
    from ass_style_tool.qt.player import MpvPlayerWidget
    _patch_mpv(monkeypatch, SimpleNamespace(MPV=FakeMPV))
    w = MpvPlayerWidget()
    w.load_video(Path("v.mkv"))
    w.show_subtitle(Path("p.ass"))
    w.show_subtitle(Path("p.ass"))
    assert w._mpv.commands[0] == ("sub-add", "p.ass", "select")
    assert w._mpv.commands[1] == ("sub-reload",)


def test_seek_and_shutdown(qapp, monkeypatch):
    from ass_style_tool.qt.player import MpvPlayerWidget
    _patch_mpv(monkeypatch, SimpleNamespace(MPV=FakeMPV))
    w = MpvPlayerWidget()
    w.load_video(Path("v.mkv"))
    w._mpv.pause = False
    w.seek(3.25)
    assert ("seek", 3.25, "absolute") in w._mpv.commands
    assert w._mpv.pause is True
    mpv_instance = w._mpv
    w.shutdown()
    assert mpv_instance.terminated is True
    assert w._mpv is None


def test_position_and_duration_read_from_mpv(qapp, monkeypatch):
    from ass_style_tool.qt.player import MpvPlayerWidget
    _patch_mpv(monkeypatch, SimpleNamespace(MPV=FakeMPV))
    w = MpvPlayerWidget()
    w.load_video(Path("v.mkv"))
    assert w.position() == 12.5
    assert w.duration() == 90.0
