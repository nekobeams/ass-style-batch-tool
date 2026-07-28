"""分頁版面的共用建構器與間距常數(方案 C:右側設定側欄)。

三個工作分頁(字幕檔 / MKV / 封裝)採用同一個骨架:

    來源列(橫跨全寬)
    QSplitter(水平) → 左:清單或表格   右:設定側欄
    動作列(次要靠左 → 留白 → 主要靠右)
    進度列

把常數與建構器集中在這裡,而不是三個分頁各寫一份——三份平行的版面碼
很容易在日後只改一邊而慢慢分岔。
"""
from __future__ import annotations

from typing import Sequence, Tuple

from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtWidgets import (QDialog, QGroupBox, QHBoxLayout, QLayout,
                               QSplitter, QVBoxLayout, QWidget)

MARGIN = 12              # 分頁最外層外距
SPACING = 10             # 主要區塊之間
GROUP_SPACING = 8        # 群組盒內部
SIDEBAR_MIN_WIDTH = 240  # 設定側欄:塞得下 ScalePanel 與語言下拉的下限


def page_layout(widget: QWidget) -> QVBoxLayout:
    """分頁最外層的垂直版面,統一外距與間距。"""
    layout = QVBoxLayout()
    layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
    layout.setSpacing(SPACING)
    widget.setLayout(layout)
    # 保持 widget 的引用,防止它被垃圾回收時連帶刪除 layout
    layout._widget = widget
    return layout


def group(title: str, inner: QLayout) -> QGroupBox:
    """把一段版面包成有標題的群組盒(統一內距與間距)。"""
    inner.setContentsMargins(GROUP_SPACING, GROUP_SPACING,
                             GROUP_SPACING, GROUP_SPACING)
    inner.setSpacing(GROUP_SPACING)
    box = QGroupBox(title)
    box.setLayout(inner)
    return box


def settings_sidebar(*groups: QWidget) -> QWidget:
    """右側設定側欄:群組盒由上而下排,底部留白讓它們保持自然高度。"""
    panel = QWidget()
    column = QVBoxLayout(panel)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(SPACING)
    for box in groups:
        column.addWidget(box)
    column.addStretch(1)
    panel.setMinimumWidth(SIDEBAR_MIN_WIDTH)
    return panel


def main_splitter(main_area: QWidget, sidebar: QWidget) -> QSplitter:
    """左清單 / 右側欄。左邊拿三倍伸縮權重,側欄不隨視窗放大而變胖。"""
    splitter = QSplitter(Qt.Horizontal)
    splitter.addWidget(main_area)
    splitter.addWidget(sidebar)
    splitter.setStretchFactor(0, 3)
    splitter.setStretchFactor(1, 1)
    splitter.setChildrenCollapsible(False)
    return splitter


def action_row(secondary: Sequence[QWidget],
               primary: Sequence[QWidget]) -> QHBoxLayout:
    """動作列:次要動作靠左,主要動作與取消靠右。"""
    row = QHBoxLayout()
    for button in secondary:
        row.addWidget(button)
    row.addStretch(1)
    for button in primary:
        row.addWidget(button)
    return row


def install_dialog_geometry(dialog: QDialog, key: str,
                            default_size: Tuple[int, int]) -> None:
    """給對話框一個合理的初始尺寸,並記住使用者調整後的大小。

    QDialog 不指定尺寸時,Qt 只會依 layout 的最小 sizeHint 收到最小,
    表格類對話框因此開起來窄到看不見內容,每次都要使用者自己拉大。
    這裡先套用預設尺寸,若有存過幾何資料就改用存的,並在關閉時存回。

    型別檢查不能省:PySide6 在 QSettings 值型別不符時不會回傳預設值,
    而是把原始值原樣丟回來,直接餵給 restoreGeometry() 會炸(與
    splitter restoreState() 同一個坑)。
    """
    settings = QSettings("ass-style-tool", "ass-style-tool")
    saved = settings.value(f"dialog/{key}")
    restored = False
    if isinstance(saved, QByteArray):
        restored = dialog.restoreGeometry(saved)
    if not restored:
        dialog.resize(*default_size)

    def _save(_result: int = 0) -> None:
        settings.setValue(f"dialog/{key}", dialog.saveGeometry())

    dialog.finished.connect(_save)
