"""側欄的目標樣式勾選清單。

掃描結果是資訊來源,不是刪除依據:設定或 profile 帶來、但這批檔案裡
不存在的樣式名,仍然列出、仍然保持勾選,只多標一個「未在檔案中找到」。
先前「修改既有軌道」對話框就是靜默丟掉使用者設定,結果用假的保證
重現了它本來要防的災難——那個教訓在這裡直接適用。
"""
from __future__ import annotations

from typing import List, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QLabel, QListWidget, QListWidgetItem,
                               QVBoxLayout, QWidget)

_NOT_FOUND = "(未在檔案中找到)"


class StylePicker(QWidget):
    changed = Signal()

    def __init__(self, parent=None, *,
                 not_found_hint: str = "這些檔案會被略過") -> None:
        """not_found_hint:已選但這批檔案裡找不到的樣式名,提示文字要接在
        後面說明「這是什麼後果」。預設「這些檔案會被略過」符合字幕檔
        分頁(batch_runner.process_file 找不到目標 Style 就跳過整檔)與
        MKV 分頁(process_mkv 所有勾選軌皆未修改就整檔跳過重封裝)的實際
        行為;封裝分頁(mux_tab.py)的「找不到」其實是原樣封裝、不套用
        樣式而非整個跳過(mkv_mux.process_mux),建構時要傳入能反映這點
        的文字,不能沿用預設措辭(最終審查 Finding C2)。
        """
        super().__init__(parent)
        self._available: List[str] = []
        self._selected: List[str] = []
        self._not_found_hint = not_found_hint

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setMaximumHeight(140)
        self.list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.list)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self._rebuild()

    # ---------- 對外 ----------
    def set_available(self, names: Sequence[str]) -> None:
        self._available = list(names)
        self._rebuild()

    def set_selected(self, names: Sequence[str]) -> None:
        self._selected = list(names)
        self._rebuild()
        # 呼叫端(還原設定、Task 6 的分頁整合)靠這個訊號驅動「預計」欄與
        # 執行按鈕的重算,不能只有使用者親手點勾選框才通知——否則程式化
        # 設定選取後,畫面會停在舊狀態直到使用者手動戳一下才更新。
        self.changed.emit()

    def selected(self) -> List[str]:
        return list(self._selected)

    # ---------- 內部 ----------
    def _rebuild(self) -> None:
        # 聯集,順序:掃描到的在前,使用者選了但沒掃到的接在後面
        names = list(self._available)
        for name in self._selected:
            if name not in names:
                names.append(name)

        # 阻擋 itemChanged:填清單時若不擋,勾選狀態的變動會被當成使用者
        # 操作處理,連帶把 _selected 在重建過程中弄壞。用 try/finally 確保
        # 就算填清單途中拋例外,訊號也一定會恢復,不會永久卡住。
        self.list.blockSignals(True)
        try:
            self.list.clear()
            for name in names:
                found = name in self._available
                item = QListWidgetItem(name if found else f"{name} {_NOT_FOUND}")
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if name in self._selected
                                   else Qt.CheckState.Unchecked)
                self.list.addItem(item)
        finally:
            self.list.blockSignals(False)
        self._update_hint()

    def _on_item_changed(self, _item: QListWidgetItem) -> None:
        self._selected = [
            self.list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list.count())
            if self.list.item(i).checkState() == Qt.CheckState.Checked
        ]
        self._update_hint()
        self.changed.emit()

    def _update_hint(self) -> None:
        if not self._available:
            self.hint.setText("尚未掃描到樣式")
            return
        missing = [n for n in self._selected if n not in self._available]
        if missing:
            self.hint.setText(
                f"⚠ {'、'.join(missing)} 不在這批檔案中,{self._not_found_hint}")
            return
        if not self._selected:
            # I11(最終審查 Finding):掃描成功、樣式清單非空,但使用者還
            # 沒勾任何一個——這是首次掃描完成後的正常狀態(不再有自由
            # 文字輸入的預設值)。執行鈕這時是關閉的(見各分頁的
            # _update_run_enabled/_refresh_run_button),提示卻是空白,
            # 使用者完全看不出為什麼按不下去。
            self.hint.setText("請勾選要套用的目標樣式")
            return
        self.hint.setText("")
