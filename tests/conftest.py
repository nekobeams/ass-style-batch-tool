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
    """
    yield
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        for widget in app.topLevelWidgets():
            widget.deleteLater()
        app.processEvents()
        app.processEvents()  # deleteLater 需要第二輪事件處理才真正銷毀


@pytest.fixture(autouse=True)
def _isolate_appdata(tmp_path, monkeypatch):
    """把 APPDATA 重導到 tmp,確保任何測試(含 StyleEditor 建構時的 profile
    搬移/讀寫)都不會碰到真實使用者的 %APPDATA%。"""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
