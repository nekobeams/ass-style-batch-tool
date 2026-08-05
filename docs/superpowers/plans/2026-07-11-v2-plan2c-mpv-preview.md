# v2 Plan 2c — mpv 即時預覽 Implementation Plan

**Goal:** 在「樣式與預覽」分頁右側內嵌 mpv 播放器——載入影片與字幕後,改樣式欄位 300ms 防抖自動熱重載字幕(所見即播放器渲染),字幕行清單點擊跳轉時間點;缺 libmpv 時優雅降級不影響其他功能。

**Architecture:** `player.py` 是薄薄的 mpv 包裝 widget(`_import_mpv()` 獨立函式供測試 monkeypatch,缺 libmpv 時所有操作安全 no-op);`preview_panel.py` 負責預覽協調(防抖計時器 → 既有 `preview.render_preview_ass` 產生暫存 .ass → 播放器 `sub-add`/`sub-reload`),播放器以鴨子型別注入,offscreen 測試用假播放器驗證行為。字幕行清單的資料整理是純函式(進 `gui_helpers.py`)。

**Tech Stack:** PySide6、python-mpv 1.0.8 + libmpv-2.dll(已裝於 site-packages,初始化已驗證)、pytest(offscreen Qt)。

**Spec:** `docs/superpowers/specs/2026-07-08-ass-style-tool-v2-design.md` 的「即時預覽」節

## Global Constraints

- 工作目錄/repo root:專案根目錄,git branch 由執行者自行建立
- **環境重點**:`python` 是壞的 Windows Store stub,一律用 `py`:`py -m pytest tests -v`
- Python 3.9+ 相容;每個新模組頂端加 `from __future__ import annotations`
- **測試絕不可真的初始化 mpv**(offscreen 下嵌入視窗會不穩):player 的測試一律 monkeypatch `_import_mpv`;preview_panel 的測試注入假播放器。真實播放驗證走手動冒煙。
- 缺 libmpv 時:`available()` 回 False、所有播放操作安全 no-op、預覽區顯示提示;**批次功能完全不受影響**(spec 要求)
- 預覽縮放規則與批次一致:走既有 `preview.render_preview_ass`(內部用 `apply_profile`),不得另寫縮放邏輯
- 既有「字幕檔」分頁與 StyleEditor 的行為不變(只新增 signal 與雙擊事件,不改既有流程)
- Qt 測試用既有 `tests/conftest.py` 的 offscreen `qapp` fixture
- 測試指令:`py -m pytest tests -v`(從 repo root;目前基準 167 passed)
- Commit 訊息用 conventional commits

### 既有介面(本計畫會用到,已實作且測試)

- `ass_style_tool.preview.render_preview_ass(source_ass_path, profile, out_path) -> list[str]`(不動來源檔,輸出 UTF-8 BOM)
- `ass_style_tool.ass_style.load_subs(path) -> pysubs2.SSAFile`(pysubs2 事件:`e.start`/`e.end` 為毫秒 int、`e.is_comment`、`e.plaintext` 去除 override 標籤並把 `\N` 轉換行)
- `ass_style_tool.profile.Profile`
- `qt.style_editor.StyleEditor`:`self._edits: dict[str, QLineEdit]`、`self._checks: dict[str, QCheckBox]`、`current_profile() -> Profile`(非法丟 ValueError)
- `qt.subtitle_tab.SubtitleFileTab`:`self.table`(QTableWidget)、`self._scan`(ScanResult 或 None,matches[row] 對應表格第 row 列)、signal `log(str)`
- `qt.main_window.MainWindow`:樣式與預覽分頁目前直接放 `self.style_editor`;`closeEvent` 已呼叫 `subtitle_tab.shutdown()`
- 測試輔助:`tests.test_ass_style.SAMPLE_ASS`(含 2 個 Dialogue 事件:0:00:01 測試字幕一、0:00:04 片頭曲)、`tests.test_profile_fields` 的 `DEFAULT_VALUES/profile_from_values`

