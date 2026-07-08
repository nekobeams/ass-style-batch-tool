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
