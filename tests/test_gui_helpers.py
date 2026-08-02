from __future__ import annotations

from pathlib import Path

from ass_style_tool.batch_runner import ScanResult
from ass_style_tool.episode_match import MatchResult
from ass_style_tool.qt.gui_helpers import (PreviewRow, font_is_missing,
                                           preview_rows)


def test_preview_rows_matched():
    scan = ScanResult(matches=[
        MatchResult(sub_path=Path("a [01].ass"), episode=1,
                    video_path=Path("v01.mkv"),
                    video_resolution=(1920, 1080), status="matched"),
    ], warnings=[])
    rows = preview_rows(scan)
    assert len(rows) == 1
    r = rows[0]
    assert r.episode == "01"
    assert r.sub_name == "a [01].ass"
    assert r.video_name == "v01.mkv"
    assert r.status_label == "已配對"


def test_preview_rows_no_video_and_no_episode():
    scan = ScanResult(matches=[
        MatchResult(sub_path=Path("x [03].ass"), episode=3,
                    video_path=None, status="no_video"),
        MatchResult(sub_path=Path("opening.ass"), episode=None,
                    status="no_episode"),
    ], warnings=[])
    rows = preview_rows(scan)
    assert rows[0].video_name == "-"
    assert rows[0].episode == "03"
    assert rows[0].status_label == "無對應影片"
    assert rows[1].episode == "?"
    assert rows[1].status_label == "無法判斷集數"


def test_preview_rows_ambiguous():
    scan = ScanResult(matches=[
        MatchResult(sub_path=Path("a [01].ass"), episode=1, status="ambiguous"),
    ], warnings=[])
    assert preview_rows(scan)[0].status_label == "配對模糊"


def test_font_missing_true():
    assert font_is_missing("思源黑體 CN", ["Arial", "Microsoft JhengHei"]) is True


def test_font_missing_false_case_insensitive():
    assert font_is_missing("arial", ["Arial", "MS Gothic"]) is False


def test_font_missing_empty_name_is_not_missing():
    assert font_is_missing("  ", ["Arial"]) is False


# ---------- 字幕行清單 ----------
import pysubs2

from ass_style_tool.qt.gui_helpers import (DialogueLine, dialogue_lines,
                                           format_timestamp)


def test_format_timestamp():
    assert format_timestamp(0) == "0:00:00.00"
    assert format_timestamp(1000) == "0:00:01.00"
    assert format_timestamp(61230) == "0:01:01.23"
    assert format_timestamp(3600000 + 125450) == "1:02:05.45"


def _subs_from(text: str) -> pysubs2.SSAFile:
    return pysubs2.SSAFile.from_string(text)


LINES_SAMPLE = (
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, Outline, Shadow\n"
    "Style: Default,Arial,40,2,1\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\fs40}大字\\N第二行\n"
    "Comment: 0,0:00:02.00,0:00:04.00,Default,,0,0,0,,這是註解事件\n"
    "Dialogue: 0,0:00:05.50,0:00:07.00,Default,,0,0,0,,一般對白\n"
)


def test_dialogue_lines_skips_comments_and_strips_tags():
    lines = dialogue_lines(_subs_from(LINES_SAMPLE))
    assert len(lines) == 2
    assert lines[0].start_ms == 1000
    assert lines[0].text == "大字 第二行"   # 標籤去除、\N 摺成空格
    assert lines[1].start_ms == 5500


def test_dialogue_lines_empty():
    empty = LINES_SAMPLE.split("[Events]")[0] + "[Events]\n" \
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    assert dialogue_lines(_subs_from(empty)) == []


# ---------- 「預計」欄文字 ----------

from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values
from ass_style_tool.qt.gui_helpers import apply_plan_text, scale_plan_text
from ass_style_tool.scale_engine import ScaleOptions
from ass_style_tool.style_scan import FileStyles


def _profile(**overrides):
    values = dict(DEFAULT_VALUES)
    values.update(overrides)
    return profile_from_values(values)


def test_apply_plan_text_shows_old_and_new_size():
    fs = FileStyles(Path("a.ass"), {"Default": 48.0}, (1920, 1080))
    # base 1920x1080、fontsize 72 → 縮放係數 1.0,預計 48 → 72
    text = apply_plan_text(fs, _profile(fontsize="72"), ["Default"])
    assert text == "Default 48 → 72"


