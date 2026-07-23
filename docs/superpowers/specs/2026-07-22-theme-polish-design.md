# 主題樣式深化(方案 B)Design

**背景**:目前 `qt/theme.py` 的樣式很薄——深色/淺色各約 15 行 QSS,只設定了最基本的背景/前景色與邊框。**完全沒有**針對清單列、選取狀態、hover、捲動條、群組框、進度條的樣式。結果是 MKV 分頁那種勾選樹、以及各分頁的表格,列與列之間沒有任何視覺分隔,選取哪一列也看不出來,整片糊在一起。

使用者拿參考工具「MKV Muxing Batch GUI」對比後,從三個方案中選定 **方案 B:加上列分隔與選取高亮,但不改密度**(方案 C 的緊湊密度被排除——字太小)。

## 需求(使用者確認)

1. **表格與樹狀清單**:列分隔線、交錯底色、hover 提示、明確的選取高亮。
2. **分頁籤**:選中的分頁用上緣強調線標示。
3. **主要動作按鈕**(開始處理 / 開始封裝 / 開始套用樣式)用強調色,次要按鈕維持中性灰。
4. **補上目前完全沒有樣式的控件**:捲動條、群組框(`QGroupBox`)、進度條。
5. **淺色模式做對應版本**,兩個主題視覺結構一致、只有配色不同。
6. **不改任何控件位置、密度、字級或程式邏輯。**

## 範圍的誠實說明:不只是 theme.py

方案 B 有兩項**無法只靠 QSS 完成**,必須在控件端各加一行:

- **交錯底色**:QSS 的 `alternate-background-color` 只有在該控件 `setAlternatingRowColors(True)` 時才生效。需要在 5 個控件各加一行:
  `qt/mkv_tab.py` 的 `self.tree`、`qt/mux_tab.py` 的 `self.table`、`qt/subtitle_tab.py` 的 `self.table`、`qt/modify_tracks_dialog.py` 的 `self.table`、`qt/readout_view.py` 的 `self.table`。
- **強調按鈕**:QSS 無從得知哪顆按鈕是「主要動作」。需要替 3 個分頁的主要按鈕加上一個動態屬性標記(`setProperty("accent", True)`),QSS 再用 `QPushButton[accent="true"]` 選取。

這些都是純樣式標記,不動位置、不動邏輯,但確實會碰到 `theme.py` 以外的檔案(約 8 行單行新增)。

## 核心設計

### 1. 配色表 + 共用樣板(取代兩份平行的 QSS 字串)

目前是 `_DARK_QSS` / `_LIGHT_QSS` 兩個獨立字串常數。樣式深化後兩者會各自長到約 80 行,**且必須在結構上互相對應**——只要有人只改其中一份,兩個主題就會悄悄長得不一樣。這是本次要順手修掉的維護性問題(改動範圍內的既有缺陷)。

改成:**一份共用 QSS 樣板 + 每個主題一組配色值**。兩個主題的差異被壓縮成純粹的顏色清單,結構不可能分岔。

```python
@dataclass(frozen=True)
class _Palette:
    window_bg: str      # 視窗底色
    text: str           # 主要文字
    text_dim: str       # 次要文字(表頭、未選分頁)
    field_bg: str       # 輸入框/清單底色
    row_alt: str        # 交錯列底色
    row_hover: str      # hover 列底色
    border: str         # 一般邊框
    border_light: str   # 列分隔線(比一般邊框更淡)
    surface: str        # 按鈕/分頁/表頭底色
    surface_hover: str  # 按鈕 hover
    accent: str         # 強調色(選取列、主要按鈕、分頁上緣線)
    accent_hover: str   # 強調色 hover
    accent_text: str    # 強調色上的文字
    disabled_text: str
```

**樣板用 `string.Template`(`$name` 佔位),不用 `str.format`**:QSS 本身充滿 `{` `}`,用 `format` 會把樣式規則的大括號當成佔位符而炸掉。並且用 `Template.substitute`(而非 `safe_substitute`)——漏掉任何一個顏色時會直接拋出 `KeyError`,不會靜默產生殘留 `$border` 的壞 QSS。

