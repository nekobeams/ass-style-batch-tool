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
