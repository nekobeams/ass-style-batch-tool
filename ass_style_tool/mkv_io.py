"""MKV 字幕軌的列舉、抽取與重封裝(呼叫 mkvmerge/mkvextract)。"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .subprocess_utils import no_window_kwargs

_ASS_CODEC_IDS = {"S_TEXT/ASS", "S_TEXT/SSA"}


@dataclass
class SubtitleTrack:
    track_id: int
    codec_id: str
    language: str
    track_name: str
    default: bool
    forced: bool


def parse_ass_tracks(identify_json: dict) -> List[SubtitleTrack]:
    """從 mkvmerge -J 的 dict 取出 ASS/SSA 字幕軌。"""
    result: List[SubtitleTrack] = []
    for track in identify_json.get("tracks", []):
        if track.get("type") != "subtitles":
            continue
        props = track.get("properties", {})
        codec_id = props.get("codec_id", "")
        if codec_id not in _ASS_CODEC_IDS:
            continue
        result.append(SubtitleTrack(
            track_id=int(track["id"]),
            codec_id=codec_id,
            language=props.get("language", "und"),
            track_name=props.get("track_name", ""),
            default=bool(props.get("default_track", False)),
            forced=bool(props.get("forced_track", False)),
        ))
    return result


def _run_mkvmerge_identify(mkv_path: Path, mkvmerge: Path) -> Optional[dict]:
    """跑 mkvmerge -J,回傳解析後的 JSON;任何失敗(執行錯誤/逾時/非零
    結束碼/JSON 壞掉)回 None。

    list_ass_tracks 與 extract_template_subtitle 都要跑同一個 identify
    指令,共用這個函式確保「什麼算失敗」只有一份定義——分開各自實作的話,
    兩邊的失敗判斷遲早會慢慢分岔(這個專案已經因為同一個模式吃過幾次虧)。
    """
    cmd = [str(mkvmerge), "-J", str(mkv_path)]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, encoding="utf-8",
            **no_window_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except (ValueError, TypeError):
        return None


def list_ass_tracks(mkv_path: Path, mkvmerge: Path) -> List[SubtitleTrack]:
    """跑 mkvmerge -J 列舉 ASS 字幕軌;任何失敗回 []。"""
    data = _run_mkvmerge_identify(mkv_path, mkvmerge)
    if data is None:
        return []
    return parse_ass_tracks(data)


@dataclass
class MediaTrack:
    track_id: int
    track_type: str        # "video" | "audio" | "subtitles"
    codec_id: str
    language: str
    track_name: str
    default: bool
    forced: bool


_MEDIA_TRACK_TYPES = {"video", "audio", "subtitles"}


def parse_all_tracks(identify_json: dict) -> List[MediaTrack]:
    """從 mkvmerge -J 的 dict 取出所有 video/audio/subtitles 軌(依 id 排序)。"""
    result: List[MediaTrack] = []
    for track in identify_json.get("tracks", []):
        ttype = track.get("type")
        if ttype not in _MEDIA_TRACK_TYPES:
            continue
        props = track.get("properties", {})
        result.append(MediaTrack(
            track_id=int(track["id"]),
            track_type=ttype,
            codec_id=props.get("codec_id", ""),
            language=props.get("language", "und"),
            track_name=props.get("track_name", ""),
            default=bool(props.get("default_track", False)),
            forced=bool(props.get("forced_track", False)),
        ))
    result.sort(key=lambda t: t.track_id)
    return result


def list_all_tracks(mkv_path: Path, mkvmerge: Path) -> List[MediaTrack]:
    """跑 mkvmerge -J 列出所有軌;任何失敗回 []。"""
    data = _run_mkvmerge_identify(mkv_path, mkvmerge)
    if data is None:
        return []
    return parse_all_tracks(data)


@dataclass
class Replacement:
    track: SubtitleTrack
    styled_path: Path


def build_extract_command(
    mkv_path: Path, track_id: int, out_path: Path, mkvextract: Path
) -> List[str]:
    return [str(mkvextract), str(mkv_path), "tracks", f"{track_id}:{out_path}"]


def build_remux_command(
    mkv_path: Path,
    out_path: Path,
    replacements: List[Replacement],
    mkvmerge: Path,
) -> List[str]:
    if not replacements:
        raise ValueError("replacements 不可為空")
    excluded = ",".join(str(r.track.track_id) for r in replacements)
    cmd: List[str] = [str(mkvmerge), "-o", str(out_path)]
    # 原檔:只丟掉被替換的字幕軌,其餘(含未勾字幕、視訊、音訊、章節、附件)保留
    cmd += ["--subtitle-tracks", f"!{excluded}", str(mkv_path)]
    # 每個改後 .ass 以附加軌加入,還原原軌旗標(檔內為 track 0)
    for r in replacements:
        t = r.track
        cmd += ["--language", f"0:{t.language}"]
        if t.track_name:
            cmd += ["--track-name", f"0:{t.track_name}"]
        cmd += ["--default-track", f"0:{'yes' if t.default else 'no'}"]
        cmd += ["--forced-track", f"0:{'yes' if t.forced else 'no'}"]
        cmd.append(str(r.styled_path))
    return cmd


_PROGRESS_RE = re.compile(r"Progress:\s*(\d{1,3})%")


def parse_progress(line: str) -> Optional[int]:
    match = _PROGRESS_RE.search(line)
    return int(match.group(1)) if match else None


def extract_track(
    mkv_path: Path, track_id: int, out_path: Path, mkvextract: Path
) -> bool:
    cmd = build_extract_command(mkv_path, track_id, out_path, mkvextract)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300, encoding="utf-8",
            **no_window_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


@dataclass
class TemplateExtraction:
    """extract_template_subtitle() 的結果。

    path 為 None 時 error 說明原因,呼叫端要各自對應不同的提示訊息,
    不能混為一談:
      "identify_failed" -- 連 mkvmerge -J 都沒能成功問出這個檔案有哪些軌
                          (逾時、檔案損毀/被占用、mkvmerge 當掉、輸出不是
                          合法 JSON)——完全不知道這個檔案有沒有字幕軌,
                          不能當成「沒有」來講。
      "no_track"        -- mkvmerge -J 有正常回應,但回應裡就是沒有
                          ASS/SSA 字幕軌(可能是 PGS/VobSub 圖形字幕),
                          換個檔也不會有。
      "extract_failed"  -- 軌道存在,但 mkvextract 抽取失敗(壞檔、磁碟
                          空間不足、權限問題、mkvextract 當掉…)——這批
                          影片可能有文字字幕,只是這次抽取沒成功。
    """
    path: Optional[Path]
    error: Optional[str] = None


def extract_template_subtitle(
    mkv_path: Path, mkvmerge: Path, mkvextract: Path,
    out_dir: Optional[Path] = None,
) -> TemplateExtraction:
    """抽出影片中第一條 ASS/SSA 字幕軌到暫存檔,當「讀取樣式名稱」的範本。

    只抽一條、只抽一個檔案——這是給「讀取樣式名稱」用的範本,不是批次處理。
    整季逐檔抽取太慢,而使用者的情境是全季樣式名一致。

    out_dir 未指定時退回系統暫存目錄;呼叫端若有自己會清理的暫存目錄
    (例如分頁的 _preview_dir),應該傳進來,避免範本檔留在系統暫存目錄
    裡沒人清。
    """
    data = _run_mkvmerge_identify(mkv_path, mkvmerge)
    if data is None:
        return TemplateExtraction(path=None, error="identify_failed")
    tracks = parse_ass_tracks(data)
    if not tracks:
        return TemplateExtraction(path=None, error="no_track")
    directory = out_dir if out_dir is not None else Path(tempfile.gettempdir())
    out_path = directory / f"{mkv_path.stem}.template.ass"
    if not extract_track(mkv_path, tracks[0].track_id, out_path, mkvextract):
        return TemplateExtraction(path=None, error="extract_failed")
    return TemplateExtraction(path=out_path)


def remux(
    mkv_path: Path,
    out_path: Path,
    replacements: List[Replacement],
    mkvmerge: Path,
    progress_cb: Optional[Callable[[int], None]] = None,
) -> bool:
    """重封裝;mkvmerge 退出碼 0(成功)或 1(警告)視為成功。"""
    cmd = build_remux_command(mkv_path, out_path, replacements, mkvmerge)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **no_window_kwargs(),
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            if progress_cb is not None:
                pct = parse_progress(line)
                if pct is not None:
                    progress_cb(pct)
        proc.wait()
        return proc.returncode in (0, 1)
    except OSError:
        return False
