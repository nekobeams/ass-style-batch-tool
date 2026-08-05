# SRT 字幕輸入支援 Implementation Plan

**Goal:** 讓工具能吃 SRT 字幕輸入,「套用樣式」與「縮放字級」兩種批次模式都支援,輸出一律為 ASS。

**Architecture:** 掃描白名單加 `.srt`;新增共用的輸出檔名正規化函式 `ass_output_name`(`.srt`→`.ass`);套用樣式模式因核心讀寫已格式無關,只需改輸出檔名;縮放模式對非 ASS 來源先用 pysubs2 轉成 ASS 文字再跑既有縮放引擎;輸出資料夾的檔名衝突防護改用正規化後的檔名比對。

**Tech Stack:** pysubs2(格式自動辨識與轉換)、既有 scale_engine 逐行縮放引擎、pytest。

**Spec:** `docs/superpowers/specs/2026-07-21-srt-input-support-design.md`

## Global Constraints

- 工作目錄/repo root:專案根目錄;git branch 由執行者自行建立(從 master HEAD 分出)
- **環境重點**:`python` 是壞的 Windows Store stub,一律用 `py`:`py -m pytest tests -q`
- Python 3.9+ 相容;各檔案已有 `from __future__ import annotations`
- 輸出一律 ASS 內容;輸出檔名規則:`.ass`/`.ssa` 保留原副檔名,`.srt`(及其他非 ASS 家族)正規化成 `.ass`
- SRT 原地覆蓋模式 = 同資料夾產生新 `.ass`、不動原始 `.srt`、不做 `.bak` 備份
- 縮放模式對非 ASS 來源:先 `pysubs2.SSAFile.from_string(text).to_string("ass")` 轉成 ASS 文字再縮放;輸出編碼改用 UTF-8 with BOM(不保留原 SRT 編碼);ASS/SSA 來源維持既有的編碼保留行為
- `scale_engine.py` 模組頂端**刻意不依賴 pysubs2**(既有原則);SRT→ASS 轉換用函式內延遲 import
- 「試算預覽」與真正跑批次共用同一條轉換路徑(不可各寫一套)
- 測試指令:`py -m pytest tests -q`(從 repo root;目前基準 **284 passed**)
- Commit 訊息用 conventional commits(英文)

### 既有介面(本計畫會用到,已實作)

- `ass_style_tool.episode_match`:`SUB_EXTS = {".ass", ".ssa"}`、`find_files(folder)`、`match_pairs(subs, videos)`、`MatchResult`(有 `sub_path: Path` 欄位)
- `ass_style_tool.ass_style`:`load_subs(path) -> pysubs2.SSAFile`(格式無關,自動辨識 SRT)、`save_subs(subs, path)`(一律輸出 `.to_string("ass")` UTF-8-sig)、`apply_profile(subs, profile) -> List[str]`
- `ass_style_tool.batch_runner.process_file(match, profile, output_dir)`:讀檔→套樣式→輸出;`output_dir=None` 表原地(備份 `.bak` 後覆寫)
- `ass_style_tool.scale_engine`:`scale_text(text, options) -> (str, ScaleReport)`(非 ASS 內容丟 `ScaleError`)、`read_subtitle_text(path) -> (str, SubtitleCodec)`、`SubtitleCodec`(`encode(text)->bytes`/`decode(raw)->str`)、`scale_file(path, options, out_path=None)`、`ScaleOptions(factor=..., target_size=...)`
- `ass_style_tool.qt.batch_worker`:`BatchWorker`(套樣式 worker,`run()` 內 `seen_basenames` 衝突防護)、`ScaleWorker`(縮放 worker,`run()` 內呼叫 `scale_file`,同樣有 `seen_basenames`)
- `ass_style_tool.qt.subtitle_tab.SubtitleFileTab._on_dry_run`:試算預覽,呼叫 `read_subtitle_text` + `scale_text`

## File Structure

```
ass_style_tool/
├── episode_match.py       # (修改)SUB_EXTS 加 .srt;新增 ass_output_name()
├── batch_runner.py        # (修改)process_file 輸出用 ass_output_name;掃描警告文字
├── scale_engine.py        # (修改)新增 read_as_ass_text();scale_file 用它 + ass_output_name + 編碼
└── qt/
    ├── batch_worker.py    # (修改)BatchWorker/ScaleWorker 衝突防護 key 改正規化檔名
    └── subtitle_tab.py    # (修改)_on_dry_run 改用 read_as_ass_text
tests/
├── test_episode_match.py
├── test_batch_runner.py   # (可能新建,若不存在)
├── test_scale_engine.py
└── test_subtitle_tab.py
```

