"""批次流程協調:掃描資料夾、逐檔套用樣式、輸出/備份與紀錄。"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from .ass_style import (apply_profile, get_play_res,
                        get_scaled_border_shadow, load_subs, save_subs)
from .episode_match import MatchResult, find_files, match_pairs
from .profile import Profile
from .resolution import (aspect_mismatch, ffprobe_available,
                         probe_video_resolution, reference_resolution)


@dataclass
class FileReport:
    sub_path: Path
    status: str  # ok | skipped | error
    messages: List[str] = field(default_factory=list)


@dataclass
class ScanResult:
    matches: List[MatchResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def scan_folder(folder: Path) -> ScanResult:
    subs, videos = find_files(folder)
    scan = ScanResult(matches=match_pairs(subs, videos))
    if not subs:
        scan.warnings.append("資料夾內找不到任何 .ass/.ssa 字幕檔")
    if not ffprobe_available():
        scan.warnings.append("找不到 ffprobe:預覽將不含影片解析度資訊與長寬比警告")
        return scan
    for match in scan.matches:
        if match.video_path is not None:
            match.video_resolution = probe_video_resolution(match.video_path)
    return scan


def process_file(
    match: MatchResult, profile: Profile, output_dir: Optional[Path]
) -> FileReport:
    report = FileReport(sub_path=match.sub_path, status="ok")
    try:
        subs = load_subs(match.sub_path)
    except Exception as exc:  # 單檔失敗不可中斷整批
        return FileReport(match.sub_path, "error", [f"讀取失敗: {exc}"])

    try:
        report.messages.append(
            f"ScaledBorderAndShadow: {get_scaled_border_shadow(subs)}"
        )
        ref_w, ref_h = reference_resolution(*get_play_res(subs))
        report.messages.append(f"縮放參考解析度: {ref_w}x{ref_h}")
        if match.video_resolution is not None and aspect_mismatch(
            (ref_w, ref_h), match.video_resolution
        ):
            vw, vh = match.video_resolution
            report.messages.append(
                f"警告: PlayRes 長寬比與影片 {vw}x{vh} 不符,字幕可能變形,建議人工檢查"
            )

        modified = apply_profile(subs, profile)
        if not modified:
            report.status = "skipped"
            report.messages.append(
                f"找不到目標 Style {profile.target_style_names},未修改"
            )
            return report
        report.messages.append(f"已套用樣式到: {', '.join(modified)}")
    except Exception as exc:  # 單檔失敗不可中斷整批
        return FileReport(
            match.sub_path, "error", report.messages + [f"處理失敗: {exc}"]
        )

    try:
        if output_dir is None:
            backup = match.sub_path.with_name(match.sub_path.name + ".bak")
            if not backup.exists():
                shutil.copy2(match.sub_path, backup)  # 備份失敗會丟例外 -> 不寫入
            save_subs(subs, match.sub_path)
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            save_subs(subs, output_dir / match.sub_path.name)
    except Exception as exc:
        return FileReport(
            match.sub_path, "error", report.messages + [f"寫入失敗: {exc}"]
        )
    return report


def run_batch(
    scan: ScanResult,
    profile: Profile,
    output_dir: Optional[Path] = None,
    progress_cb: Optional[Callable[[FileReport], None]] = None,
) -> List[FileReport]:
    reports: List[FileReport] = []
    seen_basenames: Optional[set[str]] = set() if output_dir is not None else None
    for match in scan.matches:
        if output_dir is not None:
            basename = match.sub_path.name
            if basename in seen_basenames:
                report = FileReport(
                    match.sub_path, "error",
                    ["輸出檔名衝突: 已有同名檔案寫入輸出資料夾,略過此檔"]
                )
                reports.append(report)
                if progress_cb is not None:
                    progress_cb(report)
                continue
            seen_basenames.add(basename)

        report = process_file(match, profile, output_dir)
        reports.append(report)
        if progress_cb is not None:
            progress_cb(report)
    return reports
