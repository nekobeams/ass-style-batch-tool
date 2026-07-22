# Modify Old Tracks(封裝時修改來源既有軌道)Design

**背景**:目前「封裝」分頁把外部 `.ass` 字幕封進 MKV 時,來源影片是以「所有軌原封不動」加入(`mkv_mux.build_mux_command` 只把 `video_path` 當輸入、不下任何針對既有軌道的旗標),再附上新的外部字幕軌。使用者希望在同一次封裝中,順便控制來源 MKV 裡**既有**的軌道:丟掉不要的字幕軌、把某音訊/字幕設成(或取消)預設軌、設 forced、重設語言與軌名。功能對標參考工具「MKV Muxing Batch GUI」的 Modify Old Tracks 對話框。

**核心決策(使用者確認)**:
1. **整合進「封裝」分頁**——和字幕封裝同一次完成,不做獨立入口。
2. **定一次、依軌 ID 套用到全部**——同一來源整季軌道結構通常一致;使用者對每條既有軌設定一次,依 mkvmerge 軌 ID 套到所有影片。
3. **四種操作**:保留/丟棄軌、設預設軌(default)、設強制軌(forced)、重設語言/軌名。**不含重新排序**(參考工具有,本版不做)。
4. **批次安全網**:封裝每部影片時只對「該影片實際存在的軌 ID」套用規則,缺該軌就跳過那條規則,避免對不存在的 ID 下旗標讓 mkvmerge 報錯。

## 元件與職責

### 1. 列出所有軌道(`mkv_io.py`,擴充)

目前 `mkv_io` 只有 `list_ass_tracks`(僅回 ASS 字幕軌)。新增列出**所有**軌道(影片/音訊/字幕):

```python
@dataclass
class MediaTrack:
    track_id: int          # mkvmerge -J 的全域 track id
    track_type: str        # "video" | "audio" | "subtitles"
    codec_id: str
    language: str
    track_name: str
    default: bool
    forced: bool

def parse_all_tracks(identify_json: dict) -> List[MediaTrack]:
    """從 mkvmerge -J 的 dict 取出所有 video/audio/subtitles 軌(依 id 排序)。"""

def list_all_tracks(mkv_path: Path, mkvmerge: Path) -> List[MediaTrack]:
    """跑 mkvmerge -J 列出所有軌;任何失敗回 []。(沿用既有 subprocess 慣例:
    text/encoding=utf-8/timeout/no_window_kwargs)"""
```

既有 `SubtitleTrack`/`parse_ass_tracks`/`list_ass_tracks` 不動(MKV restyle 分頁仍用)。

### 2. 設定模型 + 旗標建構(新檔 `ass_style_tool/track_edit.py`,純邏輯無 Qt)

```python
@dataclass
class TrackEdit:
    keep: bool = True                    # False=丟棄此軌
    set_default: Optional[bool] = None   # None=不變;True/False=設定 default 旗標
    set_forced: Optional[bool] = None    # None=不變;True/False=設定 forced 旗標
    language: Optional[str] = None       # None/"" = 不變
    track_name: Optional[str] = None     # None/"" = 不變

def build_source_track_flags(
    edits: Dict[int, TrackEdit],
    tracks: List[MediaTrack],
) -> List[str]:
    """把設定轉成套在來源影片輸入「前面」的 mkvmerge 旗標。
    只針對 tracks 內實際存在的 track_id 產生旗標(per-video 安全網)。"""
```

**旗標規則**(`build_source_track_flags`):
- **保留/丟棄**(依 type 分組):
  - 該 type 全部保留 → 不下旗標(mkvmerge 預設全留)。
  - 該 type 全部丟棄 → `--no-video` / `--no-audio` / `--no-subtitles`。
  - 部分丟棄 → `--video-tracks` / `--audio-tracks` / `--subtitle-tracks` 後接**保留**的 id(逗號分隔)。