## File Structure

```
ass_style_tool/qt/
├── gui_helpers.py     # (修改)附加 DialogueLine、format_timestamp、dialogue_lines
├── player.py          # (新)MpvPlayerWidget + _import_mpv
├── preview_panel.py   # (新)PreviewPanel:工具列、播放器、字幕行清單、防抖熱重載
├── style_editor.py    # (修改)加 values_changed signal
├── subtitle_tab.py    # (修改)加 preview_requested signal(表格雙擊)
└── main_window.py     # (修改)樣式與預覽分頁改為 QSplitter(StyleEditor | PreviewPanel)
tests/
├── test_gui_helpers.py    # (修改)附加 dialogue_lines 測試
├── test_player.py         # (新)
└── test_preview_panel.py  # (新)
```

---

### Task 1: gui_helpers — 字幕行清單純邏輯

**Files:**
- Modify: `ass_style_tool/qt/gui_helpers.py`(附加)
- Test: `tests/test_gui_helpers.py`(附加)

**Interfaces:**
- Consumes: pysubs2 SSAFile(事件屬性 start/end/is_comment/plaintext)
- Produces:
  - `DialogueLine` dataclass:`start_ms: int, end_ms: int, text: str`
  - `format_timestamp(ms: int) -> str` — `H:MM:SS.cc`(ASS 慣用格式)
  - `dialogue_lines(subs) -> list[DialogueLine]` — 跳過 Comment 事件;text 用 plaintext 去標籤、`\N` 換行摺成單一空格

- [ ] **Step 1: 附加失敗測試(tests/test_gui_helpers.py 末尾)**

```python
# ---------- 字幕行清單 ----------
import pysubs2

from ass_style_tool.qt.gui_helpers import (DialogueLine, dialogue_lines,
                                           format_timestamp)


def test_format_timestamp():
    assert format_timestamp(0) == "0:00:00.00"
    assert format_timestamp(1000) == "0:00:01.00"
    assert format_timestamp(61230) == "0:01:01.23"
    assert format_timestamp(3600000 + 125450) == "1:02:05.45"


def _subs_from(text: str) -> pysubs2.SSAFile:
    return pysubs2.SSAFile.from_string(text)


LINES_SAMPLE = (
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, Outline, Shadow\n"
    "Style: Default,Arial,40,2,1\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\fs40}大字\\N第二行\n"
    "Comment: 0,0:00:02.00,0:00:04.00,Default,,0,0,0,,這是註解事件\n"
    "Dialogue: 0,0:00:05.50,0:00:07.00,Default,,0,0,0,,一般對白\n"
)


def test_dialogue_lines_skips_comments_and_strips_tags():
    lines = dialogue_lines(_subs_from(LINES_SAMPLE))
    assert len(lines) == 2
    assert lines[0].start_ms == 1000
    assert lines[0].text == "大字 第二行"   # 標籤去除、\N 摺成空格
    assert lines[1].start_ms == 5500


def test_dialogue_lines_empty():
    empty = LINES_SAMPLE.split("[Events]")[0] + "[Events]\n" \
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    assert dialogue_lines(_subs_from(empty)) == []
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_gui_helpers.py -v`
Expected: FAIL — `ImportError: cannot import name 'DialogueLine'`

- [ ] **Step 3: 實作(附加到 gui_helpers.py 末尾)**

```python
@dataclass
class DialogueLine:
    start_ms: int
    end_ms: int
    text: str


def format_timestamp(ms: int) -> str:
    """毫秒 → 'H:MM:SS.cc'(ASS 慣用時間格式)。"""
    total_cs = int(round(ms / 10))
    hours, rem = divmod(total_cs, 360000)
    minutes, rem = divmod(rem, 6000)
    seconds, centis = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centis:02d}"


def dialogue_lines(subs) -> List[DialogueLine]:
    """取出非 Comment 的事件行;文字去 override 標籤、\\N 摺成空格。"""
    lines: List[DialogueLine] = []
    for event in subs.events:
        if event.is_comment:
            continue
        text = " ".join(event.plaintext.split())
        lines.append(DialogueLine(start_ms=event.start, end_ms=event.end,
                                  text=text))
    return lines
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_gui_helpers.py -v`
Expected: 9 passed(6 既有 + 3 新)

