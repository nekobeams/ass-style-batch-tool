# 專案慣例

## 環境
- Windows 開發環境,Python 指令用 `py`,不要用 `python`
  (多數 Windows 環境的 `python` 是 Microsoft Store 存根,exit code 49)
- 測試:`py -m pytest tests -q`
- 預設分支是 `master`,不是 `main`

## Git 慣例
- 每個任務從 master 開 feature branch,不要直接在 master 上 commit
- Commit message 用 Conventional Commits:feat / fix / docs / test / refactor / ci / build / chore
- 一個 commit 只做一件事,能用一句話說完
- 不要自行 merge 到 master,完成後交給使用者審查

## 文件慣例
- 文件中不得出現本機絕對路徑(`C:\Users\<name>\...`)
  一律使用環境變數或相對描述
- 設計文件放 docs/superpowers/specs/,實作計畫放 docs/superpowers/plans/

## 程式碼慣例
- 核心邏輯(ass_style.py、episode_match.py、resolution.py 等)保持與 Qt 解耦,
  必須能在無 GUI 環境單獨測試
- 新增功能請一併補測試
- 不要為了讓測試通過而弱化斷言
