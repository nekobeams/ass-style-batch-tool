"""GUI 用的純邏輯輔助:預覽表格列建構、字型缺失判斷(不依賴 Qt)。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..ass_style import compute_applied_values
from ..profile import Profile
from ..scale_engine import ScaleOptions, fmt_num
from ..style_scan import FileStyles

STATUS_LABELS = {
    "matched": "已配對",
    "no_video": "無對應影片",
    "ambiguous": "配對模糊",
    "no_episode": "無法判斷集數",
}

# 「預計 / 結果」欄在批次執行完成後顯示的狀態圖示;三個分頁(字幕檔/封裝/
# MKV)的 worker.file_done 狀態值(ok|skipped|error)是同一組,共用同一份
# 對照表,避免各分頁各自維護一份容易日後漂移不一致。
RESULT_ICONS = {"ok": "✓ 已套用", "skipped": "⊘ 略過", "error": "✗ 失敗"}

# 開始批次執行時,每一列「會被這批工作處理」的儲存格先被標成這個文字,
# 避免舊一輪的結果被誤讀成這次的。三個分頁的 mark_rows_pending()/
# _set_row_result() 共用同一份文字,以免各自維護導致不同步。
PENDING_TEXT = "處理中…"

# 使用者取消批次執行時,BatchWorker/ScaleWorker/MuxWorker/MkvWorker 的
# run() 迴圈一偵測到取消旗標就直接 break,尚未輪到的檔案不會發出
# file_done——如果收尾時不處理,這些列會永遠卡在 PENDING_TEXT,被誤讀成
# 還在跑,或跟這次批次的結果搞混。三個分頁的 _on_finished 都要在收尾時
# 把還卡著 PENDING_TEXT 的列換成這個明確標記(Task 10 review Finding 2)。
CANCELLED_TEXT = "⊘ 未執行(已取消)"


@dataclass
class PreviewRow:
    episode: str
    sub_name: str
    video_name: str
    status_label: str
    plan: str = ""


def preview_rows(scan,
                 plans: Optional[Dict[Path, str]] = None) -> List[PreviewRow]:
    plans = plans or {}
    rows: List[PreviewRow] = []
    for m in scan.matches:
        episode = f"{m.episode:02d}" if m.episode is not None else "?"
        video = m.video_path.name if m.video_path is not None else "-"
        rows.append(PreviewRow(
            episode=episode,
            sub_name=m.sub_path.name,
            video_name=video,
            status_label=STATUS_LABELS.get(m.status, m.status),
            plan=plans.get(m.sub_path, ""),
        ))
    return rows


def font_is_missing(fontname: str, available_families: List[str]) -> bool:
    name = fontname.strip().lower()
    if not name:
        return False
    return name not in {fam.lower() for fam in available_families}


@dataclass
class DialogueLine:
    start_ms: int
    end_ms: int
    text: str


def format_timestamp(ms: int) -> str:
    """毫秒 → 'H:MM:SS.cc'(ASS 慣用時間格式)。"""
    total_cs = int(round(ms / 10))
    hours, rem = divmod(total_cs, 360000)
    minutes, rem = divmod(rem, 6000)
    seconds, centis = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centis:02d}"


def dialogue_lines(subs) -> List[DialogueLine]:
    """取出非 Comment 的事件行;文字去 override 標籤、\\N 摺成空格。"""
    lines: List[DialogueLine] = []
    for event in subs.events:
        if event.is_comment:
            continue
        text = " ".join(event.plaintext.split())
        lines.append(DialogueLine(start_ms=event.start, end_ms=event.end,
                                  text=text))
    return lines


def apply_plan_text(file_styles: Optional[FileStyles], profile: Profile,
                    target_names: Sequence[str], *,
                    convert_all_if_srt: bool = True,
                    not_found_suffix: str = "") -> str:
    """「預計」欄文字:目標樣式在這個檔案會從幾號變成幾號。

    字級之外的欄位(外框/陰影/邊距)也會被改,但表格一欄塞不下,
    字級是最能一眼看出縮放對不對的代表值。

    convert_all_if_srt:呼叫端實際執行路徑對非 ASS/SSA 來源(判斷規則
    須與 batch_runner.process_file 的 is_ass_family 完全一致)是否會
    apply_to_all_styles=True——忽略 target_names,轉檔後套用到全部樣式。
    字幕檔分頁(subtitle_tab.py)透過 batch_runner.process_file 執行,
    確實會這樣做,預設值符合它的行為;封裝分頁(mux_tab.py)透過
    mkv_mux.process_mux → mkv_batch.transform_track_file 執行,那條路徑
    呼叫 apply_profile() 時並未帶 apply_to_all_styles=True,呼叫端必須
    明確傳入 False,否則預告文字會宣稱一個實際不會發生的「全部套用」
    (最終審查 Finding I3 的範圍不含封裝分頁,原因就在這裡)。

    not_found_suffix:目標樣式在檔案裡都找不到時,附加在
    「⊘ 找不到 X」後面的補充說明。字幕檔分頁的「找不到」確實等於
    「這個檔會被跳過」(對應 batch_runner.process_file 的行為),預設
    空字串維持原文字;封裝分頁的「找不到」實際上是「原樣封裝、不套用
    樣式」而不是整個流程被跳過(對應 mkv_mux.process_mux 的行為,見
    Finding C2),呼叫端要傳入能反映這點的文字,不然預告會誤導使用者
    以為「這個檔不會被動」,但輸出的 MKV 其實會被寫入/覆蓋。
    """
    if file_styles is None:
        return ""
    if file_styles.error is not None:
        return "⚠ 無法讀取"
    if not target_names:
        return "⊘ 未選樣式"
    is_ass_family = file_styles.path.suffix.lower() in {".ass", ".ssa"}
    if not is_ass_family and convert_all_if_srt:
        return "⚠ 非 ASS/SSA 來源,轉檔後將套用到全部樣式"
    applied = compute_applied_values(profile, *file_styles.play_res)
    parts = [
        f"{name} {fmt_num(file_styles.styles[name])} "
        f"→ {fmt_num(applied.fontsize)}"
        for name in target_names if name in file_styles.styles
    ]
    if not parts:
        return f"⊘ 找不到 {'、'.join(target_names)}{not_found_suffix}"
    return "、".join(parts)


def scale_plan_text(file_styles: Optional[FileStyles],
                    options: ScaleOptions) -> str:
    """縮放模式的「預計」欄文字。"""
    if file_styles is None:
        return ""
    if file_styles.error is not None:
        return "⚠ 無法讀取"
    base = file_styles.styles.get(options.base_style)
    if base is None:
        return f"⊘ 找不到基準樣式 {options.base_style}"
    if options.factor is not None:
        factor = options.factor
    elif options.target_size is not None:
        if not base:
            # 基準樣式大小是 0(合法值,只是沒意義):target_size / base 會
            # ZeroDivisionError,而且「0 → 任何值」的縮放係數本來就無法
            # 定義。跟本函式其他早退路徑一樣,不能留空白讓人誤讀成
            # 「還沒算過」(小修:Minor bullet)。
            return "⚠ 基準樣式大小為 0,無法縮放"
        factor = options.target_size / base
    else:
        return ""
    return (f"{options.base_style} {fmt_num(base)} "
            f"→ {fmt_num(base * factor)}(×{fmt_num(factor)})")
