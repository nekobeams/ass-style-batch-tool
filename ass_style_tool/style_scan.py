"""字幕檔樣式的掃描與彙整(純邏輯,不依賴 Qt)。

掃描階段只需要知道「這個檔案有哪些樣式、各自多大、PlayRes 多少」,
不必把整份事件行搬進 GUI。獨立成一層是為了能直接拿真實 .ass 檔測,
不必啟動 Qt。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .ass_style import get_play_res, load_subs


@dataclass
class FileStyles:
    """單一字幕檔的樣式掃描結果。

    error 不為 None 時 styles/play_res 無意義——讀檔或解析失敗了,但掃描
    不會因此中斷(與 batch_runner 單檔失敗不中斷整批的作法一致)。
    """
    path: Path
    styles: Dict[str, float] = field(default_factory=dict)
    play_res: Tuple[int, int] = (0, 0)
    error: Optional[str] = None


def scan_styles(path: Path) -> FileStyles:
    try:
        subs = load_subs(path)
    except Exception as exc:      # 壞檔不可讓整批掃描中斷
        return FileStyles(path=path, error=str(exc))
    styles = {name: float(style.fontsize)
              for name, style in subs.styles.items()}
    return FileStyles(path=path, styles=styles, play_res=get_play_res(subs))


@dataclass
class StyleSummary:
    names: List[str] = field(default_factory=list)
    inconsistent: List[Path] = field(default_factory=list)
    unreadable: List[Path] = field(default_factory=list)


def summarize(results: Sequence[FileStyles]) -> StyleSummary:
    """彙整整批掃描結果。

    inconsistent 只在各檔的樣式名集合不完全相同時才有內容——使用者的
    情境是全季一致,所以這是例外通報,不是常態顯示。
    """
    summary = StyleSummary()
    readable: List[FileStyles] = []
    for result in results:
        if result.error is not None:
            summary.unreadable.append(result.path)
        else:
            readable.append(result)

    all_names: set = set()
    for result in readable:
        all_names |= set(result.styles)
    summary.names = sorted(all_names)

    if not readable:
        return summary
    # 以「出現最廣的樣式名組合」當基準,其餘視為例外
    signatures = Counter(frozenset(r.styles) for r in readable)
    majority = signatures.most_common(1)[0][0]
    summary.inconsistent = [r.path for r in readable
                            if frozenset(r.styles) != majority]
    return summary
