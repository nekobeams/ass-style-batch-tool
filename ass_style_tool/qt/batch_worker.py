"""批次執行 worker:在 QThread 中逐檔呼叫 process_file,支援取消。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from ..batch_runner import process_file
from ..profile import Profile


class BatchWorker(QObject):
    progress = Signal(int, int)        # 已完成, 總數
    file_done = Signal(str, str)       # 檔名, 狀態(ok|skipped|error)
    message = Signal(str)              # 單行 log
    finished = Signal(int, int, int)   # ok, skipped, error

    def __init__(self, scan, profile: Profile,
                 output_dir: Optional[Path]) -> None:
        super().__init__()
        self._matches = list(scan.matches)
        self._profile = profile
        self._output_dir = output_dir
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._matches)
        ok = skipped = error = 0
        for i, match in enumerate(self._matches, start=1):
            if self._cancelled:
                self.message.emit("已取消,停止後續檔案")
                break
            report = process_file(match, self._profile, self._output_dir)
            if report.status == "ok":
                ok += 1
            elif report.status == "skipped":
                skipped += 1
            else:
                error += 1
            self.file_done.emit(report.sub_path.name, report.status)
            for msg in report.messages:
                self.message.emit(f"    {msg}")
            self.progress.emit(i, total)
        self.finished.emit(ok, skipped, error)
