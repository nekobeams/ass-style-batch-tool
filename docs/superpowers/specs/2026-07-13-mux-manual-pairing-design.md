# 封裝分頁——手動配對 Design

**背景**:「封裝」分頁(`ass_style_tool/qt/mux_tab.py`)目前只支援依集數編號的自動配對(`mkv_mux.pair_for_mux`)。當某集找不到字幕(`no_subtitle`)、同集有多個候選字幕(`ambiguous`)、或影片檔名判斷不出集數(`no_episode`)時,該列**無法封裝**——`checked_pairs()` 硬性只回傳 `status == "matched"` 的列,勾選框即使被勾起也會被忽略。使用者手動整理過檔名或想覆蓋自動配對結果時,目前完全沒有退路。

本設計新增手動配對能力,讓每一列都能透過下拉選單指定/更換字幕檔。

## 需求(使用者確認)

1. **互動方式**:下拉選單(非「點欄位跳瀏覽視窗」)。選單列出字幕資料夾內掃到的所有 `.ass` 檔名。
2. **適用範圍**:所有列都有下拉選單,包括已自動配對成功(`matched`)的列——使用者可以直接改選別的字幕檔,不限於修正失敗的配對。
3. **手動指定後的狀態**:視同 `matched`——該列狀態欄變成「已手動指定」,勾選框自動勾起,可直接封裝,不需使用者再手動勾選。

## UI 變更

配對表格第 3 欄(「字幕」)從唯讀文字改為 `QComboBox`:

- 選項來源:`_available_subtitles`(掃描字幕資料夾得到的 `.ass` 檔案清單,見下)+ 該列目前的 `pair.subtitle_path`(若不在前者清單中也強制併入,見「相容性」)
- 選項第一項固定是「(無)」,對應清除指定(`subtitle_path=None`)
- 顯示文字為檔名(`Path.name`),`itemData` 存完整 `Path`
- 選單依檔名字母序排列(「(無)」固定第一)
- 初始選取:`matched`/手動指定過的列選中對應檔案;其餘列選中「(無)」

不新增欄位、不改變欄位順序、不改變「集數」欄語意(維持顯示影片檔名判斷出的集數,與手動指定的字幕無關,即使兩者其實對不上使用者也看得到,不做隱藏處理)。

## 資料流 / 內部狀態

`MuxTab` 新增：

```python
self._available_subtitles: List[Path] = []
```

在 `_on_scan_done()` 中,除了既有的 `self.populate(pairs)` 外,額外掃一次字幕資料夾:

```python
from ..episode_match import find_files
...
def _on_scan_done(self, pairs: list) -> None:
    ...
    subs, _ = find_files(Path(self.subtitle_edit.text().strip()))
    self._available_subtitles = sorted(subs)
    self.populate(pairs)
    ...
```

（`find_files` 是既有函式,`MuxScanWorker.run()` 內部已經呼叫過一次;這裡在 GUI thread 上對同一個資料夾再呼叫一次是可接受的重複 I/O——純列目錄,無需額外執行緒,程式碼比改動 `MuxScanWorker.finished` 訊號簽章更簡單且不影響已審查通過的 worker 介面。）

`populate()` 建表格時,第 2 欄改成建立並設定 `QComboBox`(用 `setCellWidget`,不再用 `setItem`）：

```python
combo = QComboBox()
options = list(self._available_subtitles)
if pair.subtitle_path is not None and pair.subtitle_path not in options:
    options.append(pair.subtitle_path)
combo.addItem("(無)", None)
for sub in options:
    combo.addItem(sub.name, sub)
if pair.subtitle_path is not None:
    idx = combo.findData(pair.subtitle_path)
    if idx >= 0:
        combo.setCurrentIndex(idx)
combo.activated.connect(lambda _idx, row=r: self._on_subtitle_selected(row))
self.table.setCellWidget(r, 2, combo)
```

新增可測試 API：

```python
def set_row_subtitle(self, row: int, subtitle_path: Optional[Path]) -> None:
    """手動指定(或清除)某列的字幕檔;更新 pair/狀態欄/勾選框。"""
    pair = self._pairs[row]
    if subtitle_path is not None:
        new_pair = dataclasses.replace(
            pair, subtitle_path=subtitle_path, status="matched")
    else:
        new_pair = dataclasses.replace(
            pair, subtitle_path=None, status="no_subtitle")
    self._pairs[row] = new_pair
    self.table.item(row, 4).setText(
        _STATUS_LABELS.get(new_pair.status, new_pair.status))
    check = self.table.item(row, 0)
    check.setCheckState(
        Qt.CheckState.Checked if new_pair.status == "matched"
        else Qt.CheckState.Unchecked)
    self.run_button.setEnabled(
        self.tools_available
        and any(p.status == "matched" for p in self._pairs)
        and self._thread is None)

def _on_subtitle_selected(self, row: int) -> None:
    combo = self.table.cellWidget(row, 2)
    self.set_row_subtitle(row, combo.currentData())
```

`combo.activated`(非 `currentIndexChanged`)只在使用者實際操作選單時觸發,`populate()` 內用 `setCurrentIndex()` 設初始值不會誤觸發 `_on_subtitle_selected`,不需要額外的 `blockSignals` 處理。

## 相容性

- 既有測試直接呼叫 `tab.populate(PAIRS)`(不經過 `_on_scan_done`/掃描),此時 `self._available_subtitles` 是空清單。因為下拉選項清單一定會併入該列目前的 `pair.subtitle_path`,原本 `matched` 列的字幕關聯不會遺失,`test_populate_checks_matched_only`/`test_checked_pairs_respects_unchecking`/`test_run_button_enabled_after_populate` 等既有測試行為不變。
- 第 2 欄從 `QTableWidgetItem` 改成 `setCellWidget`,`table.item(r, 2)` 之後會回傳 `None`——確認過現有測試沒有讀取這一欄的 `item()`,只有第 0 欄(勾選框)被讀取,故不受影響。
- `mkv_mux.py`、`batch_worker.py`(`MuxScanWorker`/`MuxWorker`)、`process_mux`、`build_mux_command` 完全不變——手動配對純粹是 UI 層對 `self._pairs` 清單的覆蓋,不影響下游 mux pipeline。

## 範圍外(本次不做)

- 不檢查/警告兩個影片列被指定了同一個字幕檔(語意上大概沒意義,但 mkvmerge 不會因此出錯;交給使用者自行判斷)。
- 不支援瀏覽字幕資料夾以外的檔案(下拉選單只列出已掃描到的字幕資料夾內容;若要封裝資料夾外的字幕,使用者需先把檔案複製進字幕資料夾重新掃描)。
- 不改變「集數」欄的顯示邏輯或關聯性。

## 測試計畫(概要,交給 plan 階段細化)

- `set_row_subtitle` 直接呼叫:指定檔案 → 狀態變 matched + 勾選;傳 `None` → 狀態變 no_subtitle + 取消勾選
- 對原本 `ambiguous`/`no_subtitle`/`no_episode` 的列呼叫 `set_row_subtitle` 後,`checked_pairs()` 能正確回收該列
- 對原本 `matched` 的列改指定別的字幕 → `checked_pairs()` 回傳的 `MuxPair.subtitle_path` 是新指定的檔案,不是原本自動配對的
- `populate()` 在 `self._available_subtitles` 為空(未掃描過)時仍保留既有測試行為(相容性回歸測試)
- 下拉選單初始選取值正確(`matched` 列選中對應檔案,其餘選「(無)」)
