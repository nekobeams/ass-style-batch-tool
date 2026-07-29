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


# ---------- I11:掃描成功但還沒勾任何樣式時,提示不能是空白 ----------

def test_hint_prompts_selection_when_available_but_nothing_selected(qapp):
    """I11(最終審查 Finding):_available 非空(掃描到樣式)、_selected 空
    (使用者還沒勾)是首次掃描完成後的正常狀態(不再有自由文字輸入的
    預設值)——執行鈕這時是關閉的,提示卻是空白,完全看不出為什麼按不
    下去。"""
    picker = StylePicker()
    picker.set_available(["Default", "CHT"])
    assert picker.selected() == []
    assert picker.hint.text() == "請勾選要套用的目標樣式"


def test_hint_is_blank_once_something_is_selected(qapp):
    picker = StylePicker()
    picker.set_available(["Default"])
    picker.set_selected(["Default"])
    assert picker.hint.text() == ""


def test_hint_is_scan_prompt_before_any_scan(qapp):
    picker = StylePicker()
    assert picker.hint.text() == "尚未掃描到樣式"


def test_missing_selection_hint_takes_priority_over_nothing_selected_hint(qapp):
    """已選但找不到的樣式名存在時,警告訊息優先於『請勾選』提示——
    _selected 非空,不該顯示成『還沒勾任何東西』。"""
    picker = StylePicker()
    picker.set_available(["Default"])
    picker.set_selected(["CHT"])          # CHT 不在掃描結果裡
    assert "請勾選要套用的目標樣式" not in picker.hint.text()
    assert "不在這批檔案中" in picker.hint.text()


# ---------- C2:not_found_hint 可由呼叫端客製化(mux_tab 的「找不到」不是「略過」) ----------

def test_not_found_hint_customizable():
    picker = StylePicker(not_found_hint="這些檔案會原樣封裝,不套用樣式")
    picker.set_available(["Default"])
    picker.set_selected(["CHT"])
    assert "略過" not in picker.hint.text()
    assert "這些檔案會原樣封裝,不套用樣式" in picker.hint.text()


def test_not_found_hint_defaults_to_skip_wording():
    """預設措辭維持原文字不變——字幕檔/MKV 分頁沒有換過這個參數,
    既有行為不能被本次修改動到。"""
    picker = StylePicker()
    picker.set_available(["Default"])
    picker.set_selected(["CHT"])
    assert "這些檔案會被略過" in picker.hint.text()


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
