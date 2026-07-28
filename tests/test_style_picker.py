from __future__ import annotations

from ass_style_tool.qt.style_picker import StylePicker


def test_available_names_are_listed(qapp):
    picker = StylePicker()
    picker.set_available(["CHT", "Default"])
    assert picker.list.count() == 2


def test_selected_names_start_checked(qapp):
    picker = StylePicker()
    picker.set_available(["Default", "CHT"])
    picker.set_selected(["Default"])
    assert picker.selected() == ["Default"]


def test_checking_an_item_updates_selection(qapp):
    from PySide6.QtCore import Qt
    picker = StylePicker()
    picker.set_available(["Default", "CHT"])
    picker.set_selected([])
    picker.list.item(0).setCheckState(Qt.CheckState.Checked)
    assert picker.selected() == ["Default"]


def test_changed_signal_fires_on_check(qapp):
    from PySide6.QtCore import Qt
    picker = StylePicker()
    picker.set_available(["Default"])
    fired = []
    picker.changed.connect(lambda: fired.append(1))
    picker.list.item(0).setCheckState(Qt.CheckState.Checked)
    assert fired == [1]


# ---------- 核心不變式 ----------

def test_selected_name_missing_from_scan_is_kept_and_flagged(qapp):
    """掃描結果不得替使用者刪掉已選的樣式名。

    先前「修改既有軌道」對話框正是靜默丟掉使用者設定而釀成 Critical,
    這條是本功能最重要的不變式。
    """
    picker = StylePicker()
    picker.set_selected(["CHT"])
    picker.set_available(["Default"])          # 掃描結果裡沒有 CHT
    assert "CHT" in picker.selected()          # 仍然被選著
    assert picker.list.count() == 2            # 仍然列出來
    labels = [picker.list.item(i).text() for i in range(picker.list.count())]
    assert any("CHT" in text and "未在檔案中找到" in text for text in labels)


def test_rescanning_does_not_drop_user_selection(qapp):
    picker = StylePicker()
    picker.set_available(["Default", "CHT"])
    picker.set_selected(["Default", "CHT"])
    picker.set_available(["Default"])          # 換了一批檔案,只剩 Default
    assert picker.selected() == ["Default", "CHT"]


def test_toggling_unrelated_item_does_not_drop_not_found_selection(qapp):
    """勾選跟『未找到』樣式無關的項目時,不能把它從已選清單裡擠掉。

    這條釘住的是 _on_item_changed 的實作方式:它必須把「畫面上目前勾選的
    項目」當成新的 _selected,而不是拿 self._available 去篩選。若改成從
    self._available 重建 _selected,任何一次不相關的勾選動作都會把
    「已選但未在檔案中找到」的樣式靜默清掉——這正是本檔案開頭註解描述的
    那種災難在使用者操作路徑上的重現方式。
    """
    from PySide6.QtCore import Qt
    picker = StylePicker()
    picker.set_selected(["CHT"])
    picker.set_available(["Default"])          # CHT 已選,但這批掃描不到
    assert picker.list.count() == 2
    # item(0) 是 Default(掃到的),item(1) 是 CHT(未找到但已選)
    assert picker.list.item(0).data(Qt.ItemDataRole.UserRole) == "Default"
    assert picker.list.item(1).data(Qt.ItemDataRole.UserRole) == "CHT"

    picker.list.item(0).setCheckState(Qt.CheckState.Checked)  # 勾選 Default,與 CHT 無關

    assert "CHT" in picker.selected()
    assert set(picker.selected()) == {"Default", "CHT"}


def test_rebuild_orders_found_names_before_not_found_names(qapp):
    """_rebuild 的文件承諾:掃描到的名稱在前,已選但未掃到的名稱接在後面。"""
    from PySide6.QtCore import Qt
    picker = StylePicker()
    picker.set_selected(["CHT", "Missing"])
    picker.set_available(["Default"])
    names_in_order = [
        picker.list.item(i).data(Qt.ItemDataRole.UserRole)
        for i in range(picker.list.count())
    ]
    assert names_in_order == ["Default", "CHT", "Missing"]