- [ ] **Step 5: Commit**

```powershell
git add ass_style_tool/qt/gui_helpers.py tests/test_gui_helpers.py
git commit -m "feat: add dialogue line listing helpers for preview"
```

---

### Task 2: player.py — 內嵌 mpv 播放器 widget

**Files:**
- Create: `ass_style_tool/qt/player.py`
- Test: `tests/test_player.py`

**Interfaces:**
- Consumes: python-mpv(執行期;測試一律 monkeypatch)
- Produces:
  - `_import_mpv()` — 回傳 mpv 模組或 None(ImportError/OSError 皆回 None);獨立函式供測試替換
  - `MpvPlayerWidget(QWidget)`:`available() -> bool`、`load_video(path) -> bool`、`video_loaded() -> bool`、`show_subtitle(ass_path)`(首次 `sub-add <path> select`,之後同路徑 `sub-reload`)、`seek(seconds)`(absolute,並暫停)、`toggle_pause()`、`shutdown()`;缺 mpv 時全部安全 no-op

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_player.py`:

```python
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


class FakeMPV:
    """記錄呼叫的假 mpv 實例。"""

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.commands = []
        self.played = []
        self.pause = False
        self.terminated = False

    def play(self, path):
        self.played.append(path)

    def command(self, *args):
        self.commands.append(args)

    def terminate(self):
        self.terminated = True


def _patch_mpv(monkeypatch, module):
    monkeypatch.setattr("ass_style_tool.qt.player._import_mpv", lambda: module)


def test_unavailable_all_noop(qapp, monkeypatch):
    from ass_style_tool.qt.player import MpvPlayerWidget
    _patch_mpv(monkeypatch, None)
    w = MpvPlayerWidget()
    assert w.available() is False
    assert w.load_video(Path("x.mkv")) is False
    assert w.video_loaded() is False
    # 全部安全 no-op,不得丟例外
    w.show_subtitle(Path("a.ass"))
    w.seek(1.5)
    w.toggle_pause()
    w.shutdown()


def test_load_video_creates_player_and_pauses(qapp, monkeypatch):
    from ass_style_tool.qt.player import MpvPlayerWidget
    fake_module = SimpleNamespace(MPV=FakeMPV)
    _patch_mpv(monkeypatch, fake_module)
    w = MpvPlayerWidget()
    assert w.available() is True
    assert w.load_video(Path("video.mkv")) is True
    assert w.video_loaded() is True
    assert w._mpv.played == ["video.mkv"]
    assert w._mpv.pause is True


def test_show_subtitle_add_then_reload(qapp, monkeypatch):
    from ass_style_tool.qt.player import MpvPlayerWidget
    _patch_mpv(monkeypatch, SimpleNamespace(MPV=FakeMPV))
    w = MpvPlayerWidget()
    w.load_video(Path("v.mkv"))
    w.show_subtitle(Path("p.ass"))
    w.show_subtitle(Path("p.ass"))
    assert w._mpv.commands[0] == ("sub-add", "p.ass", "select")
    assert w._mpv.commands[1] == ("sub-reload",)


def test_seek_and_shutdown(qapp, monkeypatch):
    from ass_style_tool.qt.player import MpvPlayerWidget
    _patch_mpv(monkeypatch, SimpleNamespace(MPV=FakeMPV))
    w = MpvPlayerWidget()
    w.load_video(Path("v.mkv"))
    w._mpv.pause = False
    w.seek(3.25)
    assert ("seek", 3.25, "absolute") in w._mpv.commands
    assert w._mpv.pause is True
    mpv_instance = w._mpv
    w.shutdown()
    assert mpv_instance.terminated is True
    assert w._mpv is None
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_player.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.qt.player'`

