"""批次執行 worker:在 QThread 中逐檔呼叫 process_file,支援取消。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from ..batch_runner import process_file
from ..episode_match import ass_output_name, find_files
from ..mkv_batch import MkvTools, process_mkv
from ..mkv_io import list_all_tracks, list_ass_tracks
from ..mkv_mux import MuxMeta, MuxPair, pair_for_mux, process_mux
from ..profile import Profile
from ..scale_engine import ScaleOptions, scale_file


class ScanWorker(QObject):
    progress = Signal(int, int)        # 已完成, 總數
    finished = Signal(object)          # 攜帶 ScanResult

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self._folder = folder
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        from ..batch_runner import scan_folder
        self.finished.emit(scan_folder(
            self._folder,
            progress=lambda done, total: self.progress.emit(done, total),
            should_cancel=lambda: self._cancelled,
        ))


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
            out_name = ass_output_name(match.sub_path).name
            if self._output_dir is not None and out_name in seen_basenames:
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
                    seen_basenames.add(out_name)
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
            out_name = ass_output_name(match.sub_path).name
            if self._output_dir is not None and out_name in seen_basenames:
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
                    seen_basenames.add(out_name)
                self.file_done.emit(match.sub_path.name, "ok")
                for change in report.style_changes:
                    self.message.emit(
                        f"    {change.name}: {change.old_size} → {change.new_size}")
                self.message.emit(
                    f"    inline \\fs 修改 {report.inline_fs_count} 處"
                    f"(倍率 {report.factor_used:.3f})")
            self.progress.emit(i, total)
        self.finished.emit(ok, 0, error)


class _TrackListWorker(QObject):
    """列舉指定清單各檔的軌道資訊;支援進度回報與取消。

    `MkvScanWorker` 與 `TrackScanWorker` 共用的基底類別:兩者的差異只在
    預設的 `list_fn`(以及各自的公開文件字串),`__init__`/`cancel`/`run`
    的行為完全一致,故抽出這裡,避免日後(例如新增單檔錯誤 signal)要
    手動同步改兩份。
    """

    finished = Signal(object)      # dict[Path, list[...]]
    progress = Signal(int, int)    # 已完成, 總數
    cancelled = Signal()           # 使用者取消(部分結果丟棄)

    def __init__(self, paths, mkvmerge: Path, list_fn) -> None:
        super().__init__()
        self._paths = [Path(p) for p in paths]
        self._mkvmerge = mkvmerge
        self._list_fn = list_fn
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._paths)
        result = {}
        self.progress.emit(0, total)  # 先讓對話框切到確定範圍,不是等第一檔跑完才有反應
        for i, path in enumerate(self._paths, start=1):
            # 檢查點在每個檔案之前;執行中的那一次 list_fn 會先跑完
            if self._cancelled:
                self.cancelled.emit()   # 丟棄 result,不發 finished
                return
            result[path] = self._list_fn(path, self._mkvmerge)
            self.progress.emit(i, total)
        self.finished.emit(result)


class MkvScanWorker(_TrackListWorker):
    """列舉指定 MKV 清單各檔的 ASS 字幕軌;支援進度回報與取消。

    吃檔案清單而非資料夾:MKV 分頁的資料夾掃描已經改成只列檔名、不跑
    外部程序,mkvmerge -J 只在使用者真的要選軌(或按下開始處理而尚未
    設定規則)時才跑。實際行為由 `_TrackListWorker` 提供。
    """

    def __init__(self, paths, mkvmerge: Path,
                 list_fn=list_ass_tracks) -> None:
        super().__init__(paths, mkvmerge, list_fn)


class TrackScanWorker(_TrackListWorker):
    """掃描指定的影片清單,列舉每檔的所有軌道;支援進度回報與取消。

    實際行為由 `_TrackListWorker` 提供。
    """

    def __init__(self, video_paths, mkvmerge: Path,
                 list_fn=list_all_tracks) -> None:
        super().__init__(video_paths, mkvmerge, list_fn)


class MkvWorker(QObject):
    """MKV 批次 worker;逐檔跑 process_mkv,支援取消與檔名衝突保護。"""

    progress = Signal(int, int)        # 已完成, 總數
    file_progress = Signal(int)        # 當前檔 mkvmerge %
    file_done = Signal(str, str)       # 檔名, 狀態
    message = Signal(str)
    finished = Signal(int, int, int)   # ok, skipped, error

    def __init__(self, jobs, operation, tools: MkvTools,
                 output_dir: Optional[Path],
                 process_fn=process_mkv) -> None:
        super().__init__()
        self._jobs = list(jobs)
        self._operation = operation
        self._tools = tools
        self._output_dir = output_dir  # None = 取代原檔
        self._process_fn = process_fn
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._jobs)
        ok = skipped = error = 0
        seen_basenames: set[str] = set()
        for i, (mkv_path, tracks) in enumerate(self._jobs, start=1):
            if self._cancelled:
                self.message.emit("已取消,停止後續檔案")
                break
            if (self._output_dir is not None
                    and mkv_path.name in seen_basenames):
                error += 1
                self.file_done.emit(mkv_path.name, "error")
                self.message.emit(
                    "    輸出檔名衝突: 已有同名檔案寫入輸出資料夾,略過此檔")
                self.progress.emit(i, total)
                continue
            out = (self._output_dir / mkv_path.name
                   if self._output_dir is not None else None)
            try:
                report = self._process_fn(
                    mkv_path, tracks, self._operation, self._tools,
                    out_path=out, progress_cb=self.file_progress.emit)
            except Exception as exc:  # 單檔失敗不中斷整批
                error += 1
                self.file_done.emit(mkv_path.name, "error")
                self.message.emit(f"    {exc}")
                self.progress.emit(i, total)
                continue
            if report.status == "ok":
                ok += 1
                if self._output_dir is not None:
                    seen_basenames.add(mkv_path.name)
            elif report.status == "skipped":
                skipped += 1
            else:
                error += 1
            self.file_done.emit(mkv_path.name, report.status)
            for msg in report.messages:
                self.message.emit(f"    {msg}")
            self.progress.emit(i, total)
        self.finished.emit(ok, skipped, error)


class MuxScanWorker(QObject):
    """掃描影片資料夾與字幕資料夾,依集數配對。"""

    finished = Signal(object)  # list[MuxPair]

    def __init__(self, video_folder: Path, subtitle_folder: Path,
                 pair_fn=pair_for_mux) -> None:
        super().__init__()
        self._video_folder = Path(video_folder)
        self._subtitle_folder = Path(subtitle_folder)
        self._pair_fn = pair_fn

    def run(self) -> None:
        _subs_in_v, videos = find_files(self._video_folder)
        subs, _videos_in_s = find_files(self._subtitle_folder)
        self.finished.emit(self._pair_fn(videos, subs))


class MuxWorker(QObject):
    """封裝批次 worker;逐檔跑 process_mux,支援取消與檔名衝突保護。"""

    progress = Signal(int, int)
    file_progress = Signal(int)
    file_done = Signal(str, str)
    message = Signal(str)
    finished = Signal(int, int, int)

    def __init__(self, pairs, meta: MuxMeta, operation, tools,
                 output_dir: Optional[Path], process_fn=process_mux,
                 edits=None) -> None:
        super().__init__()
        self._pairs = list(pairs)
        self._meta = meta
        self._operation = operation
        self._tools = tools
        self._output_dir = output_dir
        self._process_fn = process_fn
        self._edits = edits
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._pairs)
        ok = skipped = error = 0
        seen_basenames: set[str] = set()
        for i, pair in enumerate(self._pairs, start=1):
            if self._cancelled:
                self.message.emit("已取消,停止後續檔案")
                break
            name = pair.video_path.name
            if self._output_dir is not None and name in seen_basenames:
                error += 1
                self.file_done.emit(name, "error")
                self.message.emit(
                    "    輸出檔名衝突: 已有同名檔案寫入輸出資料夾,略過此檔")
                self.progress.emit(i, total)
                continue
            out = (self._output_dir / name
                   if self._output_dir is not None else None)
            try:
                report = self._process_fn(
                    pair, self._meta, self._operation, self._tools,
                    out_path=out, progress_cb=self.file_progress.emit,
                    edits=self._edits)
            except Exception as exc:  # 單檔失敗不中斷整批
                error += 1
                self.file_done.emit(name, "error")
                self.message.emit(f"    處理失敗: {exc}")
                self.progress.emit(i, total)
                continue
            if report.status == "ok":
                ok += 1
                if self._output_dir is not None:
                    seen_basenames.add(name)
            elif report.status == "skipped":
                skipped += 1
            else:
                error += 1
            self.file_done.emit(name, report.status)
            for msg in report.messages:
                self.message.emit(f"    {msg}")
            self.progress.emit(i, total)
        self.finished.emit(ok, skipped, error)
