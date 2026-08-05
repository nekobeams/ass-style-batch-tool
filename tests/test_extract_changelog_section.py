"""release.yml 用來從 CHANGELOG.md 擷取版本段落的小工具
(.github/scripts/extract_changelog_section.py)。獨立在 .github/scripts/
底下(不是 ass_style_tool 套件的一部分,是 CI 專用的小腳本),測試用
sys.path 直接匯入。"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / ".github" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from extract_changelog_section import extract_section  # noqa: E402


_SAMPLE = """\
# Changelog

## v1.2.0

- 加入某某功能
- 修掉某某 bug

## v1.1.0

- 第一段
- 第二段

## v1.0.0

初始版本。
"""


def test_extracts_middle_section():
    assert extract_section(_SAMPLE, "v1.1.0") == "- 第一段\n- 第二段"


def test_extracts_first_section_stops_before_next_heading():
    assert extract_section(_SAMPLE, "v1.2.0") == "- 加入某某功能\n- 修掉某某 bug"


def test_extracts_last_section_to_end_of_file():
    assert extract_section(_SAMPLE, "v1.0.0") == "初始版本。"


def test_missing_version_returns_empty_string():
    """找不到對應標題時回空字串,不是丟例外——呼叫端(release.yml)靠
    空字串判斷要不要退回讀 tag 訊息。"""
    assert extract_section(_SAMPLE, "v9.9.9") == ""


def test_version_string_is_not_a_prefix_match():
    """v1.1.0 不能誤配到 v1.1.0-test 這種以它為前綴的標題——這是版本
    字串比對最容易犯的錯,兩個版本內容混在一起會讓 release notes 對不
    上實際那個 tag。"""
    text = "## v1.1.0-test\n\n這是測試版\n\n## v1.1.0\n\n這是正式版\n"
    assert extract_section(text, "v1.1.0") == "這是正式版"
    assert extract_section(text, "v1.1.0-test") == "這是測試版"


def test_empty_section_returns_empty_string():
    text = "## v1.0.0\n\n## v0.9.0\n\n有內容\n"
    assert extract_section(text, "v1.0.0") == ""


def test_missing_changelog_file_returns_none(tmp_path):
    """main() 對應 release.yml 的實際呼叫路徑:CHANGELOG.md 根本不存在
    時要能安全處理(印出空字串),不是這個測試檔案的職責範圍是
    extract_section() 本身;main() 的檔案不存在分支另外驗證。"""
    import extract_changelog_section as mod
    import io
    import contextlib

    missing = tmp_path / "nope.md"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sys.argv = ["extract_changelog_section.py", str(missing), "v1.0.0"]
        mod.main()
    assert buf.getvalue() == ""