- **屬性(default/forced/語言/軌名)只對「保留」的軌產生**(丟棄的軌設屬性無意義):
  - `set_default is not None` → `--default-track <id>:yes|no`
  - `set_forced is not None` → `--forced-track <id>:yes|no`
  - `language`(非空)→ `--language <id>:<code>`
  - `track_name`(非空)→ `--track-name <id>:<name>`
- `edits` 中沒對應項的軌 → 視為預設 `TrackEdit()`(保留、無屬性變更)。
- `edits` 為空 → 回 `[]`(等同現行行為)。

沿用既有 `--default-track`/`--forced-track`/`--language`/`--track-name` 旗標(封裝 code 已在用,相容各版 mkvmerge)。

### 3. 封裝命令與管線(`mkv_mux.py`,修改)

- `build_mux_command` 加一個 `source_flags: Optional[List[str]] = None` 參數,插在 `-o <out>` 與 `<video_path>` **之間**(mkvmerge 的輸入專屬旗標必須排在該輸入檔前):

  ```
  [mkvmerge, -o, out, *source_flags, video, --language 0:.., (--track-name..), --default-track 0:.., --forced-track 0:.., subtitle]
  ```

  `source_flags=None` → 行為與現行完全相同。

- `_default_mux` 與 `mux_fn` 協定加一個尾端 `source_flags: Optional[List[str]] = None` 參數,轉交給 `build_mux_command`。(既有測試裡的假 `mux_fn` 一併補上這個預設參數。)

- `process_mux` 加參數 `edits: Optional[Dict[int, TrackEdit]] = None` 與 `track_list_fn: Callable = list_all_tracks`(可注入以便測試)。流程:
  - `edits` 為空/None → `source_flags = []`(不掃描、不改變現行行為)。
  - 否則:`tracks = track_list_fn(video, tools.mkvmerge)` → `source_flags = build_source_track_flags(edits, tracks)`;掃描失敗(回 `[]` 或丟例外)→ `source_flags = []`(安全降級:該影片不做軌道修改,照常封裝)。
  - 呼叫 `mux_fn(..., source_flags=source_flags)`。

### 4. 對話框(新檔 `ass_style_tool/qt/modify_tracks_dialog.py`)

`ModifyTracksDialog(QDialog)`:
- 建構參數:`tracks: List[MediaTrack]`(由呼叫端先掃好傳入,對話框本身不碰 mkvmerge → 可離線測試)、`existing: Optional[Dict[int, TrackEdit]] = None`(重開時預填上次設定)。
- 表格每列一條既有軌,欄位:
  - **保留**(勾選框,預設依 existing 或全勾)
  - **類型**(唯讀:影片/音訊/字幕)
  - **編碼**(唯讀 codec_id)
  - **語言**(可編輯,留空=不變;預填目前語言為 placeholder 提示,但空白才代表不變)
  - **軌名**(可編輯,留空=不變)
  - **預設**(下拉:不變/是/否)
  - **強制**(下拉:不變/是/否)
- `get_edits() -> Dict[int, TrackEdit]`:讀表格組成設定(語言/軌名空白 → None;下拉「不變」→ None)。
- 標準 OK/取消按鈕。

### 5. 封裝分頁接線(`qt/mux_tab.py` + `qt/batch_worker.py`,修改)

- `MuxTab` 新增狀態 `self._track_edits: Dict[int, TrackEdit] = {}`(空=不修改,即現行行為)。
- 新增按鈕「修改既有軌道…」(僅在 `tools_available` 且已有至少一部 matched 影片時可按):
  - 點擊 → 取**第一部 matched 影片**,以 `list_all_tracks` 掃描其軌道(單檔 mkvmerge -J,同步執行 + 等待游標;非同步進度對話框屬下一個功能)。掃不到軌 → log 提示、不開對話框。
  - 開 `ModifyTracksDialog(tracks, self._track_edits)`;按 OK → `self._track_edits = dialog.get_edits()`。
  - 按鈕文字在已設定時可加註記(例如「修改既有軌道…(已設定)」)以提示狀態。
