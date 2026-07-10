from __future__ import annotations

from pathlib import Path

import pytest

from ass_style_tool.batch_runner import ScanResult
from ass_style_tool.episode_match import MatchResult
from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values
from ass_style_tool.scale_engine import ScaleError


def test_scale_panel_factor_options(qapp):
    from ass_style_tool.qt.scale_panel import ScalePanel
    panel = ScalePanel()
    panel.factor_radio.setChecked(True)
    panel.factor_edit.setText("1.25")
    options = panel.get_options()
    assert options.factor == 1.25
    assert options.target_size is None
    assert options.scale_decorations is True
    assert options.scale_inline_fs is True
    assert options.scale_fscxy is False


def test_scale_panel_target_options(qapp):
    from ass_style_tool.qt.scale_panel import ScalePanel
    panel = ScalePanel()
    panel.target_radio.setChecked(True)
    panel.target_edit.setText("72")
    panel.base_edit.setText("  ")
    panel.fscxy_check.setChecked(True)
    options = panel.get_options()
    assert options.target_size == 72.0
    assert options.base_style == "Default"  # 空白 fallback
    assert options.scale_fscxy is True


def test_scale_panel_invalid_number_raises(qapp):
    from ass_style_tool.qt.scale_panel import ScalePanel
    panel = ScalePanel()
    panel.factor_radio.setChecked(True)
    panel.factor_edit.setText("abc")
    with pytest.raises(ScaleError):
        panel.get_options()


def test_mode_switch_toggles_scale_panel(qapp):
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    assert tab.apply_mode_radio.isChecked()
    assert tab.scale_panel.isHidden() is True     # 預設隱藏
    tab.scale_mode_radio.setChecked(True)
    assert tab.scale_panel.isHidden() is False
    assert tab.run_button.text() == "開始縮放"
    tab.apply_mode_radio.setChecked(True)
    assert tab.scale_panel.isHidden() is True
    assert tab.run_button.text() == "開始套用樣式"


def test_scale_worker_scales_files(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import ScaleWorker
    from ass_style_tool.scale_engine import ScaleOptions
    from tests.test_ass_style import SAMPLE_ASS
    sub = tmp_path / "a [01].ass"
    sub.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    scan = ScanResult(matches=[
        MatchResult(sub_path=sub, episode=1, status="no_video")],
        warnings=[])
    worker = ScaleWorker(scan, ScaleOptions(factor=2),
                         output_dir=tmp_path / "out")
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done == {"ok": 1, "skipped": 0, "error": 0}
    out_text = (tmp_path / "out" / "a [01].ass").read_text(encoding="utf-8-sig")
    assert "Style: Default,Arial,80," in out_text   # 40*2
    assert "Style: OP,Comic Sans MS,120," in out_text  # 60*2


def test_scale_worker_error_isolated(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import ScaleWorker
    from ass_style_tool.scale_engine import ScaleOptions
    bad = tmp_path / "bad [01].ass"
    bad.write_text("not a subtitle", encoding="utf-8")
    scan = ScanResult(matches=[
        MatchResult(sub_path=bad, episode=1, status="no_video")],
        warnings=[])
    worker = ScaleWorker(scan, ScaleOptions(factor=2),
                         output_dir=tmp_path / "out")
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    assert done == {"ok": 0, "skipped": 0, "error": 1}