- [ ] **Step 3: 實作 player.py**

建立 `ass_style_tool/qt/player.py`:

```python
"""內嵌 mpv 播放器 widget:載入影片、外掛字幕熱重載、seek;缺 libmpv 時優雅降級。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QStackedLayout, QWidget


def _import_mpv():
    """獨立函式以便測試 monkeypatch;缺 libmpv 時 python-mpv 會丟 OSError。"""
    try:
        import mpv
        return mpv
    except (ImportError, OSError):
        return None


class MpvPlayerWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        # mpv 以原生視窗控制代碼(wid)嵌入,需要真正的原生視窗
        self.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self.setAttribute(Qt.WA_NativeWindow)
        self._mpv = None
        self._video_path: Optional[Path] = None
        self._sub_added = False

        self._hint = QLabel("尚未載入影片\n(缺 libmpv 時預覽停用,不影響批次功能)")
        self._hint.setAlignment(Qt.AlignCenter)
        layout = QStackedLayout(self)
        layout.addWidget(self._hint)
        self.setMinimumSize(320, 180)

    # ---------- 可用性 ----------
    def available(self) -> bool:
        return _import_mpv() is not None

    def _ensure_player(self) -> bool:
        if self._mpv is not None:
            return True
        mpv_module = _import_mpv()
        if mpv_module is None:
            return False
        self._mpv = mpv_module.MPV(
            wid=str(int(self.winId())),
            osc=False,
            input_default_bindings=False,
            keep_open="yes",
        )
        return True

    # ---------- 操作(缺 mpv 時皆安全 no-op) ----------
    def load_video(self, path: Path) -> bool:
        if not self._ensure_player():
            return False
        self._video_path = Path(path)
        self._sub_added = False
        self._hint.hide()
        self._mpv.play(str(path))
        self._mpv.pause = True
        return True

    def video_loaded(self) -> bool:
        return self._mpv is not None and self._video_path is not None

    def show_subtitle(self, ass_path: Path) -> None:
        """外掛字幕:首次 sub-add,之後同一路徑熱重載(sub-reload)。"""
        if not self.video_loaded():
            return
        if not self._sub_added:
            self._mpv.command("sub-add", str(ass_path), "select")
            self._sub_added = True
        else:
            self._mpv.command("sub-reload")

    def seek(self, seconds: float) -> None:
        if not self.video_loaded():
            return
        self._mpv.command("seek", seconds, "absolute")
        self._mpv.pause = True

    def toggle_pause(self) -> None:
        if self.video_loaded():
            self._mpv.pause = not self._mpv.pause

    def shutdown(self) -> None:
        if self._mpv is not None:
            try:
                self._mpv.terminate()
            except Exception:
                pass  # 關閉階段的清理失敗不影響程式結束
            self._mpv = None
        self._video_path = None
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_player.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```powershell
git add ass_style_tool/qt/player.py tests/test_player.py
git commit -m "feat: add embedded mpv player widget with graceful degradation"
```

---

### Task 3: preview_panel.py — 預覽面板(防抖熱重載 + 行清單)

**Files:**
- Create: `ass_style_tool/qt/preview_panel.py`
- Test: `tests/test_preview_panel.py`

**Interfaces:**
- Consumes: `preview.render_preview_ass`、`ass_style.load_subs`、`gui_helpers.dialogue_lines/format_timestamp`、`player.MpvPlayerWidget`(可注入替身)
- Produces:
  - `DEBOUNCE_MS = 300`
  - `PreviewPanel(QWidget)`:建構子 `(get_profile: Callable[[], Profile], player: QWidget | None = None)`;`set_media(sub_path, video_path=None)`;`on_style_changed()`(啟動防抖);`_apply_preview()`(產生暫存 .ass 並叫播放器顯示);`line_list`(QListWidget);`shutdown()`(關播放器、清暫存)
  - 注入播放器需具備:`load_video(path)->bool / video_loaded()->bool / show_subtitle(path) / seek(sec) / toggle_pause() / shutdown()`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_preview_panel.py`:

