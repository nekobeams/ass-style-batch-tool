from __future__ import annotations

from pathlib import Path

import pysubs2

from ass_style_tool.batch_runner import (FileReport, ScanResult,
                                         process_file, run_batch,
                                         scan_folder)
from ass_style_tool.episode_match import MatchResult
from tests.test_ass_style import SAMPLE_ASS
from tests.test_profile import make_profile


def _write_sample(tmp_path: Path, name: str = "[A] Show [01].ass") -> Path:
    path = tmp_path / name
    path.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    return path


def test_process_file_inplace_backs_up_and_modifies(tmp_path):
    sub = _write_sample(tmp_path)
    original_bytes = sub.read_bytes()
    report = process_file(MatchResult(sub_path=sub, episode=1), make_profile(), None)
    assert report.status == "ok"
    backup = tmp_path / "[A] Show [01].ass.bak"
    assert backup.read_bytes() == original_bytes
    updated = pysubs2.SSAFile.from_string(sub.read_text(encoding="utf-8-sig"))
    assert updated.styles["Default"].fontname == "思源黑體 CN"
    assert updated.styles["Default"].fontsize == 48


def test_process_file_output_dir_leaves_original(tmp_path):
    sub = _write_sample(tmp_path)
    original_bytes = sub.read_bytes()
    out_dir = tmp_path / "out"
    report = process_file(MatchResult(sub_path=sub, episode=1), make_profile(), out_dir)
    assert report.status == "ok"
    assert sub.read_bytes() == original_bytes          # 原檔不動
    assert not (tmp_path / "[A] Show [01].ass.bak").exists()  # 不備份
    produced = out_dir / "[A] Show [01].ass"
    updated = pysubs2.SSAFile.from_string(produced.read_text(encoding="utf-8-sig"))
    assert updated.styles["Default"].fontsize == 48


def test_process_file_missing_style_skipped(tmp_path):
    sub = _write_sample(tmp_path)
    profile = make_profile(target_style_names=["沒有這個"])
    report = process_file(MatchResult(sub_path=sub, episode=1), profile, None)
    assert report.status == "skipped"
    assert not (tmp_path / "[A] Show [01].ass.bak").exists()  # 沒改就不備份


def test_process_file_corrupt_is_error(tmp_path):
    sub = tmp_path / "bad [01].ass"
    sub.write_text("this is not a subtitle file", encoding="utf-8")
    report = process_file(MatchResult(sub_path=sub, episode=1), make_profile(), None)
    assert report.status == "error"


def test_process_file_logs_metadata(tmp_path):
    sub = _write_sample(tmp_path)
    match = MatchResult(sub_path=sub, episode=1, video_resolution=(640, 480))
    report = process_file(match, make_profile(), None)
    joined = "\n".join(report.messages)
    assert "ScaledBorderAndShadow: unset" in joined
    assert "1280x720" in joined       # 縮放參考解析度
    assert "長寬比" in joined          # 720p PlayRes vs 4:3 影片 -> 警告


def test_scan_folder_matches_and_warns_without_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.batch_runner.ffprobe_available", lambda: False
    )
    _write_sample(tmp_path, "[A] Show [01].ass")
    (tmp_path / "[B] Show - 01 [x].mkv").write_bytes(b"")
    scan = scan_folder(tmp_path)
    assert len(scan.matches) == 1
    assert scan.matches[0].status == "matched"
    assert scan.matches[0].video_resolution is None
    assert any("ffprobe" in w for w in scan.warnings)


def test_scan_folder_empty_warns(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ass_style_tool.batch_runner.ffprobe_available", lambda: False
    )
    scan = scan_folder(tmp_path)
    assert scan.matches == []
    assert any("找不到" in w for w in scan.warnings)


def test_run_batch_continues_after_error(tmp_path):
    good = _write_sample(tmp_path, "[A] Show [01].ass")
    bad = tmp_path / "[A] Show [02].ass"
    bad.write_text("garbage", encoding="utf-8")
    scan = ScanResult(
        matches=[
            MatchResult(sub_path=good, episode=1),
            MatchResult(sub_path=bad, episode=2),
        ],
        warnings=[],
    )
    seen: list[FileReport] = []
    reports = run_batch(scan, make_profile(), None, progress_cb=seen.append)
    assert [r.status for r in reports] == ["ok", "error"]
    assert len(seen) == 2


def test_run_batch_isolates_apply_failure(tmp_path):
    good = _write_sample(tmp_path, "[A] Show [01].ass")
    also_good = _write_sample(tmp_path, "[A] Show [02].ass")
    bad_profile = make_profile()
    bad_profile.style.alignment = 99  # bypasses load_profile validation
    scan = ScanResult(
        matches=[
            MatchResult(sub_path=good, episode=1),
            MatchResult(sub_path=also_good, episode=2),
        ],
        warnings=[],
    )
    reports = run_batch(scan, bad_profile, None)
    assert [r.status for r in reports] == ["error", "error"]  # both fail, none aborts


def test_inplace_rerun_preserves_original_backup(tmp_path):
    sub = _write_sample(tmp_path)
    original_bytes = sub.read_bytes()
    match = MatchResult(sub_path=sub, episode=1)
    assert process_file(match, make_profile(), None).status == "ok"
    assert process_file(match, make_profile(), None).status == "ok"  # 重跑
    backup = tmp_path / "[A] Show [01].ass.bak"
    assert backup.read_bytes() == original_bytes  # 備份仍是最初原始檔


