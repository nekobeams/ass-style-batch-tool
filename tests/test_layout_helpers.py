from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from ass_style_tool.qt.layout_helpers import (GROUP_SPACING, MARGIN, SPACING,
                                              SIDEBAR_MIN_WIDTH, action_row,
                                              group, main_splitter,
                                              page_layout, settings_sidebar)


def test_group_sets_title_and_inner_spacing(qapp):
    box = group("輸出", QVBoxLayout())
    assert box.title() == "輸出"
    assert box.layout().spacing() == GROUP_SPACING
    assert box.layout().contentsMargins().left() == GROUP_SPACING


def test_settings_sidebar_has_minimum_width(qapp):
    """側欄要夠寬才塞得下 ScalePanel 與語言下拉,窄過頭等於沒做。"""
    assert settings_sidebar().minimumWidth() == SIDEBAR_MIN_WIDTH


def test_settings_sidebar_stacks_groups_then_leaves_slack(qapp):
    first = group("甲", QVBoxLayout())
    second = group("乙", QVBoxLayout())
    panel = settings_sidebar(first, second)
    layout = panel.layout()
    assert layout.itemAt(0).widget() is first
    assert layout.itemAt(1).widget() is second
    assert layout.itemAt(2).spacerItem() is not None   # 底部留白,群組不被拉開


def test_main_splitter_orders_list_then_sidebar(qapp):
    left, right = QWidget(), QWidget()
    splitter = main_splitter(left, right)
    assert splitter.widget(0) is left
    assert splitter.widget(1) is right
    assert splitter.childrenCollapsible() is False   # 側欄不可被拖到消失


def test_action_row_puts_primary_actions_on_the_right(qapp):
    scan, run, cancel = QPushButton(), QPushButton(), QPushButton()
    row = action_row([scan], [run, cancel])
    assert row.itemAt(0).widget() is scan
    assert row.itemAt(1).spacerItem() is not None
    assert row.itemAt(2).widget() is run
    assert row.itemAt(3).widget() is cancel


def test_page_layout_applies_shared_margins(qapp):
    layout = page_layout(QWidget())
    assert layout.contentsMargins().top() == MARGIN
    assert layout.spacing() == SPACING