def test_apply_plan_text_scales_by_play_res():
    fs = FileStyles(Path("a.ass"), {"Default": 24.0}, (960, 540))
    # 960x540 相對於基準 1920x1080 是 0.5 倍 → 72 * 0.5 = 36
    text = apply_plan_text(fs, _profile(fontsize="72"), ["Default"])
    assert text == "Default 24 → 36"


def test_apply_plan_text_marks_missing_style():
    """精確比對整串:子字串斷言(「找不到」in text)抓不到 ⊘ 標記被拿掉、
    多個樣式名的「、」連接壞掉、或前後間距跑掉——而這一格的文字就是使用者
    用來判斷「這個檔會不會被改」的唯一依據(最終審查 Minor)。"""
    fs = FileStyles(Path("a.ass"), {"CHS": 48.0}, (1920, 1080))
    text = apply_plan_text(fs, _profile(), ["Default"])
    assert text == "⊘ 找不到 Default"


def test_apply_plan_text_missing_style_joins_multiple_names():
    """多個目標樣式全都找不到時,用「、」連接(不是 Python 的 list repr,
    也不是逗號)——這條路徑先前完全沒有測試覆蓋。"""
    fs = FileStyles(Path("a.ass"), {"CHS": 48.0}, (1920, 1080))
    text = apply_plan_text(fs, _profile(), ["Default", "Sign"])
    assert text == "⊘ 找不到 Default、Sign"


def test_apply_plan_text_joins_multiple_found_styles():
    """成功路徑的多樣式連接也同樣沒被測過。"""
    fs = FileStyles(Path("a.ass"), {"Default": 48.0, "Sign": 24.0},
                    (1920, 1080))
    text = apply_plan_text(fs, _profile(fontsize="72"), ["Default", "Sign"])
    assert text == "Default 48 → 72、Sign 24 → 72"


def test_apply_plan_text_with_no_file_styles():
    """file_styles 為 None(該檔還沒掃到樣式)回空字串,不是拋例外。"""
    assert apply_plan_text(None, _profile(), ["Default"]) == ""


def test_apply_plan_text_marks_unreadable_file():
    fs = FileStyles(Path("a.ass"), error="讀取失敗")
    assert apply_plan_text(fs, _profile(), ["Default"]) == "⚠ 無法讀取"


def test_apply_plan_text_with_no_selection():
    fs = FileStyles(Path("a.ass"), {"Default": 48.0}, (1920, 1080))
    assert apply_plan_text(fs, _profile(), []) == "⊘ 未選樣式"


def test_scale_plan_text_uses_factor():
    fs = FileStyles(Path("a.ass"), {"Default": 40.0}, (1920, 1080))
    text = scale_plan_text(fs, ScaleOptions(factor=1.5, base_style="Default"))
    assert text == "Default 40 → 60(×1.5)"


def test_scale_plan_text_derives_factor_from_target_size():
    fs = FileStyles(Path("a.ass"), {"Default": 40.0}, (1920, 1080))
    text = scale_plan_text(fs,
                           ScaleOptions(target_size=60, base_style="Default"))
    assert text == "Default 40 → 60(×1.5)"


def test_scale_plan_text_marks_missing_base_style():
    """同上,精確比對整串而不是子字串。"""
    fs = FileStyles(Path("a.ass"), {"CHS": 40.0}, (1920, 1080))
    text = scale_plan_text(fs, ScaleOptions(factor=1.5, base_style="Default"))
    assert text == "⊘ 找不到基準樣式 Default"


def test_scale_plan_text_with_no_file_styles():
    """file_styles 為 None 回空字串,不是拋例外(先前未覆蓋)。"""
    assert scale_plan_text(
        None, ScaleOptions(factor=1.5, base_style="Default")) == ""


def test_scale_plan_text_without_factor_or_target_size():
    """factor 與 target_size 都沒給時回空字串——這條分支先前完全沒被
    測過,而 ScaleOptions 允許兩者皆 None。"""
    fs = FileStyles(Path("a.ass"), {"Default": 40.0}, (1920, 1080))
    assert scale_plan_text(fs, ScaleOptions(base_style="Default")) == ""


def test_scale_plan_text_marks_zero_base_size_instead_of_blank():
    """Minor bullet:target_size 模式下基準樣式大小是 0 時,舊行為是走進
    `elif options.target_size is not None and base:` 的 else 分支回傳
    空字串——跟本函式其他早退路徑(⚠/⊘)不一致,也讓「還沒算過」跟
    「算過但沒東西可縮放」分不出來。"""
    fs = FileStyles(Path("a.ass"), {"Default": 0.0}, (1920, 1080))
    text = scale_plan_text(fs, ScaleOptions(target_size=60, base_style="Default"))
    assert text == "⚠ 基準樣式大小為 0,無法縮放"