`qss_for(theme)` 的對外簽章與回傳型別不變(仍回傳 QSS 字串),因此 `apply_theme`、`main_window` 與既有測試都不受影響。

### 2. 樣板涵蓋的控件

在既有規則(`QMainWindow`/`QWidget`/`QTabBar`/`QLineEdit`/`QPushButton`/`QHeaderView` 等)之上補:

- `QTreeWidget` / `QTableWidget`:`alternate-background-color`、`gridline-color`;
  `::item` 加 `border-bottom` 做列分隔;
  `::item:hover` 用 `row_hover`;
  `::item:selected` 用 `accent` + `accent_text`。
- `QTabBar::tab:selected`:`border-top: 2px solid $accent`;未選中的用 `border-top: 2px solid transparent` 保持等高(避免選取時整排跳動)。
- `QPushButton[accent="true"]`:`accent` 底色 + `accent_text` 文字,hover 用 `accent_hover`;停用時仍走既有的 disabled 規則。
- `QScrollBar:vertical` / `:horizontal`:細捲軸,`surface` 軌道 + `border` 滑塊,hover 加深。
- `QGroupBox`:邊框 + 標題位置(目前「換算對照」群組框完全沒樣式)。
- `QProgressBar`:槽底 `field_bg`、`::chunk` 用 `accent`、文字置中。

### 3. 控件端的樣式標記

- 5 個表格/樹狀控件各加 `setAlternatingRowColors(True)`(位置緊接在該控件建立處)。
- 3 個主要動作按鈕各加 `setProperty("accent", True)`:
  `subtitle_tab.py` 的 `run_button`、`mkv_tab.py` 的 `run_button`、`mux_tab.py` 的 `run_button`。

（屬性在控件建立時就設好,`apply_theme` 是在 `MainWindow` 建構後才套用樣式表,因此不需要額外 repolish;之後切換主題時 `setStyleSheet` 會重新套用整個 app,屬性仍然保留。)

## 邊界與注意

- **Fusion 樣式依賴不變**:`apply_theme` 既有的「非 Fusion 就切成 Fusion」邏輯保留——Windows 原生樣式不完整遵守 QSS,這是既有且必要的行為。
- **標題列著色**不受影響(由 DWM 屬性控制,與 QSS 無關)。
- **兩個主題的可讀性**:淺色模式的 `accent` 上必須用白字、深色模式亦然;交錯列與 hover 底色在兩個主題都要與一般列有可見但不刺眼的差異。
- **不新增第三個主題**,不動 `THEME_MODES`。

## 範圍外

- 任何控件位置調整、分頁重新排版、把設定收進工具列之類的版面改造(使用者選 B 而非「連版面一起改」)。
- 密度/字級調整(方案 C 已被排除)。
- 字型變更。
- 參考工具的「Information About Tracks」每檔軌道資訊面板——那是獨立的新功能,不屬於樣式工作。

## 測試計畫(概要,交給 plan 細化)

- `theme.py`:
  - 兩個主題的 `qss_for` 都完全替換完成——**斷言結果中不含 `$`**(證明沒有殘留佔位符)。
  - 兩個主題都含新選擇器(`QTreeWidget`、`QScrollBar`、`QGroupBox`、`QProgressBar`、`accent`)。
  - 配色表缺欄位時 `Template.substitute` 會拋出(以刻意殘缺的 palette 驗證,證明錯誤不會被靜默吞掉)。
  - 既有測試維持通過:`qss_for("dark")` 含 `QMainWindow`、light 與 dark 不同、`resolve_theme` 各分支不變。
- 控件端:5 個表格/樹狀控件 `alternatingRowColors()` 為 True;3 個主要按鈕的 `property("accent")` 為 True。
- 既有全套測試維持通過(目前 360)。
