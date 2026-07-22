"""Windows 上抑制外部工具子行程閃現的終端機視窗。

打包版是 GUI 程式(console=False,見 ass_style_tool.spec),沒有附著的終端機。
Windows 對這種行程呼叫 subprocess.run/Popen 時,預設會替每次呼叫另外彈出一個
終端機視窗再消失。加上 CREATE_NO_WINDOW 才能抑制;非 Windows 平台無此旗標,回傳空 dict。
"""
from __future__ import annotations

import subprocess
import sys
from typing import Dict


def no_window_kwargs() -> Dict[str, int]:
    """回傳可直接以 **展開進 subprocess.run/Popen 的 kwargs。"""
    if sys.platform.startswith("win"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
