#!/usr/bin/env python3
"""從 CHANGELOG.md 擷取指定版本的段落,供 release.yml 當 GitHub Release
notes 用。

慣例:每個版本一個二級標題,寫成 `## v<版本>`(跟 git tag 完全同一個
字串,例如 `## v1.1.0`),內容到下一個 `## ` 標題或檔尾為止。找不到
對應標題、或 CHANGELOG.md 不存在時印出空字串——呼叫端(release.yml)
收到空字串會退回讀 git tag 的 annotate 訊息,這裡不負責 fallback。
"""
from __future__ import annotations

import re
import sys


def extract_section(changelog_text: str, tag: str) -> str:
    pattern = re.compile(
        rf"^## {re.escape(tag)}\s*$(.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(changelog_text)
    if not match:
        return ""
    return match.group(1).strip()


def main() -> None:
    # release.yml 透過 PowerShell 用 `$notes = python ... ` 擷取這支
    # 腳本的輸出,stdout 因此不是真正的終端機,而是被導向/pipe——Python
    # 在這種情況下(尤其 Windows)預設用系統的 ANSI codepage 編碼輸出,
    # 不是 UTF-8,英文 locale 的 codepage(例如 cp1252)甚至編不進中文
    # 字,會讓這個 step 直接壞掉或印出亂碼(實測撞到,不是理論推測——
    # 見 tests/test_extract_changelog_section.py 的子行程測試)。固定
    # 用 UTF-8,不依賴呼叫環境的 locale。用 getattr 保護是因為測試會把
    # sys.stdout 換成 io.StringIO()(redirect_stdout),那種物件沒有
    # reconfigure()——只有真正的 TextIOWrapper(實際跑成子行程時)才有。
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")
    if len(sys.argv) != 3:
        print(f"用法: {sys.argv[0]} <CHANGELOG.md 路徑> <tag,例如 v1.1.0>",
              file=sys.stderr)
        raise SystemExit(2)
    changelog_path, tag = sys.argv[1], sys.argv[2]
    try:
        with open(changelog_path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return
    print(extract_section(text, tag))


if __name__ == "__main__":
    main()
