from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QWidget

from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values


class FakePlayer(QWidget):
    """假播放器;必須是 QWidget 才能被面板 addWidget。"""

    def __init__(self):
        super().__init__()
        self.videos = []
        self.subtitles = []
        self.seeks = []
        self.paused_toggles = 0
        self.shut = False
        self._loaded = False

    def load_video(self, path):
        self.videos.append(Path(path))
        self._loaded = True
        return True

    def video_loaded(self):
        return self._loaded

    def show_subtitle(self, path):
        self.subtitles.append(Path(path))

    def seek(self, seconds):
        self.seeks.append(seconds)

    def toggle_pause(self):
        self.paused_toggles += 1

    def shutdown(self):
        self.shut = True


def _write_sample(tmp_path: Path) -> Path:
    from tests.test_ass_style import SAMPLE_ASS
    p = tmp_path / "e01.ass"
    p.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    return p


def _panel(player):
    from ass_style_tool.qt.preview_panel import PreviewPanel
    return PreviewPanel(lambda: profile_from_values(DEFAULT_VALUES),
                        player=player)


def test_set_media_renders_preview_and_lists_lines(qapp, tmp_path):
    player = FakePlayer()
    panel = _panel(player)
    sub = _write_sample(tmp_path)
    panel.set_media(sub, video_path=Path("v.mkv"))
    assert player.videos == [Path("v.mkv")]
    assert len(player.subtitles) == 1          # 立即產生一次預覽
    assert player.subtitles[0].exists()        # 暫存 .ass 真的寫出
    assert panel.line_list.count() == 2        # SAMPLE_ASS 兩個 Dialogue
    panel.shutdown()


def test_set_media_without_video_lists_but_no_show(qapp, tmp_path):
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path))
    assert player.subtitles == []              # 沒影片就不叫 show_subtitle
    assert panel.line_list.count() == 2
    panel.shutdown()


def test_on_style_changed_starts_debounce(qapp, tmp_path):
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path), video_path=Path("v.mkv"))
    assert panel._debounce.isActive() is False
    panel.on_style_changed()
    assert panel._debounce.isActive() is True
    panel._debounce.stop()
    panel._apply_preview()                     # 直接呼叫防抖到期的行為
    assert len(player.subtitles) == 2
    panel.shutdown()


def test_invalid_profile_skips_preview(qapp, tmp_path):
    player = FakePlayer()
    from ass_style_tool.qt.preview_panel import PreviewPanel

    def bad_profile():
        raise ValueError("欄位無效")

    panel = PreviewPanel(bad_profile, player=player)
    panel.set_media(_write_sample(tmp_path), video_path=Path("v.mkv"))
    assert player.subtitles == []              # 無效欄位不預覽、不丟例外
    panel.shutdown()


def test_line_click_seeks(qapp, tmp_path):
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path), video_path=Path("v.mkv"))
    item = panel.line_list.item(0)             # SAMPLE_ASS 第一句 0:00:01.00
    panel._on_line_clicked(item)
    assert player.seeks == [1.0]
    panel.shutdown()


def test_shutdown_cleans_temp(qapp, tmp_path):
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path), video_path=Path("v.mkv"))
    temp = panel._temp_ass
    assert temp.exists()
    panel.shutdown()
    assert player.shut is True
    assert not temp.exists()