---

### Task 1: episode_match — 掃描白名單加 .srt + 輸出檔名正規化函式

**Files:**
- Modify: `ass_style_tool/episode_match.py`
- Test: `tests/test_episode_match.py`

**Interfaces:**
- Consumes: 標準庫 `pathlib.Path`
- Produces:
  - `SUB_EXTS = {".ass", ".ssa", ".srt"}`
  - `ass_output_name(src: Path) -> Path`:`.ass`/`.ssa` 回傳原路徑不變;其他副檔名(如 `.srt`)回傳 `src.with_suffix(".ass")`。大小寫不敏感。

- [ ] **Step 1: 附加失敗測試**

在 `tests/test_episode_match.py` 末尾附加:

```python


# ---------- SRT 支援 ----------

def test_sub_exts_includes_srt():
    from ass_style_tool.episode_match import SUB_EXTS
    assert ".srt" in SUB_EXTS
    assert ".ass" in SUB_EXTS
    assert ".ssa" in SUB_EXTS


def test_ass_output_name_keeps_ass_family():
    from pathlib import Path
    from ass_style_tool.episode_match import ass_output_name
    assert ass_output_name(Path("a/b.ass")) == Path("a/b.ass")
    assert ass_output_name(Path("a/b.ssa")) == Path("a/b.ssa")


def test_ass_output_name_normalizes_srt():
    from pathlib import Path
    from ass_style_tool.episode_match import ass_output_name
    assert ass_output_name(Path("a/movie.srt")) == Path("a/movie.ass")
    # 大小寫不敏感
    assert ass_output_name(Path("a/movie.SRT")) == Path("a/movie.ass")
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_episode_match.py -v -k "srt or ass_output_name"`
Expected: FAIL — `ImportError: cannot import name 'ass_output_name'`(以及 `test_sub_exts_includes_srt` 斷言失敗,`.srt` 不在 `SUB_EXTS`)

- [ ] **Step 3: 實作**

在 `ass_style_tool/episode_match.py` 把:

```python
SUB_EXTS = {".ass", ".ssa"}
```

改成:

```python
SUB_EXTS = {".ass", ".ssa", ".srt"}
```

在 `SUB_EXTS`/`VIDEO_EXTS` 定義之後(`_NON_EPISODE_NUMBERS` 之前)新增:

```python
def ass_output_name(src: Path) -> Path:
    """輸出檔名決策:.ass/.ssa 保留原副檔名(維持既有行為);其他(如 .srt)
    正規化成 .ass(輸出一律為 ASS 內容)。回傳含原目錄的完整路徑。"""
    if src.suffix.lower() in {".ass", ".ssa"}:
        return src
    return src.with_suffix(".ass")
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_episode_match.py -v -k "srt or ass_output_name"`
Expected: 3 passed

- [ ] **Step 5: 跑全套確認無回歸**

Run: `py -m pytest tests -q`
Expected: 287 passed(284 + 3)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/episode_match.py tests/test_episode_match.py
git commit -m "feat: add .srt to scan extensions and ass_output_name helper"
```

---

### Task 2: 套用樣式模式支援 SRT 輸出 + run_batch 衝突防護(batch_runner)

**Files:**
- Modify: `ass_style_tool/batch_runner.py`
- Test: `tests/test_batch_runner.py`(已存在,附加測試函式)

**Interfaces:**
- Consumes: Task 1 的 `ass_output_name`;既有 `load_subs`/`apply_profile`/`save_subs`、`MatchResult`、測試 helper `tests.test_profile.make_profile`(預設 `target_style_names=["Default"]`,正好對應 pysubs2 轉 SRT 後的預設 Style 名)
- Produces:
  - `process_file` 輸出行為——`.srt` 來源輸出 `.ass`(原地=同資料夾新檔不備份;輸出資料夾=正規化檔名);`.ass`/`.ssa` 來源行為完全不變
  - `run_batch` 的輸出資料夾檔名衝突防護 key 改用 `ass_output_name(...).name`(這是 batch_runner 內獨立於 Qt worker 的第二處衝突防護——同資料夾 `ep1.srt`+`ep1.ass` 兩者輸出都是 `ep1.ass`,原本用原始檔名比對會漏判)

**注意**:既有 `test_scan_folder_empty_warns` 只斷言警告含 `"找不到"` 子字串,改警告文字不會壞它;既有 collision 測試用 `.ass` 輸入,正規化後 key 不變,也不受影響。

- [ ] **Step 1: 附加失敗測試**

在 `tests/test_batch_runner.py` 末尾附加(檔案頂端已 import `pysubs2`、`process_file`、`MatchResult`、`make_profile`、`run_batch`、`ScanResult`;下列測試沿用這些,不需新增 import):

```python


