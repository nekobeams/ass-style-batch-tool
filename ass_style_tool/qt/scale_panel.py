"""縮放字級模式的參數面板(單欄版面,塞得進 240px 的設定側欄)。"""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit,
                               QRadioButton, QVBoxLayout, QWidget)

from ..scale_engine import ScaleError, ScaleOptions


class ScalePanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 4)
        root.setSpacing(6)

        factor_row = QHBoxLayout()
        self.factor_radio = QRadioButton("倍率 ×")
        self.factor_radio.setChecked(True)
        self.factor_edit = QLineEdit("1.25")
        self.factor_edit.setMaximumWidth(80)
        factor_row.addWidget(self.factor_radio)
        factor_row.addWidget(self.factor_edit)
        factor_row.addStretch(1)
        root.addLayout(factor_row)

        target_row = QHBoxLayout()
        self.target_radio = QRadioButton("主 Style 設為")
        self.target_edit = QLineEdit("72")
        self.target_edit.setMaximumWidth(80)
        target_row.addWidget(self.target_radio)
        target_row.addWidget(self.target_edit)
        target_row.addStretch(1)
        root.addLayout(target_row)

        base_row = QHBoxLayout()
        base_row.addWidget(QLabel("基準"))
        self.base_edit = QLineEdit("Default")
        self.base_edit.setMaximumWidth(140)
        base_row.addWidget(self.base_edit, 0)
        base_row.addStretch(1)
        root.addLayout(base_row)

        self.deco_check = QCheckBox("外框/陰影")
        self.deco_check.setToolTip("同步縮放外框和陰影效果")
        self.deco_check.setChecked(True)
        self.inline_check = QCheckBox("對白 \\fs")
        self.inline_check.setToolTip("縮放對白內的字級標籤")
        self.inline_check.setChecked(True)
        # 標題縮短、細節移到 tooltip:側欄只有 240px,長標籤會把分頁撐寬
        self.fscxy_check = QCheckBox("字幅比")
        self.fscxy_check.setToolTip("同步縮放 \\fscx/\\fscy(會改變字幅比例)")
        for check in (self.deco_check, self.inline_check, self.fscxy_check):
            root.addWidget(check)

    def get_options(self) -> ScaleOptions:
        try:
            if self.factor_radio.isChecked():
                options = ScaleOptions(factor=float(self.factor_edit.text()))
            else:
                options = ScaleOptions(
                    target_size=float(self.target_edit.text()),
                    base_style=self.base_edit.text().strip() or "Default")
        except ValueError as exc:
            if isinstance(exc, ScaleError):
                raise
            raise ScaleError(f"數值格式錯誤: {exc}")
        options.scale_decorations = self.deco_check.isChecked()
        options.scale_inline_fs = self.inline_check.isChecked()
        options.scale_fscxy = self.fscxy_check.isChecked()
        options.validate()
        return options
