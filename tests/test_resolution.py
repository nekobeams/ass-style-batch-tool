from __future__ import annotations

from pathlib import Path

from ass_style_tool.resolution import (SPEC_DEFAULT_RES, aspect_mismatch,
                                       compute_scale,
                                       probe_video_resolution,
                                       reference_resolution)


def test_reference_both_valid():
    assert reference_resolution(1920, 1080) == (1920, 1080)


def test_reference_only_x_derives_4_3():
    assert reference_resolution(1280, 0) == (1280, 960)


def test_reference_only_y_derives_4_3():
    assert reference_resolution(0, 720) == (960, 720)


def test_reference_none_uses_spec_default():
    assert reference_resolution(0, 0) == SPEC_DEFAULT_RES == (384, 288)


def test_reference_negative_treated_as_missing():
    assert reference_resolution(-1, -5) == (384, 288)


def test_compute_scale():
    sx, sy = compute_scale(1280, 720, 1920, 1080)
    assert abs(sx - 1280 / 1920) < 1e-9
    assert abs(sy - 720 / 1080) < 1e-9


def test_aspect_mismatch_43_vs_169():
    assert aspect_mismatch((640, 480), (1920, 1080)) is True


def test_aspect_match_same_ratio():
    assert aspect_mismatch((1280, 720), (1920, 1080)) is False


def test_aspect_match_within_tolerance():
    assert aspect_mismatch((1920, 1080), (1919, 1080)) is False


class FakeCompleted:
    def __init__(self, returncode: int, stdout: str = ""):
        self.returncode = returncode
        self.stdout = stdout


def test_probe_parses_output(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.resolution.subprocess.run",
        lambda *a, **k: FakeCompleted(0, "1920,1080\n"),
    )
    assert probe_video_resolution(Path("x.mkv")) == (1920, 1080)


def test_probe_nonzero_exit_returns_none(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.resolution.subprocess.run",
        lambda *a, **k: FakeCompleted(1, ""),
    )
    assert probe_video_resolution(Path("x.mkv")) is None


def test_probe_garbage_output_returns_none(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.resolution.subprocess.run",
        lambda *a, **k: FakeCompleted(0, "N/A\n"),
    )
    assert probe_video_resolution(Path("x.mkv")) is None


def test_probe_oserror_returns_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("ffprobe not found")

    monkeypatch.setattr("ass_style_tool.resolution.subprocess.run", boom)
    assert probe_video_resolution(Path("x.mkv")) is None
