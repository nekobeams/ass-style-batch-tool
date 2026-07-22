from __future__ import annotations

from ass_style_tool.preview_readout import (OriginalValues, ReadoutData,
                                            build_readout)
from tests.test_profile import make_profile


def _orig():
    # 對應 SAMPLE_ASS 的 Default: fontsize 40, outline 2, shadow 1, margin 10/10/10
    return OriginalValues(fontsize=40.0, outline=2.0, shadow=1.0,
                          margin_l=10, margin_r=10, margin_v=10)


def test_build_readout_rows_original_and_applied():
    # 基準 1920x1080,畫布 640x360 → scale 0.3333
    data = build_readout(make_profile(), 640, 360, _orig(),
                         "e01.ass", None, None)
    assert data.missing_message == ""
    by_label = {r.label: (r.original, r.applied) for r in data.rows}
    assert by_label["字級"] == ("40", "24")
    assert by_label["外框"] == ("2", "1.2")
    assert by_label["陰影"] == ("1", "0.33")
    assert by_label["邊界 V"] == ("10", "8")


def test_build_readout_mechanism_mentions_base_canvas_scale():
    data = build_readout(make_profile(), 640, 360, _orig(),
                         "e01.ass", None, None)
    assert "1920×1080" in data.mechanism
    assert "640×360" in data.mechanism
    assert "0.333" in data.mechanism


def test_build_readout_no_video_shows_guidance():
    data = build_readout(make_profile(), 640, 360, _orig(),
                         "e01.ass", None, None)
    assert "載入影片" in data.context_video
    assert data.aspect_warning is False


def test_build_readout_video_aspect_match():
    # 畫布 1280x720 (16:9),影片 1920x1080 (16:9) → 相符
    data = build_readout(make_profile(), 1280, 720, _orig(),
                         "e01.ass", "e01.mkv", (1920, 1080))
    assert "比例相符" in data.context_video
    assert data.aspect_warning is False


def test_build_readout_video_aspect_mismatch():
    # 畫布 1280x720 (16:9),影片 1440x1080 (4:3) → 不符
    data = build_readout(make_profile(), 1280, 720, _orig(),
                         "e01.ass", "e01.mkv", (1440, 1080))
    assert data.aspect_warning is True
    assert "比例不符" in data.context_video


def test_build_readout_target_style_missing():
    data = build_readout(make_profile(target_style_names=["字幕"]),
                         640, 360, None, "e01.ass", None, None)
    assert data.rows == []
    assert "字幕" in data.missing_message
    assert "略過" in data.missing_message
