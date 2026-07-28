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
