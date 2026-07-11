from __future__ import annotations

from ass_style_tool.profile import Profile
from ass_style_tool.profile_fields import DEFAULT_VALUES, values_from_profile


def test_get_values_roundtrip(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    editor.set_values(DEFAULT_VALUES)
    values = editor.get_values()
    # 關鍵欄位讀回一致
    assert values["fontname"] == DEFAULT_VALUES["fontname"]
    assert values["target_style_names"] == DEFAULT_VALUES["target_style_names"]
    assert str(values["fontsize"]) == str(DEFAULT_VALUES["fontsize"])
    assert bool(values["bold"]) == bool(DEFAULT_VALUES["bold"])
    assert values["alignment"] == DEFAULT_VALUES["alignment"]


def test_current_profile_from_defaults(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    editor.set_values(DEFAULT_VALUES)
    profile = editor.current_profile()
    assert isinstance(profile, Profile)
    assert profile.style.fontname == DEFAULT_VALUES["fontname"]
    assert profile.base_width == 1920


def test_set_values_from_profile_roundtrip(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    from ass_style_tool.profile_fields import profile_from_values
    editor = StyleEditor()
    p0 = profile_from_values(DEFAULT_VALUES)
    editor.set_values(values_from_profile(p0))
    assert editor.current_profile() == p0


def test_invalid_fontsize_raises(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    editor.set_values(DEFAULT_VALUES)
    editor.set_values({**DEFAULT_VALUES, "fontsize": "big"})
    import pytest
    with pytest.raises(ValueError):
        editor.current_profile()


def test_font_warning_toggles(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    # 一個幾乎不可能安裝的字型名 → 應標記未安裝
    editor.set_values({**DEFAULT_VALUES, "fontname": "NoSuchFont ZZZ 12345"})
    editor.refresh_font_warning()
    assert editor.font_warning_visible() is True


def test_values_changed_signal_fires(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    fired = []
    editor.values_changed.connect(lambda: fired.append(1))
    editor._edits["fontsize"].setText("88")
    assert len(fired) >= 1
    before = len(fired)
    editor._checks["bold"].setChecked(True)
    assert len(fired) > before