# ---------- SRT 輸入支援 ----------

_SRT_SAMPLE = """1
00:00:01,000 --> 00:00:04,000
Hello world
"""


def test_srt_output_dir_produces_ass(tmp_path):
    src = tmp_path / "movie.srt"
    src.write_text(_SRT_SAMPLE, encoding="utf-8")
    out_dir = tmp_path / "out"
    match = MatchResult(sub_path=src, episode=1, video_path=None,
                        status="no_video")
    report = process_file(match, make_profile(), out_dir)
    assert report.status == "ok"
    assert (out_dir / "movie.ass").exists()
    assert not (out_dir / "movie.srt").exists()
    assert src.exists()                            # 原始 .srt 不動
    subs = pysubs2.SSAFile.from_string(
        (out_dir / "movie.ass").read_text(encoding="utf-8-sig"))
    assert len(subs.events) == 1                   # 產出的是合法 ASS


def test_srt_inplace_makes_new_ass_no_backup(tmp_path):
    src = tmp_path / "movie.srt"
    src.write_text(_SRT_SAMPLE, encoding="utf-8")
    match = MatchResult(sub_path=src, episode=1, video_path=None,
                        status="no_video")
    report = process_file(match, make_profile(), None)
    assert report.status == "ok"
    assert (tmp_path / "movie.ass").exists()       # 同資料夾產生 .ass
    assert src.exists()                            # 原 .srt 保留
    assert not (tmp_path / "movie.srt.bak").exists()  # 無備份


def test_run_batch_collision_srt_and_ass_normalized(tmp_path):
    # 同資料夾 ep1.srt 與 ep1.ass,輸出都會是 ep1.ass -> run_batch 應判定衝突
    srt = tmp_path / "ep1.srt"
    srt.write_text(_SRT_SAMPLE, encoding="utf-8")
    ass = tmp_path / "ep1.ass"
    ass.write_text(pysubs2.SSAFile.from_string(_SRT_SAMPLE).to_string("ass"),
                   encoding="utf-8-sig")
    scan = ScanResult(matches=[
        MatchResult(sub_path=srt, episode=1, video_path=None, status="no_video"),
        MatchResult(sub_path=ass, episode=1, video_path=None, status="no_video"),
    ])
    out_dir = tmp_path / "out"
    reports = run_batch(scan, make_profile(), out_dir)
    statuses = [r.status for r in reports]
    assert statuses.count("error") == 1            # 第二個因輸出檔名衝突被擋
    assert (out_dir / "ep1.ass").exists()
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_batch_runner.py -v -k "srt or collision_srt"`
Expected: FAIL — `test_srt_output_dir_produces_ass` 失敗(`.srt` 輸出資料夾模式目前產生 `movie.srt`,`movie.ass` 不存在);`test_run_batch_collision_srt_and_ass_normalized` 失敗(原始檔名 `ep1.srt`/`ep1.ass` 不同名,衝突沒被偵測,兩個都寫入,error 為 0)

- [ ] **Step 3: 實作**

在 `ass_style_tool/batch_runner.py` 的 import 區把:

```python
from .episode_match import MatchResult, find_files, match_pairs
```

改成:

```python
from .episode_match import (MatchResult, ass_output_name, find_files,
                            match_pairs)
```

把 `process_file` 尾端的輸出區塊:

```python
    try:
        if output_dir is None:
            backup = match.sub_path.with_name(match.sub_path.name + ".bak")
            if not backup.exists():
                shutil.copy2(match.sub_path, backup)  # 備份失敗會丟例外 -> 不寫入
            save_subs(subs, match.sub_path)
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            save_subs(subs, output_dir / match.sub_path.name)
    except Exception as exc:
        return FileReport(
            match.sub_path, "error", report.messages + [f"寫入失敗: {exc}"]
        )
    return report
