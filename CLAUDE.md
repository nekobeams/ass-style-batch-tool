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

## 發版流程

`.github/workflows/release.yml` 會在收到 `v*` 開頭的 tag 時自動跑完整套
build + 發布,人只要做前半段:

1. 改 `VERSION` 檔(單一版本來源,`pyproject.toml`/`ass_style_tool.iss` 都讀它)
2. `git add VERSION && git commit -m "build: 版本號更新為 X.Y.Z"`
3. `git tag -a vX.Y.Z -m "..."`(**annotated tag**,`-m` 給有意義的多行內容——
   `CHANGELOG.md` 沒有對應段落時,這段訊息會直接變成 Release notes)
4. `git push origin master && git push origin vX.Y.Z`

其餘全自動:跑一次完整測試(**沒過就不發布,這是硬性條件**)→ 驗證
tag 版本與 `VERSION` 檔一致(不一致就失敗,防止發錯版本)→ PyInstaller
build → Inno Setup 編譯 → 建立 GitHub Release 並上傳安裝檔。

**Release notes 來源優先序:** `CHANGELOG.md` 裡 `## vX.Y.Z` 對應段落
(找不到就用整段,包含到下一個 `## ` 標題或檔尾為止)→ 找不到就用 annotated
tag 的訊息 → 兩者都沒有就只寫 `Release vX.Y.Z`。目前專案沒有維護
`CHANGELOG.md`,所以現在是走 tag 訊息這條路——打 tag 時 `-m` 请寫清楚
這次改了什麼,不要只寫版本號。

**已知範圍限制:CI 產出的安裝程式只有 core 元件。** `installer_payload/`
底下的 ffmpeg/mkvtoolnix 是你手動放的第三方二進位(`.gitignore`,不進
repo),CI 沒有這兩個資料夾——`.iss` 的 `#if DirExists(...)` 設計會在
資料夾不存在時直接跳過對應元件(不會編譯失敗),所以自動化 release 裝
出來的版本會缺少「自動偵測並提供安裝 ffprobe/MKVToolNix」這個選項,跟
手動打包的版本不完全一樣。這是刻意接受的簡化(見
docs/superpowers 之外的分析:方案評估時討論過一併自動化這兩個工具的
選項,決定先不做)。如果哪次 release 需要跟手動打包一樣完整,還是要走
本節最下面的手動步驟。

**libmpv-2.dll 的取得方式:** 不在 repo 裡(pip 的 `python-mpv` 套件本身
不附帶這顆 DLL),CI 從專案自己代管的 vendor release
(`vendor-libmpv-v0.41.0-724-g71ebd0840`,見該 release 本身的說明)下載
固定版本,不即時抓上游「最新版」——上游(SourceForge/shinchiro 建置站
台)沒有穩定的程式化下載端點。要升版 libmpv 時,建一個新的
`vendor-libmpv-v<版本>` release,同步改 `release.yml` 裡的下載網址。

**手動打包(不透過 CI,例如要包含 ffmpeg/MKVToolNix 完整版本時):**

```powershell
py -m pytest tests -q
py -m PyInstaller ass_style_tool.spec --noconfirm --clean
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" "ass_style_tool.iss"
```

編出來的安裝程式在 `installer_dist\ass-style-tool-setup.exe`,自己
`gh release create` 上傳。
