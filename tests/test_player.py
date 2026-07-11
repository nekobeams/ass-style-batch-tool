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
    subs = [c for c in w._mpv.commands if c and c[0] in ("sub-add", "sub-reload")]
    assert subs[0] == ("sub-add", "p.ass", "select")
    assert subs[1] == ("sub-reload",)


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


def test_click_toggles_pause(qapp, monkeypatch):
    from PySide6.QtCore import QPointF, Qt, QEvent
    from PySide6.QtGui import QMouseEvent
    from ass_style_tool.qt.player import MpvPlayerWidget
    _patch_mpv(monkeypatch, SimpleNamespace(MPV=FakeMPV))
    w = MpvPlayerWidget()
    w.load_video(Path("v.mkv"))
    assert w._mpv.pause is True
    event = QMouseEvent(QEvent.MouseButtonPress, QPointF(10, 10),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    w.mousePressEvent(event)
    assert w._mpv.pause is False   # 點畫面 → 播放/暫停切換


def test_space_and_arrow_keys(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent, QKeySequence
    from PySide6.QtCore import QEvent
    from ass_style_tool.qt.player import MpvPlayerWidget
    _patch_mpv(monkeypatch, SimpleNamespace(MPV=FakeMPV))
    w = MpvPlayerWidget()
    w.load_video(Path("v.mkv"))

    def key(k):
        return QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier)

    w.keyPressEvent(key(Qt.Key_Space))
    assert w._mpv.pause is False                        # 空白 → 播放
    w.keyPressEvent(key(Qt.Key_Right))
    assert ("seek", 10, "relative") in w._mpv.commands  # → 進 10 秒
    w.keyPressEvent(key(Qt.Key_Left))
    assert ("seek", -10, "relative") in w._mpv.commands  # ← 退 10 秒
    # 相對 seek 不可改變播放狀態
    assert w._mpv.pause is False


def test_seek_relative_noop_without_video(qapp, monkeypatch):
    from ass_style_tool.qt.player import MpvPlayerWidget
    _patch_mpv(monkeypatch, None)
    w = MpvPlayerWidget()
    w.seek_relative(10)   # 安全 no-op,不丟例外


def test_focus_policy_allows_keyboard(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from ass_style_tool.qt.player import MpvPlayerWidget
    _patch_mpv(monkeypatch, SimpleNamespace(MPV=FakeMPV))
    w = MpvPlayerWidget()
    assert w.focusPolicy() == Qt.StrongFocus   # 點擊即取得鍵盤焦點
