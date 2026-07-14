"""外部工具(ffprobe/mkvmerge/mkvextract)的偵測:PATH → 常見目錄 → 內建 tools/。"""
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


def bundled_tools_dir() -> Path:
    """安裝程式會把工具放在套件旁的 tools/ 目錄(不保證存在)。
    打包後(sys.frozen)以執行檔所在目錄為準;開發模式維持相對於原始碼的位置。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "tools"
    return Path(__file__).parent / "tools"


def mkvtoolnix_common_dirs() -> List[Path]:
    """MKVToolNix 常見安裝目錄(存在與否不保證)。"""
    return [
        Path(r"C:\Program Files\MKVToolNix"),
        Path(r"C:\Program Files (x86)\MKVToolNix"),
    ]


def find_tool(
    exe_names: List[str], extra_dirs: Optional[List[Path]] = None
) -> Optional[Path]:
    """依序:PATH(shutil.which)→ extra_dirs 內找同名檔 → None。"""
    for name in exe_names:
        found = shutil.which(name)
        if found:
            return Path(found)
    for directory in extra_dirs or []:
        for name in exe_names:
            candidate = Path(directory) / name
            if candidate.exists():
                return candidate
    return None


def ffprobe_path() -> Optional[Path]:
    return find_tool(["ffprobe.exe", "ffprobe"], [bundled_tools_dir()])


def mkvmerge_path() -> Optional[Path]:
    dirs = mkvtoolnix_common_dirs() + [bundled_tools_dir()]
    return find_tool(["mkvmerge.exe", "mkvmerge"], dirs)


def mkvextract_path() -> Optional[Path]:
    dirs = mkvtoolnix_common_dirs() + [bundled_tools_dir()]
    return find_tool(["mkvextract.exe", "mkvextract"], dirs)


@dataclass
class ToolStatus:
    name: str
    path: Optional[Path]

    @property
    def available(self) -> bool:
        return self.path is not None


def tool_statuses() -> List[ToolStatus]:
    return [
        ToolStatus("ffprobe", ffprobe_path()),
        ToolStatus("mkvmerge", mkvmerge_path()),
        ToolStatus("mkvextract", mkvextract_path()),
    ]
