"""批次執行 worker:在 QThread 中逐檔呼叫 process_file,支援取消。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from ..batch_runner import process_file
from ..profile import Profile
from ..scale_engine import ScaleOptions, scale_file


class ScanWorker(QObject):
    finished = Signal(object)  # 攜帶 ScanResult

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self._folder = folder

    def run(self) -> None:
        from ..batch_runner import scan_folder
        self.finished.emit(scan_folder(self._folder))


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
        seen_basenames: set[str] = set()
        for i, match in enumerate(self._matches, start=1):
            if self._cancelled:
                self.message.emit("已取消,停止後續檔案")
                break
            if self._output_dir is not None and match.sub_path.name in seen_basenames:
                error += 1
                self.file_done.emit(match.sub_path.name, "error")
                self.message.emit(
                    f"    輸出檔名衝突: 已有同名檔案寫入輸出資料夾,略過此檔")
                self.progress.emit(i, total)
                continue
            report = process_file(match, self._profile, self._output_dir)
            if report.status == "ok":
                ok += 1
                if self._output_dir is not None:
                    seen_basenames.add(match.sub_path.name)
            elif report.status == "skipped":
                skipped += 1
            else:
                error += 1
            self.file_done.emit(report.sub_path.name, report.status)
            for msg in report.messages:
                self.message.emit(f"    {msg}")
            self.progress.emit(i, total)
        self.finished.emit(ok, skipped, error)


class ScaleWorker(QObject):
    """縮放字級批次 worker;signals 形狀與 BatchWorker 相同(skipped 恆為 0)。"""

    progress = Signal(int, int)
    file_done = Signal(str, str)
    message = Signal(str)
    finished = Signal(int, int, int)

    def __init__(self, scan, options: ScaleOptions,
                 output_dir: Optional[Path]) -> None:
        super().__init__()
        self._matches = list(scan.matches)
        self._options = options
        self._output_dir = output_dir
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._matches)
        ok = error = 0
        seen_basenames: set[str] = set()
        for i, match in enumerate(self._matches, start=1):
            if self._cancelled:
                self.message.emit("已取消,停止後續檔案")
                break
            if self._output_dir is not None and match.sub_path.name in seen_basenames:
                error += 1
                self.file_done.emit(match.sub_path.name, "error")
                self.message.emit(
                    f"    輸出檔名衝突: 已有同名檔案寫入輸出資料夾,略過此檔")
                self.progress.emit(i, total)
                continue
            out = (self._output_dir / match.sub_path.name
                   if self._output_dir is not None else None)
            try:
                report = scale_file(match.sub_path, self._options, out)
            except Exception as exc:  # 單檔失敗不中斷整批
                error += 1
                self.file_done.emit(match.sub_path.name, "error")
                self.message.emit(f"    {exc}")
            else:
                ok += 1
                if self._output_dir is not None:
                    seen_basenames.add(match.sub_path.name)
                self.file_done.emit(match.sub_path.name, "ok")
                for change in report.style_changes:
                    self.message.emit(
                        f"    {change.name}: {change.old_size} → {change.new_size}")
                self.message.emit(
                    f"    inline \\fs 修改 {report.inline_fs_count} 處"
                    f"(倍率 {report.factor_used:.3f})")
            self.progress.emit(i, total)
        self.finished.emit(ok, 0, error)
