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
    # 排除用不到的東西。這個程式只 import PySide6 的 QtCore/QtGui/QtWidgets
    # (`grep -rho "from PySide6\.[A-Za-z]*" ass_style_tool/` 只有這三個),
    # 但 PyInstaller 的 PySide6 hook 預設會把整套 Qt 都收進來——實測產物
    # 244 MB 裡有 33 MB 是這個純 QtWidgets 程式永遠不會載入的東西。
    excludes=[
        "tkinter", "tkinterdnd2",      # v1 tkinter GUI 已移除
        # QML/Quick 整條線:本程式沒有任何 QtQuick/QQuick/QML/QtQml 的
        # import(已 grep 確認),Qt6Quick.dll 一個就 6.3 MB。
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
        "PySide6.QtQuickControls2", "PySide6.QtQml.QtQml",
        # 其餘沒用到的 Qt 模組
        "PySide6.QtNetwork", "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
        "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
        "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth",
        "PySide6.QtPositioning", "PySide6.QtSerialPort", "PySide6.QtPdf",
        "PySide6.QtPdfWidgets", "PySide6.QtDesigner", "PySide6.QtHelp",
        "PySide6.QtUiTools", "PySide6.QtSvgWidgets",
        # PIL / numpy / scipy 完全不是本程式的相依(requirements.txt 只有
        # pysubs2、charset-normalizer、PySide6;`grep -rn "from PIL\|import
        # numpy\|import scipy" ass_style_tool/ run_app.py` 零命中)。它們是
        # 被環境裡其他套件間接拉進分析的搭便車貨:實測 scipy 一個
        # libscipy_openblas 就 19.5 MB,PIL 的 AVIF 外掛 7.5 MB。
        "PIL", "numpy", "scipy", "matplotlib", "pandas",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# excludes 只擋得住 Python 模組層。PySide6 的 hook 是直接把整批 Qt DLL 複製
# 進 a.binaries 的,不經過 import 分析,所以 QML/Quick 那幾顆 DLL 即使
# excludes 已經排除對應的 Python 模組,還是會被收進產物——要在這裡按檔名
# 濾掉。
#
# 刻意不濾 opengl32sw.dll(19.7 MB,Mesa 軟體 OpenGL 後備):預覽分頁的
# mpv 是把畫面渲染到嵌入的子視窗上,在沒有硬體 OpenGL 的機器(遠端桌面、
# 虛擬機、老顯卡)上這顆是最後的退路。省 19.7 MB 換「某些機器上預覽整個
# 黑掉」不划算,而且這台開發機有正常顯卡,實測不出那個情境——沒有辦法
# 驗證的東西就不動它。
_DROP_BINARIES = {
    "qt6quick.dll", "qt6qml.dll", "qt6qmlmodels.dll", "qt6qmlmeta.dll",
    "qt6qmlworkerscript.dll", "qt6quickcontrols2.dll",
    "qt6quickcontrols2impl.dll", "qt6quicktemplates2.dll",
    "qt6quickwidgets.dll", "qt6quickdialogs2.dll",
    "qt6quickdialogs2quickimpl.dll", "qt6quickdialogs2utils.dll",
    "qt6quickeffects.dll", "qt6quicklayouts.dll", "qt6quickshapes.dll",
    "qt6quicktest.dll", "qt6labsanimation.dll", "qt6labsfolderlistmodel.dll",
    "qt6labsqmlmodels.dll", "qt6labssettings.dll", "qt6labssharedimage.dll",
    "qt6labswavefrontmesh.dll",
}
a.binaries = [b for b in a.binaries
              if os.path.basename(b[0]).lower() not in _DROP_BINARIES]

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
