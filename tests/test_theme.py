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
