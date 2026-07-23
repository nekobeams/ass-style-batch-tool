from __future__ import annotations

import pytest

from ass_style_tool.qt.theme import (THEME_MODES, qss_for, resolve_theme)


def test_theme_modes():
    assert THEME_MODES == ("system", "dark", "light")


def test_resolve_explicit_dark():
    assert resolve_theme("dark", system_is_dark=False) == "dark"


def test_resolve_explicit_light():
    assert resolve_theme("light", system_is_dark=True) == "light"


def test_resolve_system_follows_dark():
    assert resolve_theme("system", system_is_dark=True) == "dark"


def test_resolve_system_follows_light():
    assert resolve_theme("system", system_is_dark=False) == "light"


def test_resolve_unknown_mode_defaults_light():
    assert resolve_theme("bogus", system_is_dark=False) == "light"


def test_qss_for_dark_nonempty():
    assert "QMainWindow" in qss_for("dark")


def test_qss_for_light_differs_from_dark():
    assert qss_for("light") != qss_for("dark")


def test_qss_has_no_unsubstituted_placeholders():
    # 殘留的 $name 代表配色表漏了欄位,產生的 QSS 會壞掉
    for theme in ("dark", "light"):
        assert "$" not in qss_for(theme), f"{theme} 主題有殘留佔位符"


def test_qss_covers_new_widgets():
    for theme in ("dark", "light"):
        qss = qss_for(theme)
        for selector in ("QTreeWidget", "QScrollBar", "QGroupBox",
                         "QProgressBar", 'QPushButton[accent="true"]'):
            assert selector in qss, f"{theme} 主題缺少 {selector}"


def test_qss_has_row_separator_and_selection():
    for theme in ("dark", "light"):
        qss = qss_for(theme)
        assert "alternate-background-color" in qss      # 交錯底色
        assert "::item:selected" in qss                 # 選取高亮
        assert "::item:hover" in qss                    # hover 提示


def test_incomplete_palette_raises_loudly():
    # 配色表缺欄位必須直接拋出,不可靜默產生壞 QSS
    from ass_style_tool.qt.theme import _QSS_TEMPLATE
    with pytest.raises(KeyError):
        _QSS_TEMPLATE.substitute({"window_bg": "#000000"})
