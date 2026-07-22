from __future__ import annotations

import subprocess

from ass_style_tool.subprocess_utils import no_window_kwargs


def test_no_window_kwargs_windows(monkeypatch):
    monkeypatch.setattr("ass_style_tool.subprocess_utils.sys.platform", "win32")
    assert no_window_kwargs() == {"creationflags": subprocess.CREATE_NO_WINDOW}


def test_no_window_kwargs_non_windows(monkeypatch):
    monkeypatch.setattr("ass_style_tool.subprocess_utils.sys.platform", "linux")
    assert no_window_kwargs() == {}
