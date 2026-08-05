libmpv (libmpv-2.dll) — 授權與來源說明
======================================

本程式的「樣式與預覽」分頁使用 libmpv 播放影片,安裝時會一併安裝
libmpv-2.dll。

授權
----
libmpv 依 GNU 通用公眾授權條款第 2 版或更新版本(GPL v2 or later)散布。
授權全文見同目錄下的 COPYING.txt。

這項資訊取自 libmpv-2.dll 自身的版本資源(不是推測):

    FileVersion    : v0.41.0-724-g71ebd0840
    CompanyName    : mpv
    ProductName    : mpv
    LegalCopyright : Copyright (c) 2000-2026 mpv/MPlayer/mplayer2 projects
    Comments       : mpv is distributed under the terms of the
                     GNU General Public License Version 2 or later.

原始碼取得方式
--------------
mpv 專案原始碼:
    https://github.com/mpv-player/mpv

本程式散布的這份 Windows 二進位由 shinchiro 建置,其建置腳本(含用來
產生這份 DLL 的完整設定)位於:
    https://github.com/shinchiro/mpv-winbuild-cmake

發行檔亦鏡像於:
    https://sourceforge.net/projects/mpv-player-windows

上述版本字串(v0.41.0-724-g71ebd0840)中的 g71ebd0840 即對應 mpv 原始碼
的 git commit,可據此取得與本 DLL 完全對應的原始碼。

其他隨附的第三方元件
--------------------
ffmpeg 與 MKVToolNix 為可選安裝元件,其授權文字分別位於
{app}\licenses\ffmpeg\ 與 {app}\licenses\mkvtoolnix\。
