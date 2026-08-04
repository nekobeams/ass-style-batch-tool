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


def test_aspect_mismatch_exactly_at_tolerance_is_not_mismatch():
    """相對誤差『剛好等於』tolerance 時不算 mismatch(實作用嚴格 `>`)。

    寫死的浮點字面值(例如 0.05)在二進位浮點下不可靠——實測
    21/20 與 1/1 的相對誤差其實是 0.050000000000000044,不是乾淨的
    0.05,直接拿字面值當 tolerance 測邊界會測到浮點雜訊而非真正的
    邊界行為。這裡改成先用函式本身的公式反推出誤差值,再把它原封
    不動地當 tolerance 丟回去——保證兩邊比較的是同一個浮點數,誤差
    等於 tolerance 時是否真的被視為「不算超標」。
    """
    ref, video = (21, 20), (1, 1)
    ref_ratio = ref[0] / ref[1]
    video_ratio = video[0] / video[1]
    diff = abs(ref_ratio - video_ratio) / video_ratio

    assert aspect_mismatch(ref, video, tolerance=diff) is False


def test_aspect_mismatch_just_above_tolerance_is_mismatch():
    """誤差比 tolerance 大『浮點能表示的最小一格』時,必須算 mismatch。"""
    import math

    ref, video = (21, 20), (1, 1)
    ref_ratio = ref[0] / ref[1]
    video_ratio = video[0] / video[1]
    diff = abs(ref_ratio - video_ratio) / video_ratio
    just_below_diff = math.nextafter(diff, -math.inf)

    assert aspect_mismatch(ref, video, tolerance=just_below_diff) is True


def test_aspect_mismatch_just_below_tolerance_is_not_mismatch():
    """誤差比 tolerance 小『浮點能表示的最小一格』時,不算 mismatch。"""
    import math

    ref, video = (21, 20), (1, 1)
    ref_ratio = ref[0] / ref[1]
    video_ratio = video[0] / video[1]
    diff = abs(ref_ratio - video_ratio) / video_ratio
    just_above_diff = math.nextafter(diff, math.inf)

    assert aspect_mismatch(ref, video, tolerance=just_above_diff) is False


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


def test_probe_uses_bundled_ffprobe_path(monkeypatch):
    """Fix 2:cmd[0] 必須來自 tools.ffprobe_path(),不能寫死 "ffprobe"
    字面字串——打包後 PATH 沒有 {app}\\tools,寫死字串會讓內建的
    ffprobe.exe 永遠找不到(見 tools.ffprobe_path 的 PATH → 內建目錄邏輯)。
    """
    sentinel = Path(r"C:\install\tools\ffprobe.exe")
    monkeypatch.setattr(
        "ass_style_tool.resolution.ffprobe_path", lambda: sentinel)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeCompleted(0, "1920,1080\n")

    monkeypatch.setattr("ass_style_tool.resolution.subprocess.run", fake_run)
    assert probe_video_resolution(Path("x.mkv")) == (1920, 1080)
    assert captured["cmd"][0] == str(sentinel)


def test_ffprobe_available_uses_bundled_path(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.resolution.ffprobe_path", lambda: Path("x/ffprobe.exe"))
    from ass_style_tool.resolution import ffprobe_available
    assert ffprobe_available() is True
    monkeypatch.setattr("ass_style_tool.resolution.ffprobe_path", lambda: None)
    assert ffprobe_available() is False


def test_probe_suppresses_console_window(monkeypatch):
    import subprocess
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return FakeCompleted(0, "1920,1080\n")

    monkeypatch.setattr("ass_style_tool.resolution.subprocess.run", fake_run)
    monkeypatch.setattr("ass_style_tool.subprocess_utils.sys.platform", "win32")
    probe_video_resolution(Path("x.mkv"))
    assert captured.get("creationflags") == subprocess.CREATE_NO_WINDOW
