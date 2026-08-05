"""logging_setup.py 的路徑解析與 RotatingFileHandler 設定。"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from ass_style_tool.logging_setup import log_dir, setup_logging


@pytest.fixture(autouse=True)
def _reset_root_logger():
    """setup_logging() 動的是 root logger(process 全域單例),不重設會讓
    這裡裝的 handler 洩漏到其他測試——尤其 handler 指到的檔案在 tmp_path
    清掉後還留著,之後任何一行 logging 呼叫都會對著已刪除的路徑寫入。"""
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    for h in original_handlers:
        root.addHandler(h)
    root.setLevel(original_level)


def test_log_dir_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert log_dir() == tmp_path / "ass-style-batch-tool" / "logs"


def test_log_dir_falls_back_when_localappdata_unset(monkeypatch):
    """LOCALAPPDATA 沒設定時(理論上 Windows 一定有,但不該讓 import 這個
    模組就直接 KeyError 崩掉)要有備援,不能整個 logging 設定啟動失敗。"""
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    d = log_dir()
    assert d.is_absolute()
    assert d.parts[-2:] == ("ass-style-batch-tool", "logs")


def test_log_dir_same_regardless_of_frozen_state(monkeypatch, tmp_path):
    """使用者資料位置不該因為執行方式(PyInstaller 打包 vs 從原始碼跑)
    而變——這跟 tools.bundled_tools_dir() 特意要找『這次執行的程式本體
    旁邊』不是同一種路徑,那裡 frozen 與否位置本來就該不同,這裡不該。
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    not_frozen = log_dir()
    monkeypatch.setattr("sys.frozen", True, raising=False)
    frozen = log_dir()
    assert not_frozen == frozen


def test_setup_logging_creates_log_file_with_content(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    directory = setup_logging()
    logging.getLogger("test").info("hello")
    log_file = directory / "app.log"
    assert log_file.exists()
    assert "hello" in log_file.read_text(encoding="utf-8")


def test_setup_logging_writes_a_startup_line_by_itself(monkeypatch, tmp_path):
    """日誌檔不能靠使用者互動才有第一行內容——完全不碰任何按鈕、只是
    啟動程式,app.log 也要有東西,不然無從判斷「程式到底有沒有啟動」。
    這裡刻意不額外呼叫任何 logger,只測 setup_logging() 自己的效果。"""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    directory = setup_logging()
    text = (directory / "app.log").read_text(encoding="utf-8")
    assert text.strip() != ""


def test_setup_logging_returns_the_directory_it_uses(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert setup_logging() == log_dir()


def test_setup_logging_uses_rotating_file_handler_with_expected_limits(
        monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    setup_logging()
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    handler = handlers[0]
    assert isinstance(handler, RotatingFileHandler)
    # 單檔約 2MB、保留 3 份(見任務需求),不是隨便挑的數字,直接斷言值。
    assert handler.maxBytes == 2 * 1024 * 1024
    assert handler.backupCount == 3


def test_setup_logging_is_idempotent_no_duplicate_handlers(monkeypatch, tmp_path):
    """重複呼叫(例如測試裡每個案例都呼叫一次)不該疊加出重複輸出——
    每叫一次都新增一個 handler 的話,跑久了同一行 log 會被寫進檔案好幾次。
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    setup_logging()
    setup_logging()
    assert len(logging.getLogger().handlers) == 1


def test_setup_logging_format_includes_timestamp_level_and_module(
        monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    directory = setup_logging()
    logging.getLogger(__name__).warning("boom")
    text = (directory / "app.log").read_text(encoding="utf-8")
    assert "WARNING" in text
    assert __name__ in text
    # 時間戳格式沒有硬性規定要長怎樣,但至少要看得出年份開頭,不是完全
    # 沒有時間資訊。
    import datetime
    assert str(datetime.datetime.now().year) in text


def test_setup_logging_creates_directory_if_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert not (tmp_path / "ass-style-batch-tool").exists()
    setup_logging()
    assert log_dir().is_dir()