# ---------- I3:.srt 來源的預計欄要反映 batch_runner 的 is_ass_family 分支 ----------

def test_apply_plan_text_srt_source_shows_convert_all_marker():
    """batch_runner.process_file 對 .srt 來源會用
    apply_to_all_styles=True(忽略 target_style_names,轉檔後套用到全部
    樣式)。apply_plan_text 預設(convert_all_if_srt=True,字幕檔分頁的
    實際呼叫方式)必須反映這點,不能沿用「找不到 X」的措辭——那句話暗示
    這個檔案不會被處理,但實際上它會被轉成 .ass 且全部樣式都被改。"""
    fs = FileStyles(Path("a.srt"), {"Default": 48.0}, (1920, 1080))
    text = apply_plan_text(fs, _profile(), ["CHT"])   # CHT 不在檔案裡
    assert "找不到" not in text
    assert "全部樣式" in text


def test_apply_plan_text_ass_source_unaffected_by_srt_branch():
    """.ass/.ssa 來源不受這個新分支影響,行為不變。"""
    fs = FileStyles(Path("a.ass"), {"Default": 48.0}, (1920, 1080))
    text = apply_plan_text(fs, _profile(fontsize="72"), ["Default"])
    assert text == "Default 48 → 72"


def test_apply_plan_text_srt_source_with_convert_all_disabled():
    """封裝分頁(mux_tab.py)透過 mkv_mux.process_mux ->
    mkv_batch.transform_track_file 執行,那條路徑沒有
    apply_to_all_styles=True——呼叫端傳 convert_all_if_srt=False 時,.srt
    來源要走跟 .ass 完全一樣的邏輯(找得到就換算,找不到就『找不到』),
    不能被 I3 的規則誤套用到一個實際不會發生的行為上。"""
    fs = FileStyles(Path("a.srt"), {"CHS": 48.0}, (1920, 1080))
    text = apply_plan_text(fs, _profile(), ["Default"],
                           convert_all_if_srt=False)
    assert text == "⊘ 找不到 Default"


# ---------- C2:封裝分頁的「找不到」不是「略過」,是「原樣封裝」 ----------

def test_apply_plan_text_not_found_suffix_customizable():
    """mux_tab.py 呼叫時要能把『找不到』的後果講清楚——process_mux 對
    找不到目標樣式的字幕是原樣封裝、不套用樣式,report.status 仍是
    "ok",不是整個流程被跳過(字幕檔分頁的「找不到」才是真的跳過)。"""
    fs = FileStyles(Path("a.ass"), {"CHS": 48.0}, (1920, 1080))
    text = apply_plan_text(fs, _profile(), ["Default"],
                           not_found_suffix=",將原樣封裝")
    assert text == "⊘ 找不到 Default,將原樣封裝"


def test_apply_plan_text_not_found_suffix_defaults_to_blank():
    """預設(字幕檔分頁的呼叫方式)不附加任何後綴,維持既有文字——
    batch_runner.process_file 的「找不到」確實等於「這個檔會被跳過」。"""
    fs = FileStyles(Path("a.ass"), {"CHS": 48.0}, (1920, 1080))
    text = apply_plan_text(fs, _profile(), ["Default"])
    assert text == "⊘ 找不到 Default"


def test_preview_rows_carries_plan_text():
    from ass_style_tool.batch_runner import ScanResult
    from ass_style_tool.episode_match import MatchResult
    from ass_style_tool.qt.gui_helpers import preview_rows
    scan = ScanResult(matches=[MatchResult(Path("a.ass"), 1, status="no_video")])
    rows = preview_rows(scan, {Path("a.ass"): "Default 48 → 72"})
    assert rows[0].plan == "Default 48 → 72"


def test_preview_rows_plan_defaults_to_blank():
    from ass_style_tool.batch_runner import ScanResult
    from ass_style_tool.episode_match import MatchResult
    from ass_style_tool.qt.gui_helpers import preview_rows
    scan = ScanResult(matches=[MatchResult(Path("a.ass"), 1, status="no_video")])
    assert preview_rows(scan)[0].plan == ""
