"""root logger 設定:輸出到 %LOCALAPPDATA%\\ass-style-batch-tool\\logs\\app.log,
供使用者回報問題時附上(見 README「回報問題」一節)。"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

#: 單檔上限與保留份數——固定值,不開放呼叫端調整,避免安裝出去的版本
#: 每個使用者的日誌保留策略都不一樣,回報問題時比對不到共同基準。
_MAX_BYTES = 2 * 1024 * 1024
_BACKUP_COUNT = 3


def log_dir() -> Path:
    """日誌目錄:%LOCALAPPDATA%\\ass-style-batch-tool\\logs。

    刻意不像 tools.bundled_tools_dir() 那樣依 sys.frozen 分岔路徑——那裡
    找的是「這次執行的程式本體旁邊」的工具,frozen(裝進 Program Files)
    與從原始碼執行(repo 目錄)本來就該是不同位置;這裡是使用者資料,
    不管用哪種方式啟動都該落在同一個地方,不然「打包版」跟「開發版」
    各寫一份日誌,使用者回報問題時反而不知道該附哪一份。

    LOCALAPPDATA 理論上 Windows 一定有,但不讓這裡直接
    os.environ["LOCALAPPDATA"] 硬取——那樣萬一環境真的沒設,匯入這個
    模組(進而整個 logging 設定)就直接 KeyError 崩掉,比「沒有日誌」
    更糟。退回 Windows 該環境變數的標準預設值。
    """
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "ass-style-batch-tool" / "logs"


def setup_logging(level: int = logging.INFO) -> Path:
    """設定 root logger,回傳實際使用的日誌目錄(呼叫端,例如「開啟日誌
    資料夾」按鈕,可以直接用,不必自己重算一次 log_dir())。

    只掛檔案 handler,不掛 console handler——這是 PyInstaller 打包的
    GUI 程式(console=False,見 ass_style_tool.spec),沒有終端機可寫。

    重複呼叫是安全的:先清掉 root logger 既有的 handler 再裝新的一顆,
    不會疊加出同一行訊息被寫進檔案好幾次。
    """
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        directory / "app.log", maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s"))

    root = logging.getLogger()
    root.setLevel(level)
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)

    # 開一行啟動標記:不能只靠使用者互動(按按鈕、跑批次)才產生第一行
    # log——沒有這行的話,使用者開程式看畫面、什麼都沒按就回報「程式
    # 打不開」,app.log 會是完全空的,連「程式到底有沒有啟動」都判斷
    # 不出來。順便標出這次執行的分界,多次啟動疊在同一個檔案裡才看得出
    # 是哪一段對應哪一次執行。
    logging.getLogger(__name__).info("logging 已啟動,輸出到 %s", directory / "app.log")
    return directory