```python
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QWidget

from ass_style_tool.profile_fields import DEFAULT_VALUES, profile_from_values


class FakePlayer(QWidget):
    """假播放器;必須是 QWidget 才能被面板 addWidget。"""

    def __init__(self):
        super().__init__()
        self.videos = []
        self.subtitles = []
        self.seeks = []
        self.paused_toggles = 0
        self.shut = False
        self._loaded = False

    def load_video(self, path):
        self.videos.append(Path(path))
        self._loaded = True
        return True

    def video_loaded(self):
        return self._loaded

    def show_subtitle(self, path):
        self.subtitles.append(Path(path))

    def seek(self, seconds):
        self.seeks.append(seconds)

    def toggle_pause(self):
        self.paused_toggles += 1

    def shutdown(self):
        self.shut = True


def _write_sample(tmp_path: Path) -> Path:
    from tests.test_ass_style import SAMPLE_ASS
    p = tmp_path / "e01.ass"
    p.write_bytes(b"\xef\xbb\xbf" + SAMPLE_ASS.encode("utf-8"))
    return p


def _panel(player):
    from ass_style_tool.qt.preview_panel import PreviewPanel
    return PreviewPanel(lambda: profile_from_values(DEFAULT_VALUES),
                        player=player)


def test_set_media_renders_preview_and_lists_lines(qapp, tmp_path):
    player = FakePlayer()
    panel = _panel(player)
    sub = _write_sample(tmp_path)
    panel.set_media(sub, video_path=Path("v.mkv"))
    assert player.videos == [Path("v.mkv")]
    assert len(player.subtitles) == 1          # 立即產生一次預覽
    assert player.subtitles[0].exists()        # 暫存 .ass 真的寫出
    assert panel.line_list.count() == 2        # SAMPLE_ASS 兩個 Dialogue
    panel.shutdown()


def test_set_media_without_video_lists_but_no_show(qapp, tmp_path):
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path))
    assert player.subtitles == []              # 沒影片就不叫 show_subtitle
    assert panel.line_list.count() == 2
    panel.shutdown()


def test_on_style_changed_starts_debounce(qapp, tmp_path):
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path), video_path=Path("v.mkv"))
    assert panel._debounce.isActive() is False
    panel.on_style_changed()
    assert panel._debounce.isActive() is True
    panel._debounce.stop()
    panel._apply_preview()                     # 直接呼叫防抖到期的行為
    assert len(player.subtitles) == 2
    panel.shutdown()


def test_invalid_profile_skips_preview(qapp, tmp_path):
    player = FakePlayer()
    from ass_style_tool.qt.preview_panel import PreviewPanel

    def bad_profile():
        raise ValueError("欄位無效")

    panel = PreviewPanel(bad_profile, player=player)
    panel.set_media(_write_sample(tmp_path), video_path=Path("v.mkv"))
    assert player.subtitles == []              # 無效欄位不預覽、不丟例外
    panel.shutdown()


def test_line_click_seeks(qapp, tmp_path):
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path), video_path=Path("v.mkv"))
    item = panel.line_list.item(0)             # SAMPLE_ASS 第一句 0:00:01.00
    panel._on_line_clicked(item)
    assert player.seeks == [1.0]
    panel.shutdown()


def test_shutdown_cleans_temp(qapp, tmp_path):
    player = FakePlayer()
    panel = _panel(player)
    panel.set_media(_write_sample(tmp_path), video_path=Path("v.mkv"))
    temp = panel._temp_ass
    assert temp.exists()
    panel.shutdown()
    assert player.shut is True
    assert not temp.exists()
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_preview_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ass_style_tool.qt.preview_panel'`

- [ ] **Step 3: 實作 preview_panel.py**

建立 `ass_style_tool/qt/preview_panel.py`:

