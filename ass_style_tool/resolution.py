"""縮放參考解析度規則(與 libass/VSFilter 行為一致)與 ffprobe 包裝。"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

#: ASS 規範:PlayRes 全缺時播放器假設的虛擬畫布
SPEC_DEFAULT_RES: Tuple[int, int] = (384, 288)


def reference_resolution(play_res_x: int, play_res_y: int) -> Tuple[int, int]:
    """決定縮放參考解析度。

    - 兩者有效 (>0) -> 直接使用
    - 只有一個有效 -> 依 4:3 推導另一個(播放器實際行為)
    - 皆無效 -> 384x288(規範預設)
    """
    x_ok = play_res_x > 0
    y_ok = play_res_y > 0
    if x_ok and y_ok:
        return play_res_x, play_res_y
    if x_ok:
        return play_res_x, round(play_res_x * 3 / 4)
    if y_ok:
        return round(play_res_y * 4 / 3), play_res_y
    return SPEC_DEFAULT_RES


def compute_scale(ref_w: int, ref_h: int, base_w: int, base_h: int) -> Tuple[float, float]:
    """回傳 (scale_x, scale_y) = 參考解析度 / 設定檔基準解析度。"""
    return ref_w / base_w, ref_h / base_h


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def probe_video_resolution(video_path: Path) -> Optional[Tuple[int, int]]:
    """用 ffprobe 讀取影片第一條視訊流的寬高;任何失敗都回 None。"""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    stripped = result.stdout.strip()
    if not stripped:
        return None
    parts = stripped.splitlines()[0].split(",")
    if len(parts) != 2:
        return None
    try:
        width, height = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def aspect_mismatch(
    ref: Tuple[int, int], video: Tuple[int, int], tolerance: float = 0.05
) -> bool:
    """PlayRes 長寬比與影片長寬比相對誤差超過 tolerance 時回 True。"""
    ref_ratio = ref[0] / ref[1]
    video_ratio = video[0] / video[1]
    return abs(ref_ratio - video_ratio) / video_ratio > tolerance
