from __future__ import annotations

import pysubs2

from ass_style_tool.batch_runner import ScanResult
from ass_style_tool.episode_match import MatchResult
from tests.test_profile import make_profile

_SRT = "1\n00:00:01,000 --> 00:00:04,000\nHi\n"


def test_batchworker_collision_srt_vs_ass(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import BatchWorker
    # 同資料夾 ep1.srt 與 ep1.ass,兩者輸出都會是 ep1.ass -> 應判定衝突
    srt = tmp_path / "ep1.srt"
    srt.write_text(_SRT, encoding="utf-8")
    ass = tmp_path / "ep1.ass"
    ass.write_text(pysubs2.SSAFile.from_string(_SRT).to_string("ass"),
                   encoding="utf-8-sig")
    scan = ScanResult(matches=[
        MatchResult(sub_path=srt, episode=1, video_path=None, status="no_video"),
        MatchResult(sub_path=ass, episode=1, video_path=None, status="no_video"),
    ])
    out_dir = tmp_path / "out"
    worker = BatchWorker(scan, make_profile(), out_dir)
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    # 第一個成功寫 ep1.ass,第二個因輸出檔名衝突被擋 -> error >= 1
    assert done["error"] >= 1
    assert (out_dir / "ep1.ass").exists()
