from __future__ import annotations

import sys
from pathlib import Path

from ass_style_tool.tools import (ToolStatus, find_tool, ffprobe_path,
                                  mkvmerge_path, tool_statuses)


def test_find_tool_uses_which_first(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.tools.shutil.which",
        lambda name: r"C:\sys\mkvmerge.exe" if name == "mkvmerge" else None,
    )
    result = find_tool(["mkvmerge"])
    assert result == Path(r"C:\sys\mkvmerge.exe")


def test_find_tool_tries_multiple_names(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.tools.shutil.which",
        lambda name: r"C:\sys\ffprobe.exe" if name == "ffprobe" else None,
    )
    # 第一個候選名找不到,第二個找到
    assert find_tool(["ffprobe.exe", "ffprobe"]) == Path(r"C:\sys\ffprobe.exe")


def test_find_tool_falls_back_to_extra_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr("ass_style_tool.tools.shutil.which", lambda name: None)
    exe = tmp_path / "mkvmerge.exe"
    exe.write_bytes(b"")
    assert find_tool(["mkvmerge.exe"], extra_dirs=[tmp_path]) == exe


def test_find_tool_returns_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("ass_style_tool.tools.shutil.which", lambda name: None)
    assert find_tool(["nope.exe"], extra_dirs=[tmp_path]) is None


def test_ffprobe_path_found(monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.tools.shutil.which",
        lambda name: r"C:\sys\ffprobe.exe" if name.startswith("ffprobe") else None,
    )
    assert ffprobe_path() == Path(r"C:\sys\ffprobe.exe")


def test_mkvmerge_path_none(monkeypatch):
    monkeypatch.setattr("ass_style_tool.tools.shutil.which", lambda name: None)
    monkeypatch.setattr(
        "ass_style_tool.tools.mkvtoolnix_common_dirs", lambda: []
    )
    monkeypatch.setattr(
        "ass_style_tool.tools.bundled_tools_dir", lambda: Path(r"C:\nonexistent")
    )
    assert mkvmerge_path() is None


def test_tool_status_available():
    assert ToolStatus("ffprobe", Path(r"C:\x.exe")).available is True
    assert ToolStatus("mkvmerge", None).available is False


def test_tool_statuses_reports_three(monkeypatch):
    monkeypatch.setattr("ass_style_tool.tools.shutil.which", lambda name: None)
    monkeypatch.setattr("ass_style_tool.tools.mkvtoolnix_common_dirs", lambda: [])
    monkeypatch.setattr(
        "ass_style_tool.tools.bundled_tools_dir", lambda: Path(r"C:\nonexistent")
    )
    statuses = tool_statuses()
    assert {s.name for s in statuses} == {"ffprobe", "mkvmerge", "mkvextract"}
    assert all(s.available is False for s in statuses)


# ---------- bundled_tools_dir frozen 感知 ----------

def test_bundled_tools_dir_dev_mode(monkeypatch):
    import ass_style_tool.tools as tools_mod
    monkeypatch.delattr(sys, "frozen", raising=False)
    expected = Path(tools_mod.__file__).parent / "tools"
    assert tools_mod.bundled_tools_dir() == expected


def test_bundled_tools_dir_frozen(monkeypatch, tmp_path):
    import ass_style_tool.tools as tools_mod
    fake_exe = tmp_path / "ass_style_tool.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    assert tools_mod.bundled_tools_dir() == tmp_path / "tools"