```

改成:

```python
    try:
        target = ass_output_name(match.sub_path)  # .srt -> .ass;.ass/.ssa 不變
        is_ass_family = match.sub_path.suffix.lower() in {".ass", ".ssa"}
        if output_dir is None:
            if is_ass_family:
                backup = match.sub_path.with_name(match.sub_path.name + ".bak")
                if not backup.exists():
                    shutil.copy2(match.sub_path, backup)  # 備份失敗丟例外 -> 不寫入
            # 非 ASS 家族(.srt):輸出新 .ass,不動原檔、不備份
            save_subs(subs, target)
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            save_subs(subs, output_dir / target.name)
    except Exception as exc:
        return FileReport(
            match.sub_path, "error", report.messages + [f"寫入失敗: {exc}"]
        )
    return report
```

把 `run_batch` 迴圈裡的衝突防護區塊:

```python
        if output_dir is not None:
            basename = match.sub_path.name
            if basename in seen_basenames:
```

改成(比對 key 改用正規化後的輸出檔名):

```python
        if output_dir is not None:
            basename = ass_output_name(match.sub_path).name
            if basename in seen_basenames:
```

（`run_batch` 後面 `seen_basenames.add(basename)` 那行沿用同一個 `basename` 區域變數,已自動使用正規化檔名,不需另外改。)

把 `scan_folder` 裡的警告文字:

```python
        scan.warnings.append("資料夾內找不到任何 .ass/.ssa 字幕檔")
```

改成:

```python
        scan.warnings.append("資料夾內找不到任何 .ass/.ssa/.srt 字幕檔")
```

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_batch_runner.py -v`
Expected: 全部通過(既有測試 + 新增 3 個 SRT/collision 測試)

- [ ] **Step 5: 跑全套確認無回歸**

Run: `py -m pytest tests -q`
Expected: 290 passed(287 + 3)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/batch_runner.py tests/test_batch_runner.py
git commit -m "feat: apply-style outputs .ass for .srt input; normalize run_batch collision key"
```

---

### Task 3: 縮放模式支援 SRT(scale_engine + 試算預覽)

**Files:**
- Modify: `ass_style_tool/scale_engine.py`
- Modify: `ass_style_tool/qt/subtitle_tab.py`
- Test: `tests/test_scale_engine.py`

**Interfaces:**
- Consumes: Task 1 的 `ass_output_name`;既有 `read_subtitle_text`、`scale_text`、`SubtitleCodec`、`ScaleOptions`
- Produces:
  - `read_as_ass_text(path: Path) -> Tuple[str, SubtitleCodec, bool]`:回傳可餵給 `scale_text` 的 ASS 文字。`.ass`/`.ssa` 來源回 `(原文字, 原編碼, False)`;其他(`.srt`)回 `(pysubs2 轉出的 ASS 文字, UTF-8-sig 的 SubtitleCodec, True)`
  - `scale_file` 對 `.srt` 來源:原地模式輸出同名 `.ass`(不備份);輸出資料夾模式輸出正規化的 `.ass`;編碼 UTF-8-sig
  - `subtitle_tab._on_dry_run` 改用 `read_as_ass_text`(讓 SRT 也能試算預覽,不丟 ScaleError)

- [ ] **Step 1: 附加失敗測試**

在 `tests/test_scale_engine.py` 末尾附加:

```python


# ---------- SRT 輸入支援 ----------

_SRT_FOR_SCALE = """1
00:00:01,000 --> 00:00:04,000
Hello world
"""


def test_read_as_ass_text_converts_srt(tmp_path):
    from ass_style_tool.scale_engine import read_as_ass_text
    src = tmp_path / "m.srt"
    src.write_text(_SRT_FOR_SCALE, encoding="utf-8")
    text, codec, converted = read_as_ass_text(src)
    assert converted is True
    assert "[V4+ Styles]" in text          # 已轉成 ASS
    # UTF-8 with BOM
    assert codec.encode("x") == b"\xef\xbb\xbfx"