def test_run_batch_output_dir_name_collision_errors(tmp_path):
    sub_a = _write_sample(tmp_path, "[A] Show [01].ass")
    nested = tmp_path / "nested"
    nested.mkdir()
    sub_b = nested / "[A] Show [01].ass"
    sub_b.write_bytes(sub_a.read_bytes())
    out_dir = tmp_path / "out"
    scan = ScanResult(
        matches=[
            MatchResult(sub_path=sub_a, episode=1),
            MatchResult(sub_path=sub_b, episode=1),
        ],
        warnings=[],
    )
    reports = run_batch(scan, make_profile(), out_dir)
    assert [r.status for r in reports] == ["ok", "error"]
    assert "衝突" in reports[1].messages[0]


def test_output_dir_collision_only_counts_written_files(tmp_path):
    bad = tmp_path / "[A] Show [01].ass"
    bad.write_text("garbage", encoding="utf-8")  # 會是 error,不會寫出
    nested = tmp_path / "nested"
    nested.mkdir()
    good = nested / "[A] Show [01].ass"
    good.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    out_dir = tmp_path / "out"
    scan = ScanResult(
        matches=[
            MatchResult(sub_path=bad, episode=1),
            MatchResult(sub_path=good, episode=1),
        ],
        warnings=[],
    )
    reports = run_batch(scan, make_profile(), out_dir)
    assert [r.status for r in reports] == ["error", "ok"]  # 第二個不被誤判衝突
    assert (out_dir / "[A] Show [01].ass").exists()


# ---------- SRT 輸入支援 ----------

_SRT_SAMPLE = """1
00:00:01,000 --> 00:00:04,000
Hello world
"""


def test_srt_output_dir_produces_ass(tmp_path):
    src = tmp_path / "movie.srt"
    src.write_text(_SRT_SAMPLE, encoding="utf-8")
    out_dir = tmp_path / "out"
    match = MatchResult(sub_path=src, episode=1, video_path=None,
                        status="no_video")
    report = process_file(match, make_profile(), out_dir)
    assert report.status == "ok"
    assert (out_dir / "movie.ass").exists()
    assert not (out_dir / "movie.srt").exists()
    assert src.exists()                            # 原始 .srt 不動
    subs = pysubs2.SSAFile.from_string(
        (out_dir / "movie.ass").read_text(encoding="utf-8-sig"))
    assert len(subs.events) == 1                   # 產出的是合法 ASS


def test_srt_inplace_makes_new_ass_no_backup(tmp_path):
    src = tmp_path / "movie.srt"
    src.write_text(_SRT_SAMPLE, encoding="utf-8")
    match = MatchResult(sub_path=src, episode=1, video_path=None,
                        status="no_video")
    report = process_file(match, make_profile(), None)
    assert report.status == "ok"
    assert (tmp_path / "movie.ass").exists()       # 同資料夾產生 .ass
    assert src.exists()                            # 原 .srt 保留
    assert not (tmp_path / "movie.srt.bak").exists()  # 無備份


def test_srt_apply_style_ignores_target_style_names(tmp_path):
    # SRT 轉換後只有單一 "Default" 樣式;即使 profile 指定的目標樣式名稱
    # 不是 "Default"(例如常見的自訂字幕組樣式名),仍應套用到這唯一樣式,
    # 而不是像過去那樣因為名稱對不上而整批 skip、不輸出任何檔案。
    src = tmp_path / "movie.srt"
    src.write_text(_SRT_SAMPLE, encoding="utf-8")
    out_dir = tmp_path / "out"
    match = MatchResult(sub_path=src, episode=1, video_path=None,
                        status="no_video")
    profile = make_profile(target_style_names=["某個非Default的名字"])
    report = process_file(match, profile, out_dir)
    assert report.status == "ok"
    produced = out_dir / "movie.ass"
    assert produced.exists()
    subs = pysubs2.SSAFile.from_string(
        produced.read_text(encoding="utf-8-sig"))
    assert subs.styles["Default"].fontname == "思源黑體 CN"  # make_profile() 的字型


def test_ass_source_with_nonmatching_target_still_skips(tmp_path):
    # 迴歸測試:.ass/.ssa 來源仍須維持既有的精確名稱比對行為,
    # 目標樣式名稱對不上時整批略過、不輸出檔案。
    sub = _write_sample(tmp_path)
    profile = make_profile(target_style_names=["沒有這個"])
    out_dir = tmp_path / "out"
    report = process_file(MatchResult(sub_path=sub, episode=1), profile, out_dir)
    assert report.status == "skipped"
    assert not (out_dir / "[A] Show [01].ass").exists()


def test_run_batch_collision_srt_and_ass_normalized(tmp_path):
    # 同資料夾 ep1.srt 與 ep1.ass,輸出都會是 ep1.ass -> run_batch 應判定衝突
    srt = tmp_path / "ep1.srt"
    srt.write_text(_SRT_SAMPLE, encoding="utf-8")
    ass = tmp_path / "ep1.ass"
    ass.write_text(pysubs2.SSAFile.from_string(_SRT_SAMPLE).to_string("ass"),
                   encoding="utf-8-sig")
    scan = ScanResult(matches=[
        MatchResult(sub_path=srt, episode=1, video_path=None, status="no_video"),
        MatchResult(sub_path=ass, episode=1, video_path=None, status="no_video"),
    ])
    out_dir = tmp_path / "out"
    reports = run_batch(scan, make_profile(), out_dir)
    statuses = [r.status for r in reports]
    assert statuses.count("error") == 1            # 第二個因輸出檔名衝突被擋
    assert (out_dir / "ep1.ass").exists()
