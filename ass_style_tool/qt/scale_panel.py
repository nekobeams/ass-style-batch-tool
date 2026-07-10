"""縮放字級模式的參數面板。"""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QGridLayout, QLabel, QLineEdit,
                               QRadioButton, QWidget)

from ..scale_engine import ScaleError, ScaleOptions


class ScalePanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 4, 0, 4)

        self.factor_radio = QRadioButton("倍率 ×")
        self.factor_radio.setChecked(True)
        self.factor_edit = QLineEdit("1.25")
        self.factor_edit.setMaximumWidth(80)
        grid.addWidget(self.factor_radio, 0, 0)
        grid.addWidget(self.factor_edit, 0, 1)

        self.target_radio = QRadioButton("主 Style 設為")
        self.target_edit = QLineEdit("72")
        self.target_edit.setMaximumWidth(80)
        grid.addWidget(self.target_radio, 1, 0)
        grid.addWidget(self.target_edit, 1, 1)
        grid.addWidget(QLabel("基準 Style:"), 1, 2)
        self.base_edit = QLineEdit("Default")
        self.base_edit.setMaximumWidth(140)
        grid.addWidget(self.base_edit, 1, 3)

        self.deco_check = QCheckBox("同步縮放外框/陰影")
        self.deco_check.setChecked(True)
        self.inline_check = QCheckBox("縮放對白內 \\fs")
        self.inline_check.setChecked(True)
        self.fscxy_check = QCheckBox("同步縮放 \\fscx/\\fscy(會改變字幅比例)")
        grid.addWidget(self.deco_check, 2, 0, 1, 2)
        grid.addWidget(self.inline_check, 2, 2, 1, 2)
        grid.addWidget(self.fscxy_check, 3, 0, 1, 4)
        grid.setColumnStretch(4, 1)

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
