"""等比縮放 ASS/SSA 字級的逐行引擎:保留編碼、換行與所有非目標內容。

刻意不用 pysubs2:pysubs2 會重寫整個檔案(欄位正規化、統一編碼與換行),
而本引擎的契約是「只改必要的數值,其餘位元組原樣保留」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


class ScaleError(ValueError):
    """檔案無法安全縮放(非 ASS 內容、基準樣式無效、選項矛盾等)。"""


@dataclass
class ScaleOptions:
    factor: Optional[float] = None
    target_size: Optional[float] = None
    base_style: str = "Default"
    scale_decorations: bool = True
    scale_inline_fs: bool = True
    scale_fscxy: bool = False

    def validate(self) -> None:
        if (self.factor is None) == (self.target_size is None):
            raise ScaleError("倍率與目標大小必須恰好指定一個")
        if self.factor is not None and self.factor <= 0:
            raise ScaleError("倍率必須大於 0")
        if self.target_size is not None and self.target_size <= 0:
            raise ScaleError("目標大小必須大於 0")


@dataclass
class StyleChange:
    name: str
    old_size: str
    new_size: str


@dataclass
class ScaleReport:
    style_changes: List[StyleChange] = field(default_factory=list)
    inline_fs_count: int = 0
    factor_used: float = 1.0


def fmt_num(value: float) -> str:
    """四捨五入到 1 位小數;能整數就輸出整數(不產生 '40.0')。"""
    rounded = round(value, 1)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.1f}"


_STYLES_SECTIONS = {"[v4+ styles]", "[v4 styles]"}
_EVENTS_SECTION = "[events]"

#: \fs 後必須緊接數字 → 自然排除 \fscx、\fscy、\fsp 等其他標籤
_FS_RE = re.compile(r"(\\fs)(\d+(?:\.\d+)?)")
_FSCXY_RE = re.compile(r"(\\fsc[xy])(\d+(?:\.\d+)?)")


def parse_format_indices(format_line: str) -> Dict[str, int]:
    """解析 'Format: ...' 行,回傳 {欄位小寫名: index}。不可寫死欄位位置。"""
    _, _, rest = format_line.partition(":")
    fields = [f.strip().lower() for f in rest.split(",")]
    return {name: i for i, name in enumerate(fields)}


def _split_line_ending(line: str) -> Tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def _replace_preserving_space(part: str, new_core: str) -> str:
    lead = part[: len(part) - len(part.lstrip())]
    trail = part[len(part.rstrip()):]
    return f"{lead}{new_core}{trail}"


def _iter_style_sizes(lines: List[str]):
    """依序產出 (style名, fontsize float);供目標模式找基準用。"""
    section = ""
    fmt: Optional[Dict[str, int]] = None
    for raw in lines:
        content, _ = _split_line_ending(raw)
        stripped = content.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.lower()
            fmt = None
            continue
        if section not in _STYLES_SECTIONS:
            continue
        low = stripped.lower()
        if low.startswith("format:"):
            fmt = parse_format_indices(content)
        elif low.startswith("style:") and fmt is not None and "fontsize" in fmt:
            _, _, rest = content.partition(":")
            parts = rest.split(",")
            idx = fmt["fontsize"]
            if len(parts) <= idx:
                continue
            name_idx = fmt.get("name", 0)
            name = parts[name_idx].strip() if len(parts) > name_idx else ""
            try:
                yield name, float(parts[idx].strip())
            except ValueError:
                continue


def _determine_factor(lines: List[str], options: ScaleOptions) -> float:
    if options.factor is not None:
        return options.factor
    first_size: Optional[float] = None
    base_size: Optional[float] = None
    for name, size in _iter_style_sizes(lines):
        if first_size is None:
            first_size = size
        if name == options.base_style:
            base_size = size
            break
    size = base_size if base_size is not None else first_size
    if size is None or size <= 0:
        raise ScaleError("找不到有效的基準 Style Fontsize")
    return options.target_size / size


def _scale_style_line(content: str, fmt: Dict[str, int], factor: float,
                      options: ScaleOptions, report: ScaleReport) -> str:
    prefix, colon, rest = content.partition(":")
    parts = rest.split(",")
    idx = fmt["fontsize"]
    if len(parts) <= idx:
        return content
    old_raw = parts[idx].strip()
    try:
        old_size = float(old_raw)
    except ValueError:
        return content
    name_idx = fmt.get("name", 0)
    name = parts[name_idx].strip() if len(parts) > name_idx else ""
    if options.target_size is not None and name == options.base_style:
        new_text = fmt_num(options.target_size)
    else:
        new_text = fmt_num(old_size * factor)
    parts[idx] = _replace_preserving_space(parts[idx], new_text)
    if options.scale_decorations:
        for key in ("outline", "shadow"):
            j = fmt.get(key)
            if j is not None and j < len(parts):
                try:
                    old_val = float(parts[j].strip())
                except ValueError:
                    continue
                parts[j] = _replace_preserving_space(
                    parts[j], fmt_num(old_val * factor))
    report.style_changes.append(
        StyleChange(name=name, old_size=old_raw, new_size=new_text))
    return prefix + colon + ",".join(parts)


def _scale_event_line(content: str, factor: float, options: ScaleOptions,
                      report: ScaleReport) -> str:
    low = content.lstrip().lower()
    if not (low.startswith("dialogue:") or low.startswith("comment:")):
        return content

    def _sub(match: "re.Match[str]") -> str:
        report.inline_fs_count += 1
        return match.group(1) + fmt_num(float(match.group(2)) * factor)

    if options.scale_inline_fs:
        content = _FS_RE.sub(_sub, content)
    if options.scale_fscxy:
        content = _FSCXY_RE.sub(_sub, content)
    return content


def scale_text(text: str, options: ScaleOptions) -> Tuple[str, ScaleReport]:
    """對整份 ASS 文字做等比縮放。回傳 (新文字, 報告);非 ASS 丟 ScaleError。"""
    options.validate()
    lines = text.splitlines(keepends=True)
    has_styles = any(
        _split_line_ending(l)[0].strip().lower() in _STYLES_SECTIONS
        for l in lines)
    if not has_styles:
        raise ScaleError("找不到 [V4+ Styles]/[V4 Styles],不是 ASS/SSA 內容")
    factor = _determine_factor(lines, options)
    report = ScaleReport(factor_used=factor)

    out: List[str] = []
    section = ""
    fmt: Optional[Dict[str, int]] = None
    for raw in lines:
        content, ending = _split_line_ending(raw)
        stripped = content.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.lower()
            fmt = None
            out.append(raw)
            continue
        if section in _STYLES_SECTIONS:
            low = stripped.lower()
            if low.startswith("format:"):
                fmt = parse_format_indices(content)
            elif (low.startswith("style:") and fmt is not None
                  and "fontsize" in fmt):
                content = _scale_style_line(content, fmt, factor, options,
                                            report)
        elif section == _EVENTS_SECTION:
            content = _scale_event_line(content, factor, options, report)
        out.append(content + ending)
    return "".join(out), report
