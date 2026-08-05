"""pytest 共用設定:讓 Qt 測試在無顯示器環境以 offscreen 平台執行。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _qt_widget_cleanup():
    """每個測試後銷毀殘留的頂層 widget(等同 pytest-qt qtbot 的清理)。

    測試建立的 widget 若留到直譯器關閉才由 Qt 以未定順序銷毀,
    會造成間歇性的原生層 teardown 崩潰(全套測試實測,exit 127
    且無 traceback)。在 QApplication 仍存活時確定性銷毀可根除。

    這裡不能只呼叫 processEvents():整套測試 session 從頭到尾都沒有進過
    app.exec(),全程停在 Qt 的「event loop level 0」——processEvents()
    在這個層級不保證會把 deleteLater() 排進去的 DeferredDelete 事件真的
    清掉(實測過,offscreen 平台、PySide6 6.11.1:deleteLater() 之後跑兩次
    processEvents(),isValid() 仍是 True)。沒被真正清掉的 widget 就會像
    QThread/worker 那組 bug 一樣,銷毀時機被動交給 Python 的分代 GC——
    在 CI 上(windows-latest、Python 3.11.9)造成間歇性的 heap corruption
    (0xc0000374),事後對照過:同一台機器、同一顆直譯器,原本的兩次
    processEvents() 寫法連跑 15 次崩潰 7 次,換成 sendPostedEvents()
    後連跑 15 次 0 次崩潰。sendPostedEvents(None, DeferredDelete) 直接
    強制把這輪排隊的刪除事件清空,不必依賴進到哪個 event loop 層級。
    """
    yield
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        for widget in app.topLevelWidgets():
            widget.deleteLater()
        app.processEvents()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def _isolate_appdata(tmp_path, monkeypatch):
    """把 APPDATA/LOCALAPPDATA 都重導到 tmp,確保任何測試(含 StyleEditor
    建構時的 profile 搬移/讀寫、logging_setup 的日誌檔)都不會碰到真實
    使用者的 %APPDATA%/%LOCALAPPDATA%。"""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
