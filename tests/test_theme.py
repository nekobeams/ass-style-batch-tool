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
                         "QProgressBar", 'QPushButton[accent="true"]',
                         "QListWidget"):
            assert selector in qss, f"{theme} 主題缺少 {selector}"


def test_qss_has_row_separator_and_selection():
    for theme in ("dark", "light"):
        qss = qss_for(theme)
        assert "alternate-background-color" in qss      # 交錯底色
        assert "::item:selected" in qss                 # 選取高亮
        assert "::item:hover" in qss                    # hover 提示


def test_template_placeholders_match_palette_fields():
    # 雙向比對:沒有多餘佔位符,也沒有沒用到的配色欄位
    from ass_style_tool.qt.theme import _Palette, _QSS_TEMPLATE
    assert set(_QSS_TEMPLATE.get_identifiers()) == set(_Palette.__dataclass_fields__)


def test_qss_for_fails_loudly_on_incomplete_palette(monkeypatch):
    # 若有人把 substitute 換成 safe_substitute,這個測試會失敗
    from dataclasses import dataclass
    import ass_style_tool.qt.theme as theme

    @dataclass(frozen=True)
    class _Partial:
        window_bg: str = "#000000"

    monkeypatch.setattr(theme, "_DARK", _Partial())
    with pytest.raises(KeyError):
        theme.qss_for("dark")