```python
"""預覽面板:mpv 播放器 + 字幕行清單 + 樣式變更 300ms 防抖熱重載。"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from ..ass_style import load_subs
from ..preview import render_preview_ass
from ..profile import Profile
from .gui_helpers import dialogue_lines, format_timestamp
from .player import MpvPlayerWidget

DEBOUNCE_MS = 300


class PreviewPanel(QWidget):
    def __init__(self, get_profile: Callable[[], Profile],
                 player: Optional[QWidget] = None) -> None:
        super().__init__()
        self._get_profile = get_profile
        self.player = player if player is not None else MpvPlayerWidget()
        self._source_sub: Optional[Path] = None
        self._temp_dir = Path(tempfile.mkdtemp(prefix="ass_style_preview_"))
        self._temp_ass = self._temp_dir / "preview.ass"

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        open_video = QPushButton("開啟影片…")
        open_video.clicked.connect(self._open_video)
        open_sub = QPushButton("載入字幕…")
        open_sub.clicked.connect(self._open_sub)
        pause = QPushButton("播放 / 暫停")
        pause.clicked.connect(self.player.toggle_pause)
        bar.addWidget(open_video)
        bar.addWidget(open_sub)
        bar.addWidget(pause)
        bar.addStretch(1)
        root.addLayout(bar)

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.player)
        self.line_list = QListWidget()
        self.line_list.itemClicked.connect(self._on_line_clicked)
        split.addWidget(self.line_list)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)

        self.status = QLabel("尚未載入字幕")
        root.addWidget(self.status)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._apply_preview)

    # ---------- 對外 ----------
    def set_media(self, sub_path: Path,
                  video_path: Optional[Path] = None) -> None:
        self._source_sub = Path(sub_path)
        if video_path is not None:
            self.player.load_video(Path(video_path))
        self._refresh_lines()
        self._apply_preview()

    def on_style_changed(self) -> None:
        if self._source_sub is not None:
            self._debounce.start()

    # ---------- 檔案選擇 ----------
    def _open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "開啟影片", "",
            "影片 (*.mkv *.mp4 *.avi *.webm *.ts);;所有檔案 (*)")
        if path:
            self.player.load_video(Path(path))
            self._apply_preview()

    def _open_sub(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "載入字幕", "", "ASS/SSA (*.ass *.ssa)")
        if path:
            self.set_media(Path(path))

    # ---------- 內部 ----------
    def _refresh_lines(self) -> None:
        self.line_list.clear()
        if self._source_sub is None:
            return
        try:
            subs = load_subs(self._source_sub)
        except Exception as exc:  # 單檔讀取失敗只顯示狀態,不中斷
            self.status.setText(f"字幕讀取失敗: {exc}")
            return
        for line in dialogue_lines(subs):
            item = QListWidgetItem(
                f"{format_timestamp(line.start_ms)}  {line.text}")
            item.setData(Qt.UserRole, line.start_ms)
            self.line_list.addItem(item)
        self.status.setText(
            f"{self._source_sub.name}(共 {self.line_list.count()} 行,點擊跳轉)")

    def _on_line_clicked(self, item: QListWidgetItem) -> None:
        self.player.seek(item.data(Qt.UserRole) / 1000.0)

    def _apply_preview(self) -> None:
        if self._source_sub is None:
            return
        try:
            profile = self._get_profile()
        except ValueError:
            return  # 欄位打到一半暫時無效,略過本次防抖
        try:
            render_preview_ass(self._source_sub, profile, self._temp_ass)
        except Exception as exc:
            self.status.setText(f"預覽產生失敗: {exc}")
            return
        if self.player.video_loaded():
            self.player.show_subtitle(self._temp_ass)

    def shutdown(self) -> None:
        self.player.shutdown()
        try:
            if self._temp_ass.exists():
                self._temp_ass.unlink()
            self._temp_dir.rmdir()
        except OSError:
            pass  # 暫存清理失敗不影響關閉
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_preview_panel.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```powershell
git add ass_style_tool/qt/preview_panel.py tests/test_preview_panel.py
git commit -m "feat: add preview panel with debounced hot-reload and line list"
```

---

### Task 4: 整合 — StyleEditor 訊號、字幕表格雙擊、主視窗分頁重排

**Files:**
- Modify: `ass_style_tool/qt/style_editor.py`(加 values_changed signal)
- Modify: `ass_style_tool/qt/subtitle_tab.py`(加 preview_requested signal)
- Modify: `ass_style_tool/qt/main_window.py`(分頁改 QSplitter、接線、closeEvent)
- Test: `tests/test_style_editor.py`、`tests/test_subtitle_tab.py`(各附加)

**Interfaces:**
- Consumes: Task 3 的 `PreviewPanel`
- Produces:
  - `StyleEditor.values_changed = Signal()` — 任一欄位(QLineEdit textChanged / QCheckBox toggled)變更時發出
  - `SubtitleFileTab.preview_requested = Signal(object, object)` — 表格某列雙擊時發出 `(sub_path: Path, video_path: Path|None)`
  - MainWindow:「樣式與預覽」分頁 = `QSplitter(StyleEditor | PreviewPanel)`;`values_changed → preview_panel.on_style_changed`;`preview_requested → set_media + 切到預覽分頁`;`closeEvent` 加 `preview_panel.shutdown()`

- [ ] **Step 1: 附加失敗測試**

`tests/test_style_editor.py` 末尾附加:

```python
def test_values_changed_signal_fires(qapp):
    from ass_style_tool.qt.style_editor import StyleEditor
    editor = StyleEditor()
    fired = []
    editor.values_changed.connect(lambda: fired.append(1))
    editor._edits["fontsize"].setText("88")
    assert len(fired) >= 1
    before = len(fired)
    editor._checks["bold"].setChecked(True)
    assert len(fired) > before