- `_on_run` 把 `self._track_edits` 交給 `MuxWorker`。
- `MuxWorker.__init__` 加 `edits` 參數,`run()` 呼叫 `process_fn(..., edits=self._edits)` 轉交 `process_mux`。

## 資料流

```
封裝分頁掃描(影片↔外部字幕配對,現有)
  → 使用者按「修改既有軌道…」→ list_all_tracks(第一部 matched 影片)
  → ModifyTracksDialog → get_edits() → MuxTab._track_edits
  → 開始封裝 → MuxWorker(edits) → process_mux(edits, track_list_fn)
      → 每部影片:list_all_tracks → build_source_track_flags(edits, 該影片的軌)
      → build_mux_command(source_flags=…) → mkvmerge
```

## 邊界與注意

- **多個預設軌**:使用者若同時把某既有軌與新字幕(封裝分頁既有的「預設軌」勾選)都設成 default,輸出會有多條 default 旗標——由使用者自行決定,不強制互斥(播放器自行取一)。
- **屬性只作用於保留軌**:丟棄的軌不產生 default/forced/語言/軌名旗標。
- **軌 ID 定址**:mkvmerge 的 `--language <id>` 等一律以**來源檔的原始 id** 定址,即使同時丟棄其他軌也不受影響。
- **降級**:任何一部影片掃軌失敗 → 該影片略過軌道修改、仍照常封裝(不讓整批失敗)。

## 範圍外(本版不做)

- **重新排序軌道**(參考工具的 Ctrl+Up/Down):需跨輸入控制 `--track-order`,複雜度高,留待之後。
- **章節 / 附件的修改**:本版只處理 video/audio/subtitles 軌。
- **清空既有軌名**(把有名字的軌改成無名):空白一律代表「不變」;之後需要再加。
- **開對話框前掃描全部影片以偵測軌道結構不一致並提醒**:本版以「第一部當範本 + per-video 過濾」的安全網保證正確性;全批掃描 + 進度動畫屬下一個排定功能(載入進度對話框),屆時可一併補上一致性提醒。
- **非同步掃描進度**:單檔掃描同步執行即可;批次掃描的進度 UI 屬下一個功能。

## 測試計畫(概要,交給 plan 細化)

- `parse_all_tracks` / `list_all_tracks`(用既有 fixture `mkvmerge_identify_sample.json`,含 video/audio/3 字幕):欄位正確、依 id 排序;`list_all_tracks` 以 monkeypatch subprocess 驗證(含失敗回 `[]`)。
- `build_source_track_flags`:
  - 全保留 → 無 keep/drop 旗標。
  - 丟一條字幕 → `--subtitle-tracks` 接保留 id。
  - 丟光某 type → `--no-audio` 等。
  - 保留軌設 default/forced/語言/軌名 → 旗標正確;None/空白不產生;丟棄軌不產生。
  - 只對傳入 tracks 內存在的 id 產生(per-video 過濾)。
- `build_mux_command`:`source_flags` 正確插在 `-o out` 與 `video` 之間;`None` 時與現行輸出一致。
- `process_mux`:`edits` 非空 → 以假 `track_list_fn` 掃軌、旗標傳進假 `mux_fn`(斷言收到 `source_flags`);`edits` 空 → `source_flags=[]`(回歸);掃軌失敗 → 降級 `[]`。
- `ModifyTracksDialog`:給定 tracks,`get_edits()` 正確讀出(取消勾選→keep False;下拉→set_default/forced;空白語言/軌名→None);`existing` 預填。
- 既有 `test_mkv_mux.py` 的假 `mux_fn` 補上 `source_flags` 參數後全數通過。
- 既有全套測試維持通過(目前 326)。