def test_read_as_ass_text_keeps_ass(tmp_path):
    import pysubs2
    from ass_style_tool.scale_engine import read_as_ass_text
    ass_text = pysubs2.SSAFile.from_string(_SRT_FOR_SCALE).to_string("ass")
    src = tmp_path / "m.ass"
    src.write_text(ass_text, encoding="utf-8-sig")
    text, codec, converted = read_as_ass_text(src)
    assert converted is False
    assert "[V4+ Styles]" in text


def test_scale_file_srt_outputs_scaled_ass(tmp_path):
    from ass_style_tool.scale_engine import scale_file, ScaleOptions
    src = tmp_path / "m.srt"
    src.write_text(_SRT_FOR_SCALE, encoding="utf-8")
    out = tmp_path / "out" / "m.srt"     # worker 會傳原名;scale_file 內部正規化
    report = scale_file(src, ScaleOptions(factor=2), out)
    # 實際寫出的是 .ass(副檔名被正規化)
    assert (tmp_path / "out" / "m.ass").exists()
    assert not (tmp_path / "out" / "m.srt").exists()
    # pysubs2 轉出的 Default 預設字級 20 → 縮放 2 倍 → 40
    written = (tmp_path / "out" / "m.ass").read_text(encoding="utf-8-sig")
    assert "Style: Default,Arial,40," in written


def test_scale_file_srt_inplace_new_ass_no_backup(tmp_path):
    from ass_style_tool.scale_engine import scale_file, ScaleOptions
    src = tmp_path / "m.srt"
    src.write_text(_SRT_FOR_SCALE, encoding="utf-8")
    scale_file(src, ScaleOptions(factor=2), None)
    assert (tmp_path / "m.ass").exists()          # 同資料夾新 .ass
    assert src.exists()                            # 原 .srt 保留
    assert not (tmp_path / "m.srt.bak").exists()   # 無備份
```

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_scale_engine.py -v -k "as_ass_text or srt"`
Expected: FAIL — `ImportError: cannot import name 'read_as_ass_text'`

- [ ] **Step 3: 實作 scale_engine**

在 `ass_style_tool/scale_engine.py` 的 `read_subtitle_text` 函式**之後**新增:

```python
def read_as_ass_text(path: Path) -> Tuple[str, SubtitleCodec, bool]:
    """讀檔並回傳可餵給 scale_text 的 ASS 文字。

    .ass/.ssa 來源:原始文字 + 原編碼 + converted=False(保留位元組風格與編碼)。
    其他(如 .srt)來源:pysubs2 轉成 ASS 文字 + UTF-8-with-BOM + converted=True
    (換格式後不再保留原編碼,一律 UTF-8-sig,與 save_subs 一致)。
    """
    text, codec = read_subtitle_text(path)
    if Path(path).suffix.lower() in (".ass", ".ssa"):
        return text, codec, False
    import pysubs2  # 延遲載入:本模組刻意不在頂端依賴 pysubs2
    ass_text = pysubs2.SSAFile.from_string(text).to_string("ass")
    return ass_text, SubtitleCodec(codecs.BOM_UTF8, "utf-8"), True
```

把 `scale_file` 整個函式:

```python
def scale_file(path: Path, options: ScaleOptions,
               out_path: Optional[Path] = None) -> ScaleReport:
    """縮放單一檔案。out_path=None 表原地(先備份 .bak,已存在不覆蓋)。"""
    text, codec = read_subtitle_text(path)
    new_text, report = scale_text(text, options)
    data = codec.encode(new_text)
    if out_path is None:
        backup = Path(path).with_name(Path(path).name + ".bak")
        if not backup.exists():
            shutil.copy2(path, backup)  # 備份失敗丟例外 → 不寫入
        Path(path).write_bytes(data)
    else:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(data)
    return report
```

改成:

```python
def scale_file(path: Path, options: ScaleOptions,
               out_path: Optional[Path] = None) -> ScaleReport:
    """縮放單一檔案。out_path=None 表原地。

    .ass/.ssa:原地=先備份 .bak 再覆寫(保留原編碼);輸出資料夾=同副檔名。
    .srt:輸出一律新 .ass(原地=同資料夾新檔不備份、不動原 .srt;輸出資料夾=
    副檔名正規化為 .ass),編碼 UTF-8-with-BOM。
    """
    from .episode_match import ass_output_name
    text, codec, converted = read_as_ass_text(path)
    new_text, report = scale_text(text, options)
    data = codec.encode(new_text)
    if out_path is None:
        target = ass_output_name(Path(path))  # .srt -> .ass;.ass/.ssa 不變
        if not converted:
            backup = target.with_name(target.name + ".bak")
            if not backup.exists():
                shutil.copy2(path, backup)  # 備份失敗丟例外 → 不寫入
        # 非 ASS 家族:不備份、不動原檔,直接寫出新 .ass
        target.write_bytes(data)
    else:
        target = Path(out_path)
        if converted:
            target = target.with_suffix(".ass")  # 正規化輸出副檔名
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return report
```

