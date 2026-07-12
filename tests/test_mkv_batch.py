from __future__ import annotations

from pathlib import Path

import pysubs2

from ass_style_tool.mkv_io import SubtitleTrack
from ass_style_tool.mkv_batch import (MkvFileReport, MkvTools, process_mkv,
                                      select_same_type, track_key,
                                      transform_track_file)
from ass_style_tool.scale_engine import ScaleOptions
from tests.test_ass_style import SAMPLE_ASS
from tests.test_profile import make_profile

TOOLS = MkvTools(mkvmerge=Path("mkvmerge.exe"), mkvextract=Path("mkvextract.exe"))


def _track(tid, lang="chi", name="繁中"):
    return SubtitleTrack(tid, "S_TEXT/ASS", lang, name, False, False)


# ---------- 一鍵選整季 ----------

def test_track_key():
    assert track_key(_track(2)) == ("chi", "繁中")


def test_select_same_type_matches_by_lang_and_name():
    reference = [_track(2, "chi", "繁中")]
    files = {
        Path("e1.mkv"): [_track(2, "chi", "繁中"), _track(3, "chi", "简中")],
        Path("e2.mkv"): [_track(5, "chi", "简中"), _track(7, "chi", "繁中")],
        Path("e3.mkv"): [_track(1, "jpn", "")],
    }
    result = select_same_type(reference, files)
    assert result[Path("e1.mkv")] == {2}
    assert result[Path("e2.mkv")] == {7}   # 依 key 而非軌號
    assert result[Path("e3.mkv")] == set()


def test_select_same_type_multiple_reference():
    reference = [_track(2, "chi", "繁中"), _track(3, "chi", "简中")]
    files = {Path("e1.mkv"): [_track(4, "chi", "简中"), _track(5, "chi", "繁中")]}
    assert select_same_type(reference, files)[Path("e1.mkv")] == {4, 5}


# ---------- transform_track_file ----------

def _write_ass(tmp_path, name="in.ass"):
    p = tmp_path / name
    p.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    return p


def test_transform_profile_modifies(tmp_path):
    src = _write_ass(tmp_path)
    dst = tmp_path / "out.ass"
    changed, msgs = transform_track_file(src, dst, make_profile())
    assert changed is True
    subs = pysubs2.SSAFile.from_string(dst.read_text(encoding="utf-8-sig"))
    assert subs.styles["Default"].fontname == "思源黑體 CN"


def test_transform_profile_missing_style_not_changed(tmp_path):
    src = _write_ass(tmp_path)
    dst = tmp_path / "out.ass"
    changed, msgs = transform_track_file(
        src, dst, make_profile(target_style_names=["沒有這個"]))
    assert changed is False
    assert not dst.exists()


def test_transform_scale(tmp_path):
    src = _write_ass(tmp_path)
    dst = tmp_path / "out.ass"
    changed, msgs = transform_track_file(src, dst, ScaleOptions(factor=2))
    assert changed is True
    assert "Style: Default,Arial,80," in dst.read_text(encoding="utf-8-sig")


# ---------- process_mkv ----------

def _fake_extract_ok(tmp_path):
    def fn(mkv, tid, out, mkvextract):
        Path(out).write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
        return True
    return fn


def test_process_mkv_outdir_ok(tmp_path):
    calls = {}

    def fake_remux(mkv, out, replacements, mkvmerge, progress_cb=None):
        calls["out"] = Path(out)
        calls["repl"] = replacements
        Path(out).write_bytes(b"fake mkv")
        if progress_cb:
            progress_cb(100)
        return True

    out = tmp_path / "outdir" / "show.mkv"
    report = process_mkv(
        Path("show.mkv"), [_track(2)], make_profile(), TOOLS,
        out_path=out,
        extract_fn=_fake_extract_ok(tmp_path), remux_fn=fake_remux)
    assert report.status == "ok"
    assert calls["out"] == out
    assert len(calls["repl"]) == 1
    assert calls["repl"][0].track.track_id == 2
    assert out.exists()


def test_process_mkv_unchanged_track_kept(tmp_path):
    """未修改的勾選軌以原抽出內容放回,不可遺失。"""
    seen = {}

    def fake_remux(mkv, out, replacements, mkvmerge, progress_cb=None):
        seen["repl"] = list(replacements)
        Path(out).write_bytes(b"x")
        return True

    profile = make_profile(target_style_names=["沒有這個"])
    report = process_mkv(
        Path("s.mkv"), [_track(2)], profile, TOOLS,
        out_path=tmp_path / "o.mkv",
        extract_fn=_fake_extract_ok(tmp_path), remux_fn=fake_remux)
    # 唯一勾選軌未被修改 → 無需重封裝,整檔 skipped
    assert report.status == "skipped"
    assert "repl" not in seen


