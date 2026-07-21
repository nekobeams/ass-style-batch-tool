"""等比縮放 ASS/SSA 字級的逐行引擎:保留編碼、換行與所有非目標內容。

刻意不用 pysubs2:pysubs2 會重寫整個檔案(欄位正規化、統一編碼與換行),
而本引擎的契約是「只改必要的數值,其餘位元組原樣保留」。
"""
from __future__ import annotations

import codecs
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from charset_normalizer import from_bytes


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


@dataclass
class SubtitleCodec:
    bom: bytes
    codec: str

    def decode(self, raw: bytes) -> str:
        return raw[len(self.bom):].decode(self.codec)

    def encode(self, text: str) -> bytes:
        return self.bom + text.encode(self.codec)


def _cjk_plausibility(text: str) -> float:
    """常用 CJK 統一漢字 + CJK 標點佔非 ASCII 字元的比例,用於消歧 Big5/GBK。

    兩者都是 DBCS 編碼,位元組範圍重疊,錯誤的編碼選擇仍可能「成功」解碼
    但落在較罕見的 Unicode 區段(如 CJK 擴充區、相容區)。
    """
    non_ascii = [c for c in text if ord(c) > 0x7F]
    if not non_ascii:
        return 1.0
    common = sum(
        1 for c in non_ascii
        if 0x4E00 <= ord(c) <= 0x9FFF or 0x3000 <= ord(c) <= 0x303F
    )
    return common / len(non_ascii)


def detect_codec(raw: bytes) -> SubtitleCodec:
    """偵測編碼並記住 BOM 狀態,讓寫回能位元組級保留原編碼。"""
    if raw.startswith(codecs.BOM_UTF8):
        return SubtitleCodec(codecs.BOM_UTF8, "utf-8")
    if raw.startswith(codecs.BOM_UTF16_LE):
        return SubtitleCodec(codecs.BOM_UTF16_LE, "utf-16-le")
    if raw.startswith(codecs.BOM_UTF16_BE):
        return SubtitleCodec(codecs.BOM_UTF16_BE, "utf-16-be")
    try:
        raw.decode("utf-8")
        return SubtitleCodec(b"", "utf-8")
    except UnicodeDecodeError:
        pass
    # Big5 與 GBK/GB18030 都是常見的中文 DBCS 編碼,位元組範圍重疊,
    # 錯誤的編碼仍可能「成功」解碼但產生亂碼,因此兩者都嘗試後以
    # CJK 常用字元比例消歧,而非只信任先解碼成功的那個。
    candidates: Dict[str, str] = {}
    for enc in ("big5", "gb18030"):
        try:
            candidates[enc] = raw.decode(enc)
        except UnicodeDecodeError:
            pass
    if len(candidates) == 1:
        enc = next(iter(candidates))
        return SubtitleCodec(b"", enc)
    if len(candidates) == 2:
        scored = {enc: _cjk_plausibility(text) for enc, text in candidates.items()}
        ranked = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)
        if ranked[0][1] - ranked[1][1] > 0.05:
            return SubtitleCodec(b"", ranked[0][0])
    # 兩者皆不可解或分數太接近難以判斷 → 交給 charset-normalizer 統計判斷
    best = from_bytes(raw, steps=10).best()
    if best is None:
        raise ScaleError("無法判斷檔案編碼")
    return SubtitleCodec(b"", best.encoding.lower())


def read_subtitle_text(path: Path) -> Tuple[str, SubtitleCodec]:
    raw = Path(path).read_bytes()
    codec = detect_codec(raw)
    return codec.decode(raw), codec


def read_as_ass_text(path: Path) -> Tuple[str, SubtitleCodec, bool]:
    """讀檔並回傳可餵給 scale_text 的 ASS 文字。

    .ass/.ssa 來源:原始文字 + 原編碼 + converted=False(保留位元組風格與編碼)。
    其他(如 .srt)來源:pysubs2 轉成 ASS 文字 + UTF-8-with-BOM + converted=True
    (換格式後不再保留原編碼,一律 UTF-8-sig,與 save_subs 一致)。
    """
    text, codec = read_subtitle_text(path)
    if Path(path).suffix.lower() in (".ass", ".ssa"):
        return text, codec, False
    import pysubs2  # 延遲載入:本模組刻意不在頂端依賴 pysubs2
    ass_text = pysubs2.SSAFile.from_string(text).to_string("ass")
    return ass_text, SubtitleCodec(codecs.BOM_UTF8, "utf-8"), True


def scale_file(path: Path, options: ScaleOptions,
               out_path: Optional[Path] = None) -> ScaleReport:
    """縮放單一檔案。out_path=None 表原地。

    .ass/.ssa:原地=先備份 .bak 再覆寫(保留原編碼);輸出資料夾=同副檔名。
    .srt:輸出一律新 .ass(原地=同資料夾新檔不備份、不動原 .srt;輸出資料夾=
    副檔名正規化為 .ass),編碼 UTF-8-with-BOM。
    """
    from .episode_match import ass_output_name
    text, codec, converted = read_as_ass_text(path)
    new_text, report = scale_text(text, options)
    data = codec.encode(new_text)
    if out_path is None:
        target = ass_output_name(Path(path))  # .srt -> .ass;.ass/.ssa 不變
        if not converted:
            backup = target.with_name(target.name + ".bak")
            if not backup.exists():
                shutil.copy2(path, backup)  # 備份失敗丟例外 → 不寫入
        # 非 ASS 家族:不備份、不動原檔,直接寫出新 .ass
        target.write_bytes(data)
    else:
        target = Path(out_path)
        if converted:
            target = target.with_suffix(".ass")  # 正規化輸出副檔名
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return report