- [ ] **Step 4: 實作 subtitle_tab 試算預覽共用同一路徑**

在 `ass_style_tool/qt/subtitle_tab.py` 把 import:

```python
from ..scale_engine import ScaleError, read_subtitle_text, scale_text
```

改成:

```python
from ..scale_engine import ScaleError, read_as_ass_text, scale_text
```

把 `_on_dry_run` 裡:

```python
                text, _codec = read_subtitle_text(match.sub_path)
                _new, report = scale_text(text, options)
```

改成:

```python
                text, _codec, _converted = read_as_ass_text(match.sub_path)
                _new, report = scale_text(text, options)
```

- [ ] **Step 5: 執行測試,確認通過**

Run: `py -m pytest tests/test_scale_engine.py -v -k "as_ass_text or srt"`
Expected: 4 passed

- [ ] **Step 6: 跑全套確認無回歸(重點:既有 scale_engine 與 subtitle_tab 測試不受影響)**

Run: `py -m pytest tests -q`
Expected: 294 passed(290 + 4)

若既有測試失敗,常見原因:`read_subtitle_text` 仍被 subtitle_tab 以外的地方用到(縮放的 `.ass`/Big5 回歸測試應直接測 `scale_file`/`scale_text`,不受本改動影響)。停下來回報。

- [ ] **Step 7: Commit**

```powershell
git add ass_style_tool/scale_engine.py ass_style_tool/qt/subtitle_tab.py tests/test_scale_engine.py
git commit -m "feat: scale mode supports .srt input via pysubs2 conversion"
```

---

### Task 4: Qt worker 輸出資料夾檔名衝突防護改用正規化檔名(batch_worker)

**Files:**
- Modify: `ass_style_tool/qt/batch_worker.py`
- Test: `tests/test_subtitle_worker.py`(新建)

**Interfaces:**
- Consumes: Task 1 的 `ass_output_name`;既有 `BatchWorker`/`ScaleWorker`
- Produces: `BatchWorker`/`ScaleWorker` 兩個 Qt worker 的 `seen_basenames` 改用 `ass_output_name(match.sub_path).name` 當比對 key —— 同資料夾 `ep1.srt` + `ep1.ass` 走輸出資料夾模式時,第二個被正確判為衝突

**注意**:`run_batch`(純函式)的同類衝突防護已在 Task 2 修好;這個 task 只處理 `batch_worker.py` 裡兩個 Qt worker 各自的迴圈(它們不呼叫 `run_batch`,是獨立的迴圈)。`batch_worker.py` 頂端已有 `from ..episode_match import find_files`,只需擴充該行加入 `ass_output_name`。

- [ ] **Step 1: 附加失敗測試**

新建 `tests/test_subtitle_worker.py`:

```python
from __future__ import annotations

import pysubs2

from ass_style_tool.batch_runner import ScanResult
from ass_style_tool.episode_match import MatchResult
from tests.test_profile import make_profile

_SRT = "1\n00:00:01,000 --> 00:00:04,000\nHi\n"


def test_batchworker_collision_srt_vs_ass(qapp, tmp_path):
    from ass_style_tool.qt.batch_worker import BatchWorker
    # 同資料夾 ep1.srt 與 ep1.ass,兩者輸出都會是 ep1.ass -> 應判定衝突
    srt = tmp_path / "ep1.srt"
    srt.write_text(_SRT, encoding="utf-8")
    ass = tmp_path / "ep1.ass"
    ass.write_text(pysubs2.SSAFile.from_string(_SRT).to_string("ass"),
                   encoding="utf-8-sig")
    scan = ScanResult(matches=[
        MatchResult(sub_path=srt, episode=1, video_path=None, status="no_video"),
        MatchResult(sub_path=ass, episode=1, video_path=None, status="no_video"),
    ])
    out_dir = tmp_path / "out"
    worker = BatchWorker(scan, make_profile(), out_dir)
    done = {}
    worker.finished.connect(
        lambda ok, sk, er: done.update(ok=ok, skipped=sk, error=er))
    worker.run()
    # 第一個成功寫 ep1.ass,第二個因輸出檔名衝突被擋 -> error >= 1
    assert done["error"] >= 1
    assert (out_dir / "ep1.ass").exists()
```

