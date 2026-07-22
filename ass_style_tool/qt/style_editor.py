"""樣式編輯面板:欄位、色彩選擇器、profile 存讀、字型未安裝警告。"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)
from PySide6.QtWidgets import QColorDialog
from PySide6.QtGui import QColor, QFontDatabase

from ..profile import (Profile, load_profile, parse_ass_color, save_profile)
from ..profile_fields import (DEFAULT_VALUES, profile_from_values,
                              values_from_profile)
from .gui_helpers import font_is_missing
from .readout_view import ReadoutView

# 欄位分組(標籤, 欄位鍵)
_TEXT_FIELDS = [
    ("設定檔名稱", "profile_name"),
    ("目標 Style(逗號分隔)", "target_style_names"),
    ("字型名稱", "fontname"),
    ("字體大小", "fontsize"),
    ("外框寬度", "outline"),
    ("陰影深度", "shadow"),
    ("對齊(1-9)", "alignment"),
    ("邊距 L", "margin_l"),
    ("邊距 R", "margin_r"),
    ("邊距 V", "margin_v"),
    ("基準寬", "base_width"),
    ("基準高", "base_height"),
]
_COLOR_FIELDS = [
    ("主色", "primary_colour"),
    ("外框色", "outline_colour"),
    ("陰影色", "back_colour"),
]


def migrate_legacy_profiles(legacy_dir: Path, target_dir: Path) -> int:
    """首次啟動時把舊位置的 profile 搬到新位置(複製,不刪原檔)。
    target 已有 *.json → 不搬(回 0);legacy 不存在或無 *.json → 不搬(回 0)。
    回傳複製的檔案數。"""
    if target_dir.is_dir() and any(target_dir.glob("*.json")):
        return 0
    if not legacy_dir.is_dir():
        return 0
    legacy_files = list(legacy_dir.glob("*.json"))
    if not legacy_files:
        return 0
    target_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for f in legacy_files:
        shutil.copy2(f, target_dir / f.name)
        count += 1
    return count


def _ass_to_qcolor(ass: str) -> QColor:
    c = parse_ass_color(ass)
    return QColor(c.r, c.g, c.b)


def _qcolor_to_ass(color: QColor, alpha_ass: str) -> str:
    try:
        a = parse_ass_color(alpha_ass).a
    except ValueError:
        a = 0
    return f"&H{a:02X}{color.blue():02X}{color.green():02X}{color.red():02X}"


class StyleEditor(QWidget):
    values_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._edits: Dict[str, QLineEdit] = {}
        self._checks: Dict[str, QCheckBox] = {}

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)

        # profile 下拉 + 存讀
        profile_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setEditable(False)
        profile_row.addWidget(QLabel("設定檔:"))
        profile_row.addWidget(self.profile_combo, 1)
        load_btn = QPushButton("載入")
        load_btn.clicked.connect(self._on_load_selected)
        save_btn = QPushButton("另存")
        save_btn.clicked.connect(self._on_save_as)
        profile_row.addWidget(load_btn)
        profile_row.addWidget(save_btn)
        inner_layout.addLayout(profile_row)

        form = QFormLayout()
        for label, key in _TEXT_FIELDS:
            edit = QLineEdit()
            self._edits[key] = edit
            form.addRow(label, edit)
            if key == "fontname":
                edit.textChanged.connect(self.refresh_font_warning)

        # 字型未安裝警告(接在字型欄位之後顯示)
        self.font_warning = QLabel("⚠ 系統未安裝此字型,播放器會改用預設字型")
        self.font_warning.setStyleSheet("color: #d08a00;")
        self.font_warning.setVisible(False)
        form.addRow("", self.font_warning)

        # 粗體/斜體
        self._checks["bold"] = QCheckBox("粗體")
        self._checks["italic"] = QCheckBox("斜體")
        flags = QHBoxLayout()
        flags.addWidget(self._checks["bold"])
        flags.addWidget(self._checks["italic"])
        flags.addStretch(1)
        form.addRow("樣式", self._wrap(flags))

        # 色彩欄位:文字 + 選色按鈕
        for label, key in _COLOR_FIELDS:
            edit = QLineEdit()
            self._edits[key] = edit
            btn = QPushButton("選色…")
            btn.clicked.connect(lambda _=False, k=key: self._pick_color(k))
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            row.addWidget(btn)
            form.addRow(label, self._wrap(row))

        inner_layout.addLayout(form)

        self.readout_view = ReadoutView()
        inner_layout.addWidget(self.readout_view)
        inner_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)

        root = QVBoxLayout(self)
        root.addWidget(scroll)

        self.set_values(DEFAULT_VALUES)
        try:
            migrate_legacy_profiles(Path.cwd() / "profiles", self.profiles_dir())
        except Exception:
            pass  # 搬移失敗不阻擋啟動;profile 清單以現有內容開始
        self._refresh_profile_list()

        for edit in self._edits.values():
            edit.textChanged.connect(self.values_changed)
        for check in self._checks.values():
            check.toggled.connect(self.values_changed)

    # ---------- 小工具 ----------
    def _wrap(self, layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def profiles_dir(self) -> Path:
        return Path(os.environ["APPDATA"]) / "ass-style-tool" / "profiles"

    # ---------- 取/設值 ----------
    def set_values(self, values: dict) -> None:
        for key, edit in self._edits.items():
            if key in values:
                edit.setText(str(values[key]))
        for key, check in self._checks.items():
            if key in values:
                check.setChecked(bool(values[key]))
        self.refresh_font_warning()

    def get_values(self) -> dict:
        values: dict = {}
        for key, edit in self._edits.items():
            values[key] = edit.text()
        for key, check in self._checks.items():
            values[key] = check.isChecked()
        return values

    def current_profile(self) -> Profile:
        return profile_from_values(self.get_values())

    # ---------- 色彩 ----------
    def _pick_color(self, key: str) -> None:
        edit = self._edits[key]
        try:
            initial = _ass_to_qcolor(edit.text())
        except ValueError:
            initial = QColor(255, 255, 255)
        chosen = QColorDialog.getColor(initial, self, "選擇顏色")
        if chosen.isValid():
            edit.setText(_qcolor_to_ass(chosen, edit.text()))

    # ---------- 字型警告 ----------
    def refresh_font_warning(self) -> None:
        families = QFontDatabase.families()
        missing = font_is_missing(self._edits["fontname"].text(), list(families))
        self.font_warning.setVisible(missing)

    def font_warning_visible(self) -> bool:
        # 用 isHidden 反映「意圖顯示」狀態:isVisible() 在 widget 尚未 show 時
        # (含 offscreen 測試)即使 setVisible(True) 也回傳 False。
        return not self.font_warning.isHidden()

    # ---------- profile 存讀 ----------
    def _refresh_profile_list(self) -> None:
        self.profile_combo.clear()
        d = self.profiles_dir()
        if d.is_dir():
            for p in sorted(d.glob("*.json")):
                self.profile_combo.addItem(p.name, str(p))

    def load_profile_from(self, path) -> None:
        self.set_values(values_from_profile(load_profile(Path(path))))

    def _on_load_selected(self) -> None:
        path = self.profile_combo.currentData()
        if not path:
            return
        try:
            self.load_profile_from(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "載入失敗", str(exc))

    def _on_save_as(self) -> None:
        try:
            profile = self.current_profile()
        except ValueError as exc:
            QMessageBox.critical(self, "欄位錯誤", str(exc))
            return
        self.profiles_dir().mkdir(parents=True, exist_ok=True)
        default = str(self.profiles_dir() / f"{profile.profile_name}.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "另存設定檔", default, "JSON (*.json)")
        if not path:
            return
        try:
            save_profile(profile, Path(path))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "儲存失敗", str(exc))
            return
        self._refresh_profile_list()

    # ---------- 設定持久化 ----------
    def save_settings(self, settings: QSettings) -> None:
        path = self.profile_combo.currentData()
        if path:
            settings.setValue("style/profile", path)

    def restore_settings(self, settings: QSettings) -> None:
        path = settings.value("style/profile", "")
        if not path:
            return
        idx = self.profile_combo.findData(path)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
            try:
                self.load_profile_from(path)
            except Exception:
                pass
