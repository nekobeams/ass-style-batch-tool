# 設定持久化(QSettings)Design

**背景**:spec UX-1「設定持久化」目前只做了視窗大小與主題模式(`ass_style_tool/qt/main_window.py` 的 `_restore_settings`/`closeEvent`)。三個分頁(字幕檔/MKV/封裝)的來源資料夾、輸出模式、輸出資料夾路徑,以及樣式編輯的上次選用 profile,重開程式都會被重置,每次都要重選。本設計補齊這塊。

## 需求(使用者確認)

1. **範圍**:照 spec UX-1 清單——各分頁來源資料夾(含封裝分頁的影片+字幕兩個)、輸出模式選擇+輸出資料夾路徑、上次選用的 profile。不含處理模式(套用/縮放)、縮放倍率、封裝軌資訊(語言/軌名/default/forced)——這些維持每次預設值,不記。
2. **還原後不自動掃描**:重開程式只把路徑文字填回輸入欄,不重建表格、不觸發背景執行緒。使用者需要手動觸發掃描(按鈕或改動路徑欄位)才會真的讀取資料夾內容。
3. **存檔時機**:比照現有視窗大小/主題模式的存檔時機——`closeEvent` 時存;不做即時存檔(避免頻繁寫 QSettings)。

## 架構

每個分頁新增一對方法:

```python
def save_settings(self, settings: QSettings) -> None: ...
def restore_settings(self, settings: QSettings) -> None: ...
```

各自用分頁專屬 key 前綴(`subtitle/`、`mkv/`、`mux/`、`style/`),避免互相覆蓋。`MainWindow`:

- `_restore_settings()`(所有分頁已建構完畢後呼叫)新增呼叫每個分頁的 `restore_settings(self.settings)`
- `closeEvent()` 新增呼叫每個分頁的 `save_settings(self.settings)`(在既有 `self.settings.setValue("geometry", ...)` 之前或之後皆可,無順序依賴)

還原時只呼叫 `setText()`/`setChecked()`——**不**呼叫任何 `_auto_scan`/`_on_scan` 等會觸發背景執行緒或表格重建的方法,`setText()` 本身不會觸發 `editingFinished` 訊號,天然滿足「不自動掃描」的要求。

## 各分頁存讀的欄位與 key

### `SubtitleFileTab`(`ass_style_tool/qt/subtitle_tab.py`)

| Key | 對應控件 | 型別 |
|---|---|---|
| `subtitle/folder` | `self.folder_edit` | str |
| `subtitle/output_mode` | `inplace`/`outdir`,依 `self.inplace_radio.isChecked()`/`self.outdir_radio.isChecked()` | str |
| `subtitle/outdir` | `self.outdir_edit` | str |

```python
def save_settings(self, settings: QSettings) -> None:
    settings.setValue("subtitle/folder", self.folder_edit.text())
    settings.setValue(
        "subtitle/output_mode",
        "outdir" if self.outdir_radio.isChecked() else "inplace")
    settings.setValue("subtitle/outdir", self.outdir_edit.text())

def restore_settings(self, settings: QSettings) -> None:
    self.folder_edit.setText(settings.value("subtitle/folder", ""))
    self.outdir_edit.setText(settings.value("subtitle/outdir", ""))
    if settings.value("subtitle/output_mode", "inplace") == "outdir":
        self.outdir_radio.setChecked(True)
    else:
        self.inplace_radio.setChecked(True)
```

### `MkvTab`(`ass_style_tool/qt/mkv_tab.py`)

| Key | 對應控件 |
|---|---|
| `mkv/folder` | `self.folder_edit` |
| `mkv/output_mode` | `outdir`/`replace`,依 `self.outdir_radio`/`self.replace_radio` |
| `mkv/outdir` | `self.outdir_edit` |

程式碼結構與 `SubtitleFileTab` 對稱(輸出模式改成 outdir/replace 二選一)。

### `MuxTab`(`ass_style_tool/qt/mux_tab.py`)

| Key | 對應控件 |
|---|---|
| `mux/video_folder` | `self.video_edit` |
| `mux/subtitle_folder` | `self.subtitle_edit` |
| `mux/output_mode` | `outdir`/`replace`,依 `self.outdir_radio`/`self.replace_radio` |
| `mux/outdir` | `self.outdir_edit` |

### `StyleEditor`(`ass_style_tool/qt/style_editor.py`)

只記錄「上次選用的 profile 檔路徑」,不記編輯中的欄位值(欄位值本來就是由選中的 profile 決定,或使用者手動編輯中,不應被 QSettings 覆蓋)。

```python
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
        self.load_profile_from(path)
    # 找不到(檔案已刪除/搬移)→ 靜默保持目前預設值,不報錯、不彈窗
```

`restore_settings` 必須在 `_refresh_profile_list()`(建構子內已呼叫,建立 combo 選項)**之後**才能正確 `findData`——`StyleEditor.__init__` 本身已經在 `_refresh_profile_list()` 之後才回傳,所以 `MainWindow._restore_settings()` 呼叫時序上沒有問題(分頁都已建構完成)。

## MainWindow 接線

在 `_restore_settings()`(既有讀 `geometry`/`theme_mode` 的方法)結尾追加:

```python
    self.style_editor.restore_settings(self.settings)
    self.subtitle_tab.restore_settings(self.settings)
    self.mkv_tab.restore_settings(self.settings)
    self.mux_tab.restore_settings(self.settings)
```

在 `closeEvent()` 中(既有 `shutdown()` 呼叫之後、`self.settings.setValue("geometry", ...)` 之前皆可)追加:

```python
    self.style_editor.save_settings(self.settings)
    self.subtitle_tab.save_settings(self.settings)
    self.mkv_tab.save_settings(self.settings)
    self.mux_tab.save_settings(self.settings)
```

## 測試計畫(概要)

- 每個分頁的 `save_settings`/`restore_settings` 用 `QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat)` 注入,不碰真實 registry/使用者設定:
  - 建分頁 A → 設定控件值 → `save_settings(settings)` → 建全新分頁 B → `restore_settings(settings)` → 斷言 B 的控件值與 A 一致
  - 斷言還原後**沒有**觸發掃描(表格/清單維持空,或監看 `_scanned_folder`/`_pairs` 等內部狀態未被填入——依各分頁既有可測 API 而定)
- `StyleEditor`:profile 路徑存在時能正確選中並載入;路徑已不存在(`tmp_path` 外的假路徑)時 `restore_settings` 不拋例外、combo 維持原狀

## 範圍外

- 不記錄處理模式(套用/縮放)、縮放倍率、封裝軌資訊(語言/軌名/default/forced)——維持每次預設值
- 不做即時(每次改動就存)持久化,只在 `closeEvent` 存一次,與現有視窗大小/主題模式時機一致
- 不處理「輸出資料夾不存在」等路徑失效情境的特殊提示——文字照樣還原,使用者若之後執行時路徑無效,沿用既有的錯誤處理路徑(各分頁 `_on_run`/`_on_scan` 既有的資料夾有效性檢查)