（`make_profile()` 預設 `target_style_names=["Default"]`,對應 pysubs2 轉 SRT 後的預設 Style 名。`qapp` fixture 由既有 `tests/conftest.py` 提供。）

- [ ] **Step 2: 執行測試,確認失敗**

Run: `py -m pytest tests/test_subtitle_worker.py -v -k collision`
Expected: FAIL — 目前 `seen_basenames` 用原始檔名(`ep1.srt`/`ep1.ass` 不同名),兩個都被當成不衝突各自寫入,後者靜默覆蓋前者,`done["error"]` 為 0

- [ ] **Step 3: 實作**

在 `ass_style_tool/qt/batch_worker.py` 的 import 區把既有的:

```python
from ..episode_match import find_files
```

改成:

```python
from ..episode_match import ass_output_name, find_files
```

在 `BatchWorker.run()` 中,把衝突檢查與記名兩處的 `match.sub_path.name` 換成正規化檔名。原本迴圈內大致是:

```python
            if self._output_dir is not None and match.sub_path.name in seen_basenames:
                error += 1
                self.file_done.emit(match.sub_path.name, "error")
                self.message.emit(
                    f"    輸出檔名衝突: 已有同名檔案寫入輸出資料夾,略過此檔")
                self.progress.emit(i, total)
                continue
```

改成(在迴圈內、這段之前先算出 `out_name`):

```python
            out_name = ass_output_name(match.sub_path).name
            if self._output_dir is not None and out_name in seen_basenames:
                error += 1
                self.file_done.emit(match.sub_path.name, "error")
                self.message.emit(
                    f"    輸出檔名衝突: 已有同名檔案寫入輸出資料夾,略過此檔")
                self.progress.emit(i, total)
                continue
```

並把成功後記名的那行:

```python
                if self._output_dir is not None:
                    seen_basenames.add(match.sub_path.name)
```

改成:

```python
                if self._output_dir is not None:
                    seen_basenames.add(out_name)
```

在 `ScaleWorker.run()` 中做**相同**的兩處替換(同樣先算 `out_name = ass_output_name(match.sub_path).name`,衝突檢查與記名都用 `out_name`)。ScaleWorker 迴圈內對應片段:

```python
            if self._output_dir is not None and match.sub_path.name in seen_basenames:
```
→ 先加 `out_name = ass_output_name(match.sub_path).name`,再改判斷式用 `out_name`;

```python
                if self._output_dir is not None:
                    seen_basenames.add(match.sub_path.name)
```
→ `seen_basenames.add(out_name)`

（`scale_file` 已於 Task 3 內部把輸出副檔名正規化,ScaleWorker 傳入的 `out = output_dir / match.sub_path.name` 交給 scale_file 後會被寫成 `.ass`;此處只需修正衝突防護的比對 key。)

- [ ] **Step 4: 執行測試,確認通過**

Run: `py -m pytest tests/test_subtitle_worker.py -v -k collision`
Expected: 1 passed

- [ ] **Step 5: 跑全套確認無回歸**

Run: `py -m pytest tests -q`
Expected: 295 passed(294 + 1)

- [ ] **Step 6: Commit**

```powershell
git add ass_style_tool/qt/batch_worker.py tests/test_subtitle_worker.py
git commit -m "fix: collision guard keys by normalized output name (.srt+.ass clash)"
```

---

## 本計畫完成後

工具可吃 SRT 輸入,套用樣式與縮放兩種模式都支援,輸出一律 ASS。之後若要加 WebVTT 等其他 pysubs2 支援的格式,只需擴 `SUB_EXTS` 並確認轉換路徑(`read_as_ass_text` 已對所有非 ASS 家族走 pysubs2 轉換,理論上直接生效)。使用者宜以真實 SRT 檔手動冒煙一輪(套樣式 + 縮放 + 試算預覽)。
