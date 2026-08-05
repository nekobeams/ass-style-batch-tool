"""樣式編輯面板:欄位、色彩選擇器、profile 存讀、字型未安裝警告。"""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)
from PySide6.QtWidgets import QColorDialog
from PySide6.QtGui import QColor, QFontDatabase

from ..profile import (Profile, ass_color_to_rgb, load_profile,
                       rgb_to_ass_color, save_profile)
from ..profile_fields import (DEFAULT_VALUES, parse_target_style_names,
                              profile_from_values, values_from_profile)
from .gui_helpers import font_is_missing
from .readout_view import ReadoutView

# 欄位分組(標籤, 欄位鍵)
_TEXT_FIELDS = [
    ("設定檔名稱", "profile_name"),
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

_logger = logging.getLogger(__name__)


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


# 演算法本體(色碼 <-> RGB 三元組)在 ..profile.ass_color_to_rgb /
# rgb_to_ass_color,不依賴 Qt,可以獨立測試。這裡只做 QColor 這一層薄
# 轉換,讓呼叫端(_pick_color 等)不用自己記得怎麼拆三元組。
def _ass_to_qcolor(ass: str) -> QColor:
    r, g, b = ass_color_to_rgb(ass)
    return QColor(r, g, b)


def _qcolor_to_ass(color: QColor, alpha_ass: str) -> str:
    return rgb_to_ass_color((color.red(), color.green(), color.blue()),
                            alpha_ass)


class StyleEditor(QWidget):
    values_changed = Signal()
    # I4(最終審查 Finding):載入 profile 後,把它的 target_style_names
    # 交給「目前作用中工作分頁」的 StylePicker 當新選取——不然「載入
    # profile」只改得動這個編輯器的欄位,對任何分頁的勾選毫無效果,
    # profile 裡存的目標樣式名字形同沒被讀到。由 MainWindow(唯一同時
    # 拿得到 StyleEditor 與三個分頁的地方)接線。
    profile_loaded = Signal(list)
    # Finding 3(最終審查 Batch A3):_profile_to_save() 在「目前作用中
    # 分頁沒有勾選任何樣式」時會落回 self._target_style_names 這份隱藏
    # 值——這個代換本身是對的(不然會把空清單存進 profile_from_values()
    # 一定拋錯的檔案),但原本完全無聲,使用者看不出存出來的檔案套用的
    # 目標樣式跟分頁畫面顯示的不一樣。跟其他分頁的 log 訊號同一套接法,
    # 由 MainWindow 接到 append_log()。
    log = Signal(str)

    def __init__(self,
                 get_target_style_names:
                     Optional[Callable[[], Optional[List[str]]]] = None
                 ) -> None:
        """get_target_style_names:另存 profile 時用來覆蓋
        target_style_names 的來源,由 MainWindow 注入,回傳「目前作用中
        工作分頁」的 StylePicker 選取清單。有兩種情況都會落回
        self._target_style_names 這份隱藏值,但成因不同(I4 / Finding 3,
        最終審查 Batch A3):
        1. 回傳 None:現在判斷不出是哪個分頁的勾選(例如程式剛啟動、
           還沒有任何分頁被切換過)——這種情況不記錄 log,因為連「目前
           分頁到底有沒有勾」都無從得知。
        2. 回傳 []:判斷得出是哪個分頁,但那個分頁的勾選確實是空的
           (使用者掃描完成後還沒勾、或全部取消勾選)——這種情況會發出
           log,講清楚實際存了什麼名字、為什麼(見 _profile_to_save()）。
        兩種情況都不能用空清單覆蓋掉隱藏值。
        """
        super().__init__()
        self._edits: Dict[str, QLineEdit] = {}
        self._checks: Dict[str, QCheckBox] = {}
        # 目標 Style 已移到各工作分頁的側欄(它回答的是「這批要改哪個」,
        # 與本編輯器描述的「改成什麼樣子」不同性質)。這裡仍保留其值,
        # 因為 profile_from_values() 要求這個鍵,且存檔要原樣寫回。
        self._target_style_names = str(DEFAULT_VALUES["target_style_names"])
        self._get_target_style_names = get_target_style_names

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
        self.font_warning.setStyleSheet("QLabel { color: #d08a00; }")
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
            # 搬移失敗不阻擋啟動;profile 清單以現有內容開始(控制流程不變)。
            # 但複製檔案在啟動這個時間點失敗不是常態(權限、磁碟問題居多),
            # 記下 traceback,不然使用者回報「以前存的樣式都不見了」時
            # 完全無從查起。
            _logger.exception("搬移舊版 profile 失敗")
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
        if "target_style_names" in values:
            self._target_style_names = str(values["target_style_names"])
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
        values["target_style_names"] = self._target_style_names
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
        profile = load_profile(Path(path))
        # Finding 1(最終審查 Batch A3):先前這裡只檢查
        # `not profile.target_style_names`(裸的 falsy-list 檢查)——但
        # 真正會拋錯的驗證邏輯(profile_from_values() 內部,現在抽成
        # parse_target_style_names())判斷的是「逗號切開、去空白、過濾
        # 空字串之後還剩不剩東西」,不是「這個 List 是不是空的」。
        # `[""]`、`[","]`、`["   "]` 這幾種值在裸的真值檢查底下都算
        # 「非空清單」,騙得過舊檢查,卻仍然通不過 parse_target_style_
        # names() 的實際驗證——這種檔案不只可能是手改壞的,StylePicker
        # 的名字直接取自 .ass 檔案的 [V4+ Styles] 區段鍵值(見
        # style_scan.summarize()),一個 style 名稱是空字串的 .ass
        # (`Style: ,...`)勾選存檔就會產生 `[""]`,完全是正常操作路徑
        # 能走到的資料,不是理論案例。用跟 profile_from_values() 完全
        # 同一個函式判斷有效性,兩處判斷式才不會再度各玩各的漂移開。
        if not parse_target_style_names(", ".join(profile.target_style_names)):
            # Finding 3(最終審查 Batch A4):這個代換原本完全無聲,跟上一輪
            # 修的存檔端 fallback log 是同一種缺陷,只是換了個 guard——
            # 沿用同一個 log 訊號,講清楚實際發生了什麼、改用了什麼。
            self.log.emit(
                f"載入的設定檔目標樣式無效,已改用預設值:"
                f"{DEFAULT_VALUES['target_style_names']}")
            profile = replace(
                profile,
                target_style_names=[str(DEFAULT_VALUES["target_style_names"])])
        self.set_values(values_from_profile(profile))
        # I4:把載入到的 target_style_names 交給目前作用中的工作分頁當新
        # 選取。這是使用者主動載入這個 profile 造成的取代,不是掃描結果
        # 篩掉了什麼——跟 StylePicker 自己「勾選不因掃描而被靜默丟掉」的
        # 不變式是兩件事,接手的一端(MainWindow)用 set_selected() 走的
        # 也是同一條「保留未掃到的名字、只多標記」的路徑,不會違反那個
        # 不變式。
        self.profile_loaded.emit(list(profile.target_style_names))

    def _on_load_selected(self) -> None:
        path = self.profile_combo.currentData()
        if not path:
            return
        try:
            self.load_profile_from(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "載入失敗", str(exc))

    def _profile_to_save(self) -> Profile:
        """存檔要寫入的 profile。

        I4:target_style_names 要用「目前作用中工作分頁」的 StylePicker
        勾選覆蓋,而不是 self._target_style_names 這份隱藏值——那份值只
        有存/讀 JSON 時會被摸到,從未跟任何分頁的勾選同步過,原本的
        「另存」會把它原封不動寫進檔案,結果是使用者在分頁裡實際勾選、
        實際拿去跑的樣式,和存出來的檔案內容對不上。effective_profile()
        執行時的邏輯是「分頁勾選蓋過 profile 裡的值」,存檔必須對稱,
        才不會讓 profile 檔案靜默失真(這正是本分支要防的那類問題)。

        落回隱藏值(fallback)有兩種觸發情況,行為一致但可見性不同
        (Finding 3,最終審查 Batch A3):`names` 是 None(判斷不出是哪個
        分頁的勾選)時安靜地落回,因為連「有沒有勾」都無從得知;`names`
        是 []([] 觸發 fallback 這件事本身正是 Finding 1 half 1 修的,
        本次批次修正描述補齊——目前作用中分頁確實存在、確實沒有勾選任何
        樣式)時一樣落回,但這裡發出 log,講清楚實際存了什麼、為什麼,
        不然使用者只會在批次真的跑起來、套用了一個畫面上根本沒勾的樣式
        之後才發現存出來的檔案跟分頁畫面對不上。
        """
        profile = self.current_profile()
        if self._get_target_style_names is not None:
            names = self._get_target_style_names()
            # Finding 2(最終審查 Batch A4):跟上一輪修的載入端防呆同一個
            # 判斷式(parse_target_style_names()),不能再用裸的 list
            # truthiness——`[""]` 是非空 list,騙得過 `if names:`,卻通不過
            # 這裡真正的有效性判斷,原樣存進去會產生一個
            # profile_from_values() 會拒絕、下次載入又被靜默改回 Default
            # 的檔案。
            if names is not None and parse_target_style_names(", ".join(names)):
                profile = replace(profile, target_style_names=list(names))
            elif names is not None:
                label = "、".join(profile.target_style_names)
                self.log.emit(
                    f"目前分頁未勾選任何樣式,已依上次載入的設定儲存"
                    f"目標樣式:{label}")
        return profile

    def _on_save_as(self) -> None:
        try:
            profile = self._profile_to_save()
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
                # 啟動流程不可被互動對話框擋住(手動載入按鈕失敗會彈
                # QMessageBox,這裡不行),控制流程不變。但這代表使用者
                # 上次存下的 profile 檔案這次讀不到了(損毀、被刪、格式
                # 壞掉),值得留下 traceback——不然「我的樣式設定怎麼
                # 不見了」這種回報完全查不出是檔案本身壞了還是別的問題。
                _logger.exception("啟動時還原上次使用的 profile 失敗:%s", path)
