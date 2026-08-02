"""批次執行 worker:在 QThread 中逐檔呼叫 process_file,支援取消。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from ..batch_runner import process_file
from ..episode_match import ass_output_name, find_files
from ..mkv_batch import MkvTools, process_mkv
from ..mkv_io import (TemplateExtraction, extract_template_subtitle,
                      extract_track, list_all_tracks, list_ass_tracks)
from ..mkv_mux import MuxMeta, MuxPair, pair_for_mux, process_mux
from ..profile import Profile
from ..scale_engine import ScaleOptions, scale_file
from ..style_scan import FileStyles, scan_styles


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


@dataclass
class TemplateStyleResult:
    """TemplateStyleWorker 的結果:抽取結果 + (成功時)樣式解析結果。

    extraction.path 為 None 時 styles 一定是 None——沒抽到範本檔就沒東西
    可以拿去解析樣式,呼叫端要先看 extraction 才能決定要不要看 styles。
    """
    extraction: TemplateExtraction
    styles: Optional[FileStyles] = None


class TemplateStyleWorker(QObject):
    """MKV 分頁「讀取樣式名稱」:抽一條範本字幕軌 + 解析樣式,丟到背景
    執行緒跑,不卡住 GUI。

    只處理一個檔案(不是清單),所以沒有 progress(int, int) 的意義,也
    沒有 cancel()——這裡跟這個專案其他 worker 的「取消」語意一樣,都只
    能擋「下一步」不能真的中斷正在跑的子行程(list_ass_tracks/
    extract_track 底下都是單次 subprocess.run,沒有中途檢查點可以插),
    而這裡從頭到尾就只有一步,沒有「下一步」可以擋,所以乾脆不假裝有
    取消能力。移到背景執行緒解決的是「GUI 執行緒被鎖住最多 360 秒、視窗
    顯示沒回應」,不是提供中途喊停。
    """

    finished = Signal(object)  # 攜帶 TemplateStyleResult

    def __init__(self, mkv_path: Path, mkvmerge: Path, mkvextract: Path,
                 out_dir: Optional[Path] = None,
                 extract_fn=extract_template_subtitle,
                 scan_fn=scan_styles) -> None:
        super().__init__()
        self._mkv_path = mkv_path
        self._mkvmerge = mkvmerge
        self._mkvextract = mkvextract
        self._out_dir = out_dir
        self._extract_fn = extract_fn
        self._scan_fn = scan_fn

    def run(self) -> None:
        # 一定要 emit finished,不管中間發生什麼事:read_template_styles()
        # 靠 finished 訊號才會清空 _template_thread、重新啟用按鈕。這裡若
        # 有未預期的例外沒被接住,finished 永遠不會發出,分頁就此卡死
        # ——按鈕永久停用,連新的「正在讀取,請稍候」重入防護都會把之後
        # 每一次點擊都擋下來,除了重開程式沒有其他復原路徑(最終審查
        # Minor)。
        try:
            extraction = self._extract_fn(
                self._mkv_path, self._mkvmerge, self._mkvextract,
                self._out_dir)
            if extraction.path is None:
                self.finished.emit(TemplateStyleResult(extraction=extraction))
                return
            styles = self._scan_fn(extraction.path)
        except Exception as exc:  # noqa: BLE001 -- 見上面的說明,一定要 emit
            self.finished.emit(TemplateStyleResult(
                extraction=TemplateExtraction(
                    path=None, error=f"worker_error:{exc}")))
            return
        self.finished.emit(
            TemplateStyleResult(extraction=extraction, styles=styles))


@dataclass
class PreviewExtractResult:
    """PreviewExtractWorker 的結果。

    success 為 False 時 error 可能有更明確的原因(worker 例外訊息);
    extract_track 本身失敗時單純回 False、沒有額外原因字串,呼叫端要
    兩種都處理。"""
    mkv_path: Path
    track_id: int
    out_path: Path
    success: bool
    error: Optional[str] = None


class PreviewExtractWorker(QObject):
    """MKV 分頁「送進預覽」:抽一條字幕軌到暫存檔,丟到背景執行緒跑。

    跟 TemplateStyleWorker 同一個理由,同一個檔案裡另一處同樣形狀的
    缺陷(最終審查):extract_track 底下是單次 subprocess.run,最多
    300 秒逾時,擺在 GUI 執行緒上會讓整個視窗「沒有回應」。沒有
    cancel() 的理由也相同——單一子行程呼叫沒有中途檢查點可以插。
    """

    finished = Signal(object)  # 攜帶 PreviewExtractResult

    def __init__(self, mkv_path: Path, track_id: int, out_path: Path,
                 mkvextract: Path, extract_fn=extract_track) -> None:
        super().__init__()
        self._mkv_path = mkv_path
        self._track_id = track_id
        self._out_path = out_path
        self._mkvextract = mkvextract
        self._extract_fn = extract_fn

    def run(self) -> None:
        # 一定要 emit finished,不管中間發生什麼事——跟 TemplateStyleWorker
        # 同一個理由,不重複那份說明,見那邊的註解。
        try:
            ok = self._extract_fn(
                self._mkv_path, self._track_id, self._out_path,
                self._mkvextract)
        except Exception as exc:  # noqa: BLE001 -- 見上面的說明,一定要 emit
            self.finished.emit(PreviewExtractResult(
                mkv_path=self._mkv_path, track_id=self._track_id,
                out_path=self._out_path, success=False, error=str(exc)))
            return
        self.finished.emit(PreviewExtractResult(
            mkv_path=self._mkv_path, track_id=self._track_id,
            out_path=self._out_path, success=ok))


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


@dataclass
class MuxScanResult:
    """MuxScanWorker 的結果:配對結果 + 每個已配對字幕檔的樣式掃描結果。

    file_styles 只含有字幕的配對(subtitle_path 不為 None),鍵是
    subtitle_path——沒有字幕可掃的列(no_subtitle/ambiguous/no_episode)
    本來就沒東西可以餵給 scan_styles。
    """
    pairs: List[MuxPair] = field(default_factory=list)
    file_styles: Dict[Path, FileStyles] = field(default_factory=dict)


class MuxScanWorker(QObject):
    """掃描影片資料夾與字幕資料夾,依集數配對,並解析每個已配對字幕檔的樣式。

    樣式解析(scan_styles)放在這裡而不是留給 GUI 端的 slot 處理,是因為
    它要逐檔讀檔案、跑 pysubs2 解析——資料夾大的話這個迴圈本身就不是
    瞬間完成的事,擺在 GUI 執行緒上會讓表格該出現的那一刻反而卡住視窗。
    """

    finished = Signal(object)  # 攜帶 MuxScanResult

    def __init__(self, video_folder: Path, subtitle_folder: Path,
                 pair_fn=pair_for_mux, scan_styles_fn=scan_styles) -> None:
        super().__init__()
        self._video_folder = Path(video_folder)
        self._subtitle_folder = Path(subtitle_folder)
        self._pair_fn = pair_fn
        self._scan_styles_fn = scan_styles_fn
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        _subs_in_v, videos = find_files(self._video_folder)
        subs, _videos_in_s = find_files(self._subtitle_folder)
        pairs = self._pair_fn(videos, subs)
        matched = [p for p in pairs if p.subtitle_path is not None]
        # 逐檔解析樣式:跟 _TrackListWorker 一樣,檔案與檔案之間放一個
        # 取消檢查點(正在跑的那一次 scan_styles 會先跑完,單一檔案的
        # 解析是毫秒級,不值得也沒辦法中斷)。沒有這個檢查點的話,關掉
        # 視窗時 mux_tab.shutdown() 的 _scan_thread.wait() 會一路等到整季
        # 的字幕都解析完為止。已解析的部分照常回報,不丟棄——配對結果
        # (pairs)本來就完整,樣式只是附帶資訊,少幾筆不影響正確性。
        file_styles = {}
        for pair in matched:
            if self._cancelled:
                break
            file_styles[pair.subtitle_path] = self._scan_styles_fn(
                pair.subtitle_path)
        self.finished.emit(MuxScanResult(pairs=pairs, file_styles=file_styles))


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
