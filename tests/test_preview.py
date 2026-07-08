from __future__ import annotations

from pathlib import Path

import pysubs2

from ass_style_tool.preview import render_preview_ass
from tests.test_ass_style import SAMPLE_ASS
from tests.test_profile import make_profile


def _write_source(tmp_path: Path) -> Path:
    src = tmp_path / "source.ass"
    src.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    return src


def test_render_preview_writes_styled_copy(tmp_path):
    src = _write_source(tmp_path)
    out = tmp_path / "preview.ass"
    modified = render_preview_ass(src, make_profile(), out)
    assert modified == ["Default"]
    subs = pysubs2.SSAFile.from_string(out.read_text(encoding="utf-8-sig"))
    assert subs.styles["Default"].fontname == "思源黑體 CN"
    assert subs.styles["Default"].fontsize == 48  # 720p 縮放,同批次規則


def test_render_preview_does_not_touch_source(tmp_path):
    src = _write_source(tmp_path)
    original = src.read_bytes()
    render_preview_ass(src, make_profile(), tmp_path / "preview.ass")
    assert src.read_bytes() == original


def test_render_preview_output_has_bom(tmp_path):
    src = _write_source(tmp_path)
    out = tmp_path / "preview.ass"
    render_preview_ass(src, make_profile(), out)
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")
