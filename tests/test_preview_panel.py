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
        self.pos = None      # 目前播放位置(秒)
        self.dur = None      # 總長度(秒)

    def load_video(self, path):
        self.videos.append(Path(path))
        self._loaded = True
        return True

    def position(self):
        return self.pos

    def duration(self):
        return self.dur

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


# ---------- 時間軸 ----------

def test_poll_updates_slider_and_label(qapp, tmp_path):
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path), video_path=Path("v.mkv"))
    player.dur = 120.0        # 2 分鐘
    player.pos = 61.23        # 1:01.23
    panel._poll_playback()
    assert panel.timeline.maximum() == 120000
    assert panel.timeline.value() == 61230
    assert panel.time_label.text() == "0:01:01.23 / 0:02:00.00"
    panel.shutdown()


def test_poll_does_not_move_slider_while_scrubbing(qapp, tmp_path):
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path), video_path=Path("v.mkv"))
    player.dur = 100.0
    player.pos = 10.0
    panel._poll_playback()          # 先定位到 10s
    assert panel.timeline.value() == 10000
    panel._on_slider_pressed()      # 開始拖曳
    player.pos = 50.0               # 播放位置前進(但使用者正在拖)
    panel._poll_playback()
    assert panel.timeline.value() == 10000   # 拖曳中不被輪詢覆蓋
    panel.shutdown()


def test_slider_moved_seeks_live(qapp, tmp_path):
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path), video_path=Path("v.mkv"))
    player.dur = 200.0
    panel._on_slider_moved(45000)   # 拖到 45 秒
    assert player.seeks[-1] == 45.0                 # 即時 seek
    assert "0:00:45.00" in panel.time_label.text()  # 時間文字同步
    panel.shutdown()


def test_slider_released_seeks_and_clears_scrub(qapp, tmp_path):
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path), video_path=Path("v.mkv"))
    player.dur = 200.0
    player.pos = 0.0
    panel._poll_playback()          # 先建立滑桿範圍(0..200000)
    panel._on_slider_pressed()
    panel.timeline.setValue(30000)
    panel._on_slider_released()
    assert panel._scrubbing is False
    assert player.seeks[-1] == 30.0


# ---------- 換算對照讀出 ----------

def test_readout_populates_rows_on_set_media(qapp, tmp_path, monkeypatch):
    import ass_style_tool.qt.preview_panel as pp
    monkeypatch.setattr(pp, "probe_video_resolution", lambda path: None)
    player = FakePlayer()
    panel = _panel(player)                       # DEFAULT_VALUES: 基準 1920x1080
    panel.set_media(_write_sample(tmp_path))     # SAMPLE_ASS 畫布 1280x720
    # scale 1280/1920 = 0.6667 → 字級 72→48、原字幕 Default 40
    labels = [panel.readout_table.item(r, 0).text()
              for r in range(panel.readout_table.rowCount())]
    assert "字級" in labels
    row = labels.index("字級")
    assert panel.readout_table.item(row, 1).text() == "40"   # 原字幕現值
    assert panel.readout_table.item(row, 2).text() == "48"   # 套用後
    assert "1280×720" in panel.readout_mechanism.text()
    panel.shutdown()


def test_readout_no_video_shows_guidance(qapp, tmp_path, monkeypatch):
    import ass_style_tool.qt.preview_panel as pp
    monkeypatch.setattr(pp, "probe_video_resolution", lambda path: None)
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path))
    assert "載入影片" in panel.readout_context_video.text()
    panel.shutdown()


def test_readout_video_aspect_shown(qapp, tmp_path, monkeypatch):
    import ass_style_tool.qt.preview_panel as pp
    monkeypatch.setattr(pp, "probe_video_resolution", lambda path: (1920, 1080))
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path), video_path=Path("v.mkv"))
    # 畫布 1280x720 (16:9) vs 1920x1080 (16:9) → 相符
    assert "比例相符" in panel.readout_context_video.text()
    panel.shutdown()


def test_readout_updates_on_style_change(qapp, tmp_path, monkeypatch):
    import ass_style_tool.qt.preview_panel as pp
    monkeypatch.setattr(pp, "probe_video_resolution", lambda path: None)
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path))
    before = panel.readout_mechanism.text()
    panel._apply_preview()                       # 防抖到期會走的路徑
    assert panel.readout_mechanism.text() == before   # 同一 profile → 穩定
    panel.shutdown()
