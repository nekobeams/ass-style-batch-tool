# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec:ASS 字幕樣式批次工具。"""

# 開發機上 python-mpv 載入的 libmpv-2.dll 絕對路徑(見 plan Task 3 Step 4 調查)
LIBMPV = (
    r"C:\Users\CAT\AppData\Local\Programs\Python\Python313"
    r"\Lib\site-packages\libmpv-2.dll"
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
