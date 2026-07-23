from __future__ import annotations

from ass_style_tool.preview_readout import OriginalValues, build_readout
from ass_style_tool.qt.readout_view import ReadoutView
from tests.test_profile import make_profile


def _orig():
    return OriginalValues(fontsize=40.0, outline=2.0, shadow=1.0,
                          margin_l=10, margin_r=10, margin_v=10)


def test_update_from_data_fills_table(qapp):
    v = ReadoutView()
    data = build_readout(make_profile(), 640, 360, _orig(), "e.ass", None, None)
    v.update_from(data)
    labels = [v.table.item(r, 0).text() for r in range(v.table.rowCount())]
    assert "字級" in labels
    row = labels.index("字級")
    assert v.table.item(row, 1).text() == "40"     # 原字幕現值
    assert v.table.item(row, 2).text() == "24"     # 72 * 640/1920
    assert v.missing.isHidden()
    assert not v.table.isHidden()


def test_update_from_missing_shows_message_hides_table(qapp):
    v = ReadoutView()
    data = build_readout(make_profile(target_style_names=["字幕"]), 640, 360,
                         None, "e.ass", None, None)
    v.update_from(data)
    assert not v.missing.isHidden()
    assert "字幕" in v.missing.text()
    assert v.table.isHidden()


def test_update_from_none_shows_placeholder(qapp):
    v = ReadoutView()
    v.update_from(build_readout(make_profile(), 640, 360, _orig(),
                                "e.ass", None, None))
    v.update_from(None)
    assert "載入字幕檔" in v.mechanism.text()
    assert v.table.rowCount() == 0
    assert v.table.isHidden()


def test_table_has_alternating_rows(qapp):
    from ass_style_tool.qt.readout_view import ReadoutView
    v = ReadoutView()
    assert v.table.alternatingRowColors() is True
