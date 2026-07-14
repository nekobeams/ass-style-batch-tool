# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec:ASS 字幕樣式批次工具。"""

import os
import sysconfig

# python-mpv 在 Windows 上把 libmpv-2.dll 裝在 site-packages 根目錄(pip install
# 該套件時附帶的 wheel data)。用 sysconfig 動態找,換機器/換 Python 版本仍能重建。
_LIBMPV_CANDIDATES = [
    os.path.join(sysconfig.get_paths()["purelib"], "libmpv-2.dll"),
    os.path.join(sysconfig.get_paths()["platlib"], "libmpv-2.dll"),
]
LIBMPV = next((p for p in _LIBMPV_CANDIDATES if os.path.isfile(p)), None)
if LIBMPV is None:
    raise SystemExit(
        "找不到 libmpv-2.dll,已檢查:\n  " + "\n  ".join(_LIBMPV_CANDIDATES) +
        "\n`python-mpv`(pip 套件)本身不附帶這個 DLL,需要另外取得對應 Windows"
        "版 libmpv 的 build(libmpv-2.dll),放進上述 site-packages 目錄"
        "(與 mpv.py 同層)後再重跑打包。"
    )

block_cipher = None

a = Analysis(
    ["run_app.py"],
    pathex=["."],                      # 讓 ass_style_tool 以絕對 import 被分析追進
    binaries=[(LIBMPV, ".")],          # libmpv-2.dll 收進產物,frozen mpv 由 __file__ 旁尋得
    datas=[],
    hiddenimports=["mpv"],             # python-mpv 於 player.py 延遲 import,顯式收進
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "tkinterdnd2"],  # v1 tkinter GUI 已移除,排除
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ass_style_tool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                     # GUI 程式,不開終端機視窗
    icon="assets/icon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ass_style_tool",
)