```

`tests/test_subtitle_tab.py` 末尾附加:

```python
def test_preview_requested_on_double_click(qapp):
    from pathlib import Path
    from ass_style_tool.qt.subtitle_tab import SubtitleFileTab
    tab = SubtitleFileTab(lambda: profile_from_values(DEFAULT_VALUES))
    tab.populate_preview(_scan())
    tab._scan = _scan()
    got = []
    tab.preview_requested.connect(lambda s, v: got.append((s, v)))
    tab._on_row_double_clicked(0, 0)
    assert got == [(Path("a [01].ass"), Path("v01.mkv"))]
    tab._on_row_double_clicked(1, 2)
    assert got[1] == (Path("b [02].ass"), None)
```

(說明:`_scan()` 是該測試檔既有的 helper,回傳兩列 matches:第一列有影片、第二列 no_video。)

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_style_editor.py tests/test_subtitle_tab.py -v`
Expected: 新增兩個測試 FAIL(`AttributeError: values_changed` / `preview_requested`)

- [ ] **Step 3: 修改 style_editor.py**

(a)class 宣告下加 signal(import 區補 `from PySide6.QtCore import Signal`):

```python
class StyleEditor(QWidget):
    values_changed = Signal()
```

(b)`__init__` 末尾(`self._refresh_profile_list()` 之後)加:

```python
        for edit in self._edits.values():
            edit.textChanged.connect(self.values_changed)
        for check in self._checks.values():
            check.toggled.connect(self.values_changed)
```

- [ ] **Step 4: 修改 subtitle_tab.py**

(a)class 宣告的 `log = Signal(str)` 下加:

```python
    preview_requested = Signal(object, object)  # (sub_path, video_path|None)
```

(b)`__init__` 中 `self.table` 建立完成後(setEditTriggers 那段之後)加:

```python
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
```

(c)新增方法(放在 `populate_preview` 之後):

```python
    def _on_row_double_clicked(self, row: int, _column: int) -> None:
        if self._scan is None or row >= len(self._scan.matches):
            return
        match = self._scan.matches[row]
        self.preview_requested.emit(match.sub_path, match.video_path)
```

- [ ] **Step 5: 修改 main_window.py**