def test_process_mkv_mixed_changed_and_unchanged(tmp_path):
    """兩軌其一有改:重封裝需包含兩軌(未改軌用原內容)。"""
    def fake_extract(mkv, tid, out, mkvextract):
        text = SAMPLE_ASS if tid == 2 else SAMPLE_ASS.replace(
            "Style: Default", "Style: Other")
        Path(out).write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
        return True

    seen = {}

    def fake_remux(mkv, out, replacements, mkvmerge, progress_cb=None):
        seen["ids"] = [r.track.track_id for r in replacements]
        Path(out).write_bytes(b"x")
        return True

    report = process_mkv(
        Path("s.mkv"), [_track(2), _track(3)], make_profile(), TOOLS,
        out_path=tmp_path / "o.mkv",
        extract_fn=fake_extract, remux_fn=fake_remux)
    assert report.status == "ok"
    assert sorted(seen["ids"]) == [2, 3]


def test_process_mkv_extract_fail_is_error(tmp_path):
    report = process_mkv(
        Path("s.mkv"), [_track(2)], make_profile(), TOOLS,
        out_path=tmp_path / "o.mkv",
        extract_fn=lambda *a: False,
        remux_fn=lambda *a, **k: True)
    assert report.status == "error"


def test_process_mkv_remux_fail_is_error(tmp_path):
    report = process_mkv(
        Path("s.mkv"), [_track(2)], make_profile(), TOOLS,
        out_path=tmp_path / "o.mkv",
        extract_fn=_fake_extract_ok(tmp_path),
        remux_fn=lambda *a, **k: False)
    assert report.status == "error"


def test_process_mkv_replace_original_verify_and_swap(tmp_path):
    original = tmp_path / "show.mkv"
    original.write_bytes(b"ORIGINAL")

    def fake_remux(mkv, out, replacements, mkvmerge, progress_cb=None):
        Path(out).write_bytes(b"NEW CONTENT")
        return True

    report = process_mkv(
        original, [_track(2)], make_profile(), TOOLS,
        out_path=None,                      # 取代原檔模式
        extract_fn=_fake_extract_ok(tmp_path),
        remux_fn=fake_remux,
        verify_fn=lambda p, m: True)
    assert report.status == "ok"
    assert original.read_bytes() == b"NEW CONTENT"   # 已覆蓋
    assert not original.with_name(original.name + ".tmp.mkv").exists()


def test_process_mkv_replace_original_os_replace_fail_is_error(tmp_path, monkeypatch):
    """os.replace 失敗(如原檔被占用)時:回傳 error、清掉暫存檔、原檔不變。"""
    original = tmp_path / "show.mkv"
    original.write_bytes(b"ORIGINAL")

    def fake_remux(mkv, out, replacements, mkvmerge, progress_cb=None):
        Path(out).write_bytes(b"NEW CONTENT")
        return True

    def fake_replace(src, dst):
        raise OSError("target busy")

    monkeypatch.setattr("ass_style_tool.mkv_batch.os.replace", fake_replace)

    report = process_mkv(
        original, [_track(2)], make_profile(), TOOLS,
        out_path=None,
        extract_fn=_fake_extract_ok(tmp_path),
        remux_fn=fake_remux,
        verify_fn=lambda p, m: True)
    assert report.status == "error"
    assert original.read_bytes() == b"ORIGINAL"      # 原檔未變動
    assert not original.with_name(original.name + ".tmp.mkv").exists()  # 暫存已清


def test_process_mkv_replace_original_verify_fail_keeps_original(tmp_path):
    original = tmp_path / "show.mkv"
    original.write_bytes(b"ORIGINAL")

    def fake_remux(mkv, out, replacements, mkvmerge, progress_cb=None):
        Path(out).write_bytes(b"BROKEN")
        return True

    report = process_mkv(
        original, [_track(2)], make_profile(), TOOLS,
        out_path=None,
        extract_fn=_fake_extract_ok(tmp_path),
        remux_fn=fake_remux,
        verify_fn=lambda p, m: False)       # 驗證失敗
    assert report.status == "error"
    assert original.read_bytes() == b"ORIGINAL"      # 原檔保留
    assert not original.with_name(original.name + ".tmp.mkv").exists()  # 暫存已清
