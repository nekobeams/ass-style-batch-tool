"""共用的字幕/軌道語言清單(mkvmerge 用 ISO 639-2 書目碼)。

被 qt.mux_tab(附加字幕軌的語言下拉選單)與 qt.modify_tracks_dialog(既有
軌道的語言修改欄)共用,避免同一份清單在兩處各自維護、彼此走鐘。
最常用的三個排最前面維持原本的順手程度,「未定」保持在最後。
"""
from __future__ import annotations

from typing import List, Tuple

LANGUAGES: List[Tuple[str, str]] = [
    ("中文", "chi"), ("日文", "jpn"), ("英文", "eng"),
    ("韓文", "kor"), ("西班牙文", "spa"), ("法文", "fre"),
    ("德文", "ger"), ("義大利文", "ita"), ("葡萄牙文", "por"),
    ("俄文", "rus"), ("泰文", "tha"), ("越南文", "vie"),
    ("印尼文", "ind"), ("阿拉伯文", "ara"),
    ("未定", "und"),
]