(a)import 區加:

```python
from PySide6.QtWidgets import QSplitter
from .preview_panel import PreviewPanel
```

(把 `QSplitter` 併入既有的 QtWidgets import 行亦可。)

(b)把「樣式與預覽」分頁那行:

```python
        self.tabs.addTab(self.style_editor, "樣式與預覽")
```

替換為:

```python
        self.preview_panel = PreviewPanel(self.style_editor.current_profile)
        self._preview_split = QSplitter()
        self._preview_split.addWidget(self.style_editor)
        self._preview_split.addWidget(self.preview_panel)
        self._preview_split.setStretchFactor(1, 1)
        self.tabs.addTab(self._preview_split, "樣式與預覽")
        self.style_editor.values_changed.connect(
            self.preview_panel.on_style_changed)
        self.subtitle_tab.preview_requested.connect(self._open_in_preview)
```

(c)新增方法(放在 `append_log` 之前):

```python
    def _open_in_preview(self, sub_path, video_path) -> None:
        self.preview_panel.set_media(sub_path, video_path)
        self.tabs.setCurrentWidget(self._preview_split)
        if video_path is None:
            self.append_log("該列未配對到影片,預覽僅載入字幕行清單;"
                            "可在預覽分頁手動開啟影片")
```

(d)`closeEvent` 中 `self.subtitle_tab.shutdown()` 之後加:

```python
        self.preview_panel.shutdown()
```

- [ ] **Step 6: 執行測試 + 全套**

Run: `py -m pytest tests/test_style_editor.py tests/test_subtitle_tab.py -v`
Expected: 各自全過(含新測試)

Run: `py -m pytest tests -v`
Expected: 182 passed(167 + 3 + 4 + 6 + 2)

- [ ] **Step 7: import + 啟動冒煙**

Run: `py -c "import ass_style_tool.qt.main_window; print('ok')"`
Expected: `ok`

```powershell
$p = Start-Process -FilePath "py" -ArgumentList "-m","ass_style_tool" -WorkingDirectory $PWD -PassThru
Start-Sleep -Seconds 3
if ($p.HasExited) { Write-Output "FAIL exit=$($p.ExitCode)" } else { Write-Output "OK"; Stop-Process -Id $p.Id }
```

Expected: `OK`

- [ ] **Step 8: 手動冒煙清單(由使用者執行,記於報告)**

Run: `py -m ass_style_tool`
1. 「樣式與預覽」分頁:左邊樣式欄位、右邊預覽區(工具列 + 播放器區 + 行清單)
2. 「開啟影片…」選一部 mkv/mp4 → 影片畫面出現且暫停;「播放 / 暫停」可切換
3. 「載入字幕…」選對應 .ass → 行清單列出對白;點某一行 → 影片跳到該時間點
4. 改左邊任何樣式欄位(字型/大小/顏色)→ 約 0.3 秒後畫面上字幕樣式即時更新
5. 「字幕檔」分頁掃描後雙擊有配對影片的列 → 自動切到預覽分頁、影片+字幕都載好
6. 雙擊無影片的列 → 切到預覽分頁、行清單有內容、log 提示可手動開影片
7. 關閉程式無錯誤(mpv 正常終止、暫存清掉)

- [ ] **Step 9: Commit**

```powershell
git add ass_style_tool/qt/style_editor.py ass_style_tool/qt/subtitle_tab.py ass_style_tool/qt/main_window.py tests/test_style_editor.py tests/test_subtitle_tab.py
git commit -m "feat: wire live mpv preview into style tab with double-click handoff"
```

---

## 本計畫完成後

即時預覽完整可用(Subtitle Edit 式體驗)。接著 **Plan 2d — MKV 分頁**:`mkv_batch.py` 批次協調(抽軌→套用樣式或縮放→重封裝→取代原檔驗證)、MKV 分頁 UI(軌道表格、一鍵選整季同類型軌、進度/取消)、「送進預覽」整合。之後 **Plan 3 — 打包**。
