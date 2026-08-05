"""預覽面板:mpv 播放器 + 字幕行清單 + 樣式變更 300ms 防抖熱重載。"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QSlider,
                               QSplitter, QVBoxLayout, QWidget)

from ..ass_style import get_play_res, load_subs
from ..preview import render_preview_ass
from ..preview_readout import OriginalValues, build_readout
from ..profile import Profile
from ..resolution import probe_video_resolution
from .gui_helpers import dialogue_lines, format_timestamp
from .player import MpvPlayerWidget

DEBOUNCE_MS = 300
POLL_MS = 250
_logger = logging.getLogger(__name__)


class PreviewPanel(QWidget):
    readout_changed = Signal(object)

    def __init__(self, get_profile: Callable[[], Profile],
                 player: Optional[QWidget] = None) -> None:
        super().__init__()
        self._get_profile = get_profile
        self.player = player if player is not None else MpvPlayerWidget()
        self._source_sub: Optional[Path] = None
        self._temp_dir = Path(tempfile.mkdtemp(prefix="ass_style_preview_"))
        self._temp_ass = self._temp_dir / "preview.ass"
        self._scrubbing = False
        self._video_path: Optional[Path] = None
        self._video_res: Optional[tuple] = None
        self._source_subs = None

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        open_video = QPushButton("開啟影片…")
        open_video.clicked.connect(self._open_video)
        open_sub = QPushButton("載入字幕…")
        open_sub.clicked.connect(self._open_sub)
        pause = QPushButton("播放 / 暫停")
        pause.clicked.connect(self.player.toggle_pause)
        for btn in (open_video, open_sub, pause):
            # 按鈕不搶鍵盤焦點:避免空白鍵變成「再按一次按鈕」、
            # 方向鍵把焦點移走等混淆行為;快捷鍵交給影片區處理
            btn.setFocusPolicy(Qt.NoFocus)
        bar.addWidget(open_video)
        bar.addWidget(open_sub)
        bar.addWidget(pause)
        bar.addStretch(1)
        root.addLayout(bar)

        # 上半:播放器 + 時間軸(拖曳即時 seek);下半:字幕行清單
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self.player, 1)

        timeline_row = QHBoxLayout()
        self.timeline = QSlider(Qt.Horizontal)
        self.timeline.setRange(0, 0)
        self.timeline.sliderPressed.connect(self._on_slider_pressed)
        self.timeline.sliderReleased.connect(self._on_slider_released)
        self.timeline.sliderMoved.connect(self._on_slider_moved)
        self.time_label = QLabel("0:00:00.00 / 0:00:00.00")
        timeline_row.addWidget(self.timeline, 1)
        timeline_row.addWidget(self.time_label)
        top_layout.addLayout(timeline_row)

        split = QSplitter(Qt.Vertical)
        split.addWidget(top)
        self.line_list = QListWidget()
        self.line_list.setAlternatingRowColors(True)
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

        # 播放位置輪詢(GUI 執行緒,執行緒安全);拖曳中不覆蓋滑桿
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._poll_playback)
        self._poll.start()

    # ---------- 對外 ----------
    def set_media(self, sub_path: Path,
                  video_path: Optional[Path] = None) -> None:
        self._source_sub = Path(sub_path)
        if video_path is not None:
            self._set_video(Path(video_path))
            self.player.load_video(Path(video_path))
        self._refresh_lines()
        self._apply_preview()

    def on_style_changed(self) -> None:
        if self._source_sub is not None:
            self._debounce.start()

    # ---------- 影片解析度 ----------
    def _set_video(self, path: Optional[Path]) -> None:
        """記錄目前影片路徑並探測解析度(供比例檢查用);探測失敗回 None。"""
        self._video_path = Path(path) if path is not None else None
        if self._video_path is None:
            self._video_res = None
            return
        try:
            self._video_res = probe_video_resolution(self._video_path)
        except Exception:
            # probe_video_resolution() 自己已經對 ffprobe 常見的失敗模式
            # (找不到執行檔、逾時、輸出解析不出來)做了防禦,正常情況下
            # 根本不會讓例外傳到這裡——這裡真的接到東西,代表發生了
            # probe_video_resolution() 沒預期到的狀況,不是「選配工具缺
            # 少」那種日常會發生的事,值得留完整 traceback。控制流程不變
            # (仍然回 None,長寬比警告照常跳過,不影響樣式套用本身)。
            _logger.exception(
                "偵測影片解析度時發生未預期的例外:%s", self._video_path)
            self._video_res = None

    # ---------- 檔案選擇 ----------
    def _open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "開啟影片", "",
            "影片 (*.mkv *.mp4 *.avi *.webm *.ts);;所有檔案 (*)")
        if path:
            self._set_video(Path(path))
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
            self._source_subs = None
            return
        self._source_subs = subs
        for line in dialogue_lines(subs):
            item = QListWidgetItem(
                f"{format_timestamp(line.start_ms)}  {line.text}")
            item.setData(Qt.UserRole, line.start_ms)
            self.line_list.addItem(item)
        self.status.setText(
            f"{self._source_sub.name}(共 {self.line_list.count()} 行,點擊跳轉)")

    def _on_line_clicked(self, item: QListWidgetItem) -> None:
        self.player.seek(item.data(Qt.UserRole) / 1000.0)

    # ---------- 換算對照讀出 ----------
    def _lookup_original(self, profile: Profile):
        """回傳來源字幕中第一個存在的目標樣式現值;都不存在回 None。"""
        # 注意:當有多個目標樣式時,apply_profile 會把同一組計算後數值套用到
        # 「所有」符合的樣式,但這裡的「原始」欄位只取第一個存在的目標樣式,
        # 因此對照表的原始值僅反映第一個相符樣式,並非每個樣式各自的原值。
        if self._source_subs is None:
            return None
        for name in profile.target_style_names:
            style = self._source_subs.styles.get(name)
            if style is not None:
                return OriginalValues(
                    fontsize=style.fontsize, outline=style.outline,
                    shadow=style.shadow, margin_l=style.marginl,
                    margin_r=style.marginr, margin_v=style.marginv)
        return None

    def _update_readout(self) -> None:
        if self._source_sub is None or self._source_subs is None:
            return
        try:
            profile = self._get_profile()
        except ValueError:
            return  # 欄位打到一半暫時無效,保留上一次讀出
        play_res_x, play_res_y = get_play_res(self._source_subs)
        original = self._lookup_original(profile)
        video_name = self._video_path.name if self._video_path else None
        data = build_readout(
            profile, play_res_x, play_res_y, original,
            self._source_sub.name, video_name, self._video_res)
        self.readout_changed.emit(data)

    # ---------- 時間軸 ----------
    def _poll_playback(self) -> None:
        """定時更新時間軸與時間標籤;使用者拖曳中則不覆蓋滑桿位置。"""
        duration = self.player.duration()
        position = self.player.position()
        dur_ms = int(duration * 1000) if duration else 0
        pos_ms = int(position * 1000) if position else 0
        if self.timeline.maximum() != dur_ms:
            self.timeline.setRange(0, dur_ms)
        if not self._scrubbing:
            self.timeline.setValue(pos_ms)
            self.time_label.setText(
                f"{format_timestamp(pos_ms)} / {format_timestamp(dur_ms)}")

    def _on_slider_pressed(self) -> None:
        self._scrubbing = True

    def _on_slider_released(self) -> None:
        self._scrubbing = False
        self.player.seek(self.timeline.value() / 1000.0)

    def _on_slider_moved(self, value_ms: int) -> None:
        # 邊拖邊即時 seek,畫面跟著跳;同步更新目前時間文字
        self.player.seek(value_ms / 1000.0)
        dur_ms = self.timeline.maximum()
        self.time_label.setText(
            f"{format_timestamp(value_ms)} / {format_timestamp(dur_ms)}")

    def _apply_preview(self) -> None:
        if self._source_sub is None:
            return
        try:
            profile = self._get_profile()
        except ValueError:
            return  # 欄位打到一半暫時無效,略過本次防抖
        try:
            render_preview_ass(self._source_sub, profile, self._temp_ass)
            if self.player.video_loaded():
                self.player.show_subtitle(self._temp_ass)
        except Exception as exc:
            self.status.setText(f"預覽產生失敗: {exc}")
        self._update_readout()

    def shutdown(self) -> None:
        self._debounce.stop()  # 防止已排定的防抖在關閉後對已清除的暫存目錄觸發
        self._poll.stop()
        self.player.shutdown()
        try:
            if self._temp_ass.exists():
                self._temp_ass.unlink()
            self._temp_dir.rmdir()
        except OSError:
            pass  # 暫存清理失敗不影響關閉
